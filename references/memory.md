# 本地长期记忆

所有命令使用实际 Skill 的绝对路径。`--root` 为可选全局参数，必须放在子命令前；默认从 CODEX_HOME 解析数据目录，不读别的账号资料。

```sh
python3 <skill>/scripts/library.py status
python3 <skill>/scripts/library.py init
python3 <skill>/scripts/library.py import identity <本人照片路径> [更多照片]
python3 <skill>/scripts/library.py import style <参考图片或素材目录> [更多路径]
```

脚本只负责可靠存储，不做图像理解。`import` 与 `register-output` 使用 Python 的 Pillow 校验实际图片；其余命令仅需 Python 标准库。若当前 Python 缺少 Pillow，先找环境提供的依赖运行时。原图按 SHA256 去重、复制，保存来源路径/文件名与导入时间。库中相对路径从数据根目录解析；原来源移走不会影响已复制的资产。索引记录所有候选素材，active revision 的 asset_ids 决定已学会使用的部分；新导入图片不自动替换已有风格。

```text
wayne-ai-blogger-cover/
  identity/index.json
  identity/profile.md                     当前身份分析
  identity/assets/<完整sha256>.<ext>        本人原图
  identity/revisions/<revision>.json|md    旧版本
  style/index.json
  style/Cover_Style_Library.md             当前风格规则
  style/assets/<完整sha256>.<ext>           参考原图
  style/revisions/<revision>.json|md
  jobs/<job-id>/brief.json                 本次输入、选择、版本和确认
  jobs/<job-id>/outputs/                   生成图的持久副本
```

## 分析提交

先查看导入图片，撰写分析 Markdown 与资产ID列表，再提交。ID是文件完整 SHA256，在 import/status 返回值或 index.json 中读取。md 文件不能只有空标题。保存不代表用户确认每项推断；用“观测”“估计”“用户指定”区分依据。

```sh
python3 <skill>/scripts/library.py save-analysis identity --document <profile.md> --asset-ids <id1> <id2>
python3 <skill>/scripts/library.py save-analysis style --document <Cover_Style_Library.md> --asset-ids <id1> <id2>
```

每次更新生成新 revision，保留旧文件。脚本状态报告缺失/损坏原图、缺失分析和无效修订；只有分析与绑定素材完整才报告 ready。不要手动只改 status 来伪造就绪。

**身份 profile.md 字段**：身份来源（用户声明本人）、主参考照片及编号；脸型和五官相对关系；发型发色、眼镜等可见稳定锚点；照片能支持的个人形象；用户指定长期识别元素；姿态/服饰可变项；本人尚未确认的推断。脸型描述服务视觉一致性，不建立身份识别模型、不推断敏感属性。参考博主的形象不写入此库。没有本人照片时保持 pending，不生成虚构分析。

**Cover_Style_Library.md 字段**：来源与版本；所看样本范围/分析方法/局限；八个维度的规则及证据编号；稳定规则与可变项；构图分支及归一化布局建议；字体方向（未知具体字库写未知）；代表样本；模式允许变化；横版适配；用户明确的永久偏好。比例估计标记为视觉估计而非检测结果，建议与原图观测分开。

## 任务与确认

先把 generation.md 中的字段存为 JSON，再创建任务：

```sh
python3 <skill>/scripts/library.py new-job --brief <本次简报.json>
python3 <skill>/scripts/library.py register-output <job-id> 3:4 <生成主封面.png>
python3 <skill>/scripts/library.py approve <job-id> --confirmation '用户确认当前主封面的原话'
python3 <skill>/scripts/library.py register-output <job-id> 16:9 <横版.png>
python3 <skill>/scripts/library.py register-output <job-id> 4:3 <横版.png>
```

确认命令只在用户实际确认后调用，参数引用真实原话；不能由模型编写“我确认”。继续生成前读取任务，检查 confirmation 对应当前主封面的 SHA256；register-output 拒绝未确认横版，主封面重新登记时即清除旧确认。调用生成工具前同样执行此检查，不能先生成再靠文件登记阻挡。像素核对使用 Pillow，不可用时利用工具/系统读取实际尺寸并报告限制，不能绕过确认。

图像原图/分析/任务都以本地文件存储，可跨聊天复用。不保证图像模型每次都能100%还原同一人脸，仍需要原图参考与每次目视核对。新建/续用任务不应索取已有身份照片。仅丢失的身份原图、用户要求更新形象或资料质量不足以支持具体姿态时再请求相应素材。
