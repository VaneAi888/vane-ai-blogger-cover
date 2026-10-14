import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from PIL import Image

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/library.py'
spec=importlib.util.spec_from_file_location('cover_store', SCRIPT)
lib=importlib.util.module_from_spec(spec); spec.loader.exec_module(lib)

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='wayne-cover-test-',dir=None)
        self.base=Path(self.tmp.name).resolve(); self.root=self.base/'data'
        self.picture=self.base/'sample.png'; Image.new('RGB',(300,400),'blue').save(self.picture)
        self.doc=self.base/'analysis.md'; self.doc.write_text('# 测试分析\n仅供隔离测试的合成图片；不是用户的身份资料。\n',encoding='utf-8')
    def tearDown(self): self.tmp.cleanup()
    def establish(self,kind):
        result=lib.import_assets(self.root,kind,[str(self.picture)])
        ids=[a['id'] for a in result['imported']]
        lib.save_analysis(self.root,kind,str(self.doc),ids)
        return ids[0]
    def job(self, identity_free=False):
        sid=self.establish('style')
        if not identity_free: self.establish('identity')
        data={'title':'测试标题','theme':'测试主题','platform':'测试平台','mode':'remix',
            'font_direction':'粗黑体','extra_materials_answer':'无额外素材','extra_materials':[],
            'style_asset_ids':[sid], 'template':'T1','selection_reason':'隔离测试', 'prompt':'测试提示词',
            'dimensions':{'3:4':[300,400],'16:9':[160,90],'4:3':[160,120]},
            'identity_free':identity_free,'identity_free_instruction':'本次无人物' if identity_free else '',
            'confirmation':{'main_sha256':'forged'},'outputs':{'16:9':{'path':'fake'}}}
        f=self.base/'brief.json'; f.write_text(json.dumps(data),encoding='utf-8')
        return lib.new_job(self.root,str(f))['job_id']
    def landscape(self):
        p=self.base/'wide.png'; Image.new('RGB',(160,90),'red').save(p); return p
    def test_pending_status_is_read_only(self):
        output=subprocess.check_output(['python3',str(SCRIPT),'--root',str(self.root),'status'],text=True)
        self.assertEqual(json.loads(output)['identity']['status'],'pending')
        self.assertFalse(self.root.exists())
    def test_dedupe_source_removal_and_process_restart(self):
        self.establish('style'); lib.import_assets(self.root,'style',[str(self.picture)])
        self.picture.unlink()
        output=subprocess.check_output(['python3',str(SCRIPT),'--root',str(self.root),'status'],text=True)
        self.assertEqual(json.loads(output)['style']['status'],'ready')
        self.assertEqual(json.loads(output)['style']['asset_count'],1)
    def test_missing_identity_blocks_normal_job(self):
        sid=self.establish('style')
        f=self.base/'brief.json'; f.write_text(json.dumps({'title':'t','theme':'t','platform':'t','font_direction':'t',
            'extra_materials_answer':'none','template':'T1','selection_reason':'t','prompt':'t','mode':'strict'}))
        with self.assertRaisesRegex(ValueError,'尚未就绪'): lib.new_job(self.root,str(f))
    def test_candidates_and_revisions_are_separate(self):
        self.establish('style'); old=lib.read(self.root/'style/index.json')['active_revision']
        new=self.base/'new.png'; Image.new('RGB',(300,400),'green').save(new)
        candidate=lib.import_assets(self.root,'style',[str(new)])['imported'][0]['id']
        state,revision=lib.inspect(self.root,'style')
        self.assertEqual(state['status'],'ready'); self.assertNotIn(candidate,revision['asset_ids'])
        lib.save_analysis(self.root,'style',str(self.doc),[candidate])
        self.assertTrue((self.root/'style/revisions'/f'{old}.md').exists())
    def test_confirmation_gate_and_revised_main(self):
        j=self.job(); path=lib.job_path(self.root,j)
        self.assertIsNone(lib.read(path)['confirmation']); self.assertFalse(lib.read(path)['outputs'])
        lib.register_output(self.root,j,'3:4',self.picture)
        with self.assertRaisesRegex(ValueError,'尚未获用户确认'): lib.register_output(self.root,j,'16:9',self.landscape())
        lib.approve(self.root,j,'隔离测试中的明确确认')
        lib.register_output(self.root,j,'16:9',self.landscape())
        square=self.base/'four-three.png'; Image.new('RGB',(160,120),'green').save(square)
        lib.register_output(self.root,j,'4:3',square)
        self.assertEqual(set(lib.read(path)['outputs']),{'3:4','16:9','4:3'})
        revised=self.base/'v2.png'; Image.new('RGB',(300,400),'yellow').save(revised)
        lib.register_output(self.root,j,'3:4',revised)
        b=lib.read(path); self.assertIsNone(b['confirmation']); self.assertEqual(set(b['outputs']),{'3:4'})
        self.assertEqual(len(b['output_history']),3)
        with self.assertRaises(ValueError): lib.register_output(self.root,j,'16:9',self.landscape())
    def test_size_and_corruption_report(self):
        j=self.job(); wrong=self.base/'wrong.png'; Image.new('RGB',(320,200)).save(wrong)
        with self.assertRaisesRegex(ValueError,'比例不匹配'): lib.register_output(self.root,j,'3:4',wrong)
        small=self.base/'small.png'; Image.new('RGB',(30,40)).save(small)
        record=lib.register_output(self.root,j,'3:4',small)
        self.assertFalse(record['size_matches_request'])
        lib.approve(self.root,j,'隔离测试确认')
        lib.inside(self.root,record['path']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError): lib.register_output(self.root,j,'16:9',self.landscape())
        (self.root/'style/Cover_Style_Library.md').write_text('changed')
        self.assertEqual(lib.inspect(self.root,'style')[0]['status'],'damaged')
    def test_missing_asset_recovery_and_migration(self):
        self.establish('style')
        index=lib.read(self.root/'style/index.json'); asset=index['assets'][0]
        stored=lib.inside(self.root,asset['path']); stored.unlink()
        self.assertEqual(lib.inspect(self.root,'style')[0]['status'],'damaged')
        lib.import_assets(self.root,'style',[str(self.picture)])
        self.assertEqual(lib.inspect(self.root,'style')[0]['status'],'ready')
        moved=self.base/'migrated'; shutil.copytree(self.root,moved)
        self.assertEqual(lib.inspect(moved,'style')[0]['status'],'ready')
    def test_identity_free_is_explicit_and_stays_pending(self):
        self.job(identity_free=True)
        self.assertEqual(lib.inspect(self.root,'identity')[0]['status'],'pending')
    def test_extra_material_is_persistent(self):
        self.establish('identity'); sid=self.establish('style')
        f=self.base/'brief.json'; data={'title':'t','theme':'t','platform':'t','mode':'free','font_direction':'t',
            'extra_materials_answer':'使用上传产品','extra_materials':[str(self.picture)],'style_asset_ids':[sid],
            'template':'T2','selection_reason':'t','prompt':'t','dimensions':{'3:4':[300,400],'16:9':[160,90],'4:3':[160,120]}}
        f.write_text(json.dumps(data)); j=lib.new_job(self.root,str(f))['job_id']
        self.picture.unlink(); b=lib.read(lib.job_path(self.root,j))
        self.assertTrue(lib.inside(self.root,b['materials'][0]['path']).is_file())

if __name__=='__main__': unittest.main(verbosity=2)
