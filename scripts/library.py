#!/usr/bin/env python3
"""Persistent local cover assets and approval records; no image generation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

KINDS = ('identity', 'style')
DOCS = {'identity': 'profile.md', 'style': 'Cover_Style_Library.md'}
RATIOS = {'3:4': (3, 4), '16:9': (16, 9), '4:3': (4, 3)}
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    fd, temp = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('索引路径超出数据目录')
    return path


def init(root):
    for kind in KINDS:
        for folder in ('assets', 'revisions'):
            (root / kind / folder).mkdir(parents=True, exist_ok=True)
        path = root / kind / 'index.json'
        if not path.exists():
            atomic(path, {'schema_version': 1, 'kind': kind, 'assets': [], 'active_revision': None})


def inspect(root, kind):
    path = root / kind / 'index.json'
    if not path.exists():
        return {'status': 'pending', 'asset_count': 0}, None
    index = read(path)
    faults = {}
    for asset in index['assets']:
        p = inside(root, asset['path'])
        if not p.is_file() or digest(p) != asset['id']:
            faults[asset['id']] = asset['path']
    revision_id = index.get('active_revision')
    revision = None
    errors = []
    if revision_id:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', revision_id):
            raise ValueError('无效修订ID')
        rev_path = root / kind / 'revisions' / (revision_id + '.json')
        if rev_path.is_file():
            revision = read(rev_path)
            ids = revision.get('asset_ids', [])
            known = {a['id'] for a in index['assets']}
            if not ids or any(i not in known or i in faults for i in ids):
                errors.append('修订绑定素材缺失或损坏')
            for p in (root / kind / DOCS[kind], root / kind / 'revisions' / (revision_id + '.md')):
                if not p.is_file() or digest(p) != revision.get('document_sha256'):
                    errors.append('分析文档缺失或已被改动: ' + str(p))
        else:
            errors.append('修订记录缺失')
    state = 'damaged' if errors else ('ready' if revision else 'pending')
    return {'status': state, 'asset_count': len(index['assets']), 'active_revision': revision_id,
            'document': str(root / kind / DOCS[kind]) if revision_id else None,
            'errors': errors, 'unavailable_assets': list(faults.values())}, revision


def import_assets(root, kind, paths):
    files = []
    for source in paths:
        p = Path(source).expanduser().resolve()
        if p.is_dir():
            files.extend(sorted(x for x in p.rglob('*') if x.is_file() and x.suffix.lower() in EXTENSIONS))
        elif p.is_file() and p.suffix.lower() in EXTENSIONS:
            files.append(p)
        else:
            raise ValueError('需要可读的PNG/JPEG/WebP图片或目录: ' + str(p))
    if not files:
        raise ValueError('没有发现可导入图片')
    from PIL import Image
    # Validate every input before writing anything.
    for p in files:
        with Image.open(p) as im:
            im.verify()
    init(root)
    index_path = root / kind / 'index.json'
    index = read(index_path)
    known = {a['id']: a for a in index['assets']}
    imported = []
    for p in files:
        checksum = digest(p)
        if checksum not in known:
            dest = root / kind / 'assets' / (checksum + p.suffix.lower())
            shutil.copy2(p, dest)
            asset = {'id': checksum, 'path': str(dest.relative_to(root)), 'source': str(p),
                     'original_name': p.name, 'imported_at': now()}
            index['assets'].append(asset)
            known[checksum] = asset
        else:
            dest = inside(root, known[checksum]['path'])
            if not dest.is_file() or digest(dest) != checksum:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)
        imported.append(known[checksum])
    atomic(index_path, index)
    return {'imported': imported, 'asset_count': len(index['assets'])}


def save_analysis(root, kind, document, ids):
    content = Path(document).read_text(encoding='utf-8')
    if not any(line.strip() and not line.lstrip().startswith('#') for line in content.splitlines()):
        raise ValueError('分析文档必须含实际分析内容')
    index_path = root / kind / 'index.json'
    index = read(index_path)
    known = {a['id']: a for a in index['assets']}
    for i in ids:
        if i not in known:
            raise ValueError('素材ID未导入: ' + i)
        if digest(inside(root, known[i]['path'])) != i:
            raise ValueError('素材损坏: ' + i)
    revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    rev_doc = root / kind / 'revisions' / (revision + '.md')
    atomic(rev_doc, content)
    atomic(root / kind / 'revisions' / (revision + '.json'), {
        'revision': revision, 'created_at': now(), 'asset_ids': list(dict.fromkeys(ids)),
        'document_sha256': digest(rev_doc)})
    atomic(root / kind / DOCS[kind], content)
    index['active_revision'] = revision
    atomic(index_path, index)
    return inspect(root, kind)[0]


def new_job(root, source):
    brief = read(source)
    for field in ('title', 'theme', 'platform', 'font_direction', 'extra_materials_answer', 'template', 'selection_reason', 'prompt'):
        if not isinstance(brief.get(field), str) or not brief[field].strip():
            raise ValueError('简报缺少: ' + field)
    if brief.get('mode') not in ('strict', 'remix', 'free'):
        raise ValueError('必须明确选择生成模式')
    if not isinstance(brief.get('identity_free', False), bool):
        raise ValueError('identity_free 必须为布尔值')
    if brief.get('identity_free') and not brief.get('identity_free_instruction', '').strip():
        raise ValueError('无人物例外需记录用户明确要求')
    identity, identity_rev = inspect(root, 'identity')
    style, style_rev = inspect(root, 'style')
    if style['status'] != 'ready' or (not brief.get('identity_free') and identity['status'] != 'ready'):
        raise ValueError('身份库或风格库尚未就绪；先建立/恢复资产')
    ids = brief.get('style_asset_ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 3 or any(i not in style_rev['asset_ids'] for i in ids):
        raise ValueError('需选择已学习风格中的1–3个样本ID')
    for ratio, (a, b) in RATIOS.items():
        size = brief.get('dimensions', {}).get(ratio)
        if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size) or size[0] * b != size[1] * a:
            raise ValueError('尺寸须为正整数并匹配比例: ' + ratio)
    extras = brief.get('extra_materials')
    if not isinstance(extras, list) or any(not isinstance(p, str) or not Path(p).expanduser().is_file() for p in extras):
        raise ValueError('extra_materials 需为可读文件路径列表')
    job_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    job = root / 'jobs' / job_id
    material_refs = []
    for p in extras:
        src = Path(p).expanduser().resolve()
        checksum = digest(src)
        dest = job / 'materials' / (checksum + src.suffix.lower())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        material_refs.append({'path': str(dest.relative_to(root)), 'sha256': checksum, 'source': str(src)})
    # Do not accept caller-provided approval/output state.
    brief.update({'job_id': job_id, 'created_at': now(), 'identity_revision': identity_rev['revision'] if identity_rev else None,
                  'style_revision': style_rev['revision'], 'materials': material_refs,
                  'outputs': {}, 'output_history': [], 'confirmation': None})
    atomic(job / 'brief.json', brief)
    return {'job_id': job_id, 'brief': str(job / 'brief.json')}


def job_path(root, job_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', job_id):
        raise ValueError('无效任务ID')
    return root / 'jobs' / job_id / 'brief.json'


def approved(root, brief):
    main = brief['outputs'].get('3:4')
    confirmation = brief.get('confirmation')
    return bool(main and confirmation and confirmation.get('main_sha256') == main['sha256']
                and inside(root, main['path']).is_file() and digest(inside(root, main['path'])) == main['sha256'])


def register_output(root, job_id, ratio, source):
    path = job_path(root, job_id)
    brief = read(path)
    if ratio != '3:4' and not approved(root, brief):
        raise ValueError('当前3:4版本尚未获用户确认，禁止登记横版')
    from PIL import Image
    src = Path(source).expanduser().resolve()
    with Image.open(src) as im:
        size = list(im.size)
        im.verify()
    a, b = RATIOS[ratio]
    if size[0] * b != size[1] * a:
        raise ValueError('实际文件比例不匹配: ' + str(size))
    checksum = digest(src)
    dest = path.parent / 'outputs' / (ratio.replace(':', 'x') + '-' + checksum + src.suffix.lower())
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    entry = {'path': str(dest.relative_to(root)), 'sha256': checksum, 'size': size,
             'size_matches_request': size == brief['dimensions'][ratio], 'registered_at': now()}
    if ratio != '3:4':
        entry['based_on_main_sha256'] = brief['outputs']['3:4']['sha256']
    if ratio == '3:4':
        for r, old in list(brief['outputs'].items()):
            brief['output_history'].append({'ratio': r, **old})
        brief['outputs'] = {}
        brief['confirmation'] = None
    elif ratio in brief['outputs']:
        brief['output_history'].append({'ratio': ratio, **brief['outputs'][ratio]})
    brief['outputs'][ratio] = entry
    atomic(path, brief)
    return entry


def approve(root, job_id, confirmation):
    if not confirmation.strip():
        raise ValueError('必须记录用户真实确认原话')
    path = job_path(root, job_id)
    brief = read(path)
    main = brief['outputs'].get('3:4')
    if not main or digest(inside(root, main['path'])) != main['sha256']:
        raise ValueError('没有完整的当前3:4主封面')
    brief['confirmation'] = {'text': confirmation, 'at': now(), 'main_sha256': main['sha256']}
    atomic(path, brief)
    return brief['confirmation']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
    parser.add_argument('--root', type=Path, default=base / 'skill-data' / 'vane-ai-blogger-cover')
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('init')
    subs.add_parser('status')
    p = subs.add_parser('import'); p.add_argument('kind', choices=KINDS); p.add_argument('paths', nargs='+')
    p = subs.add_parser('save-analysis'); p.add_argument('kind', choices=KINDS)
    p.add_argument('--document', required=True); p.add_argument('--asset-ids', required=True, nargs='+')
    p = subs.add_parser('new-job'); p.add_argument('--brief', required=True)
    p = subs.add_parser('register-output'); p.add_argument('job_id'); p.add_argument('ratio', choices=RATIOS); p.add_argument('source')
    p = subs.add_parser('approve'); p.add_argument('job_id'); p.add_argument('--confirmation', required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    try:
        if args.command == 'init':
            init(root); result = {'root': str(root), 'initialized': True}
        elif args.command == 'status':
            result = {'root': str(root), **{k: inspect(root, k)[0] for k in KINDS}}
        elif args.command == 'import':
            result = import_assets(root, args.kind, args.paths)
        elif args.command == 'save-analysis':
            result = save_analysis(root, args.kind, args.document, args.asset_ids)
        elif args.command == 'new-job':
            result = new_job(root, args.brief)
        elif args.command == 'register-output':
            result = register_output(root, args.job_id, args.ratio, args.source)
        else:
            result = approve(root, args.job_id, args.confirmation)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
