# Exam Revision · 期末复习 Skill

把 Word/PDF 课程资料整理成详细或精简的 Markdown 复习包，附三套练习卷与独立解析。**这是供宿主模型执行的 Skill，不是运行一个脚本就自动生成讲义的独立应用。**

## 两种模式
- 详细：大部分实质知识点、公式、算法、主要例题及讲解。
- 精简：核心知识点、核心公式/算法、代表例题及易错点。
- 可同时生成两种。默认三套自编练习卷，不能保证命中真实考题。

## 安装与试用
解压后，找到含 `SKILL.md` 的 `exam-revision` 文件夹，避免重复嵌套。

### Codex
推荐项目级安装：复制整个文件夹到项目的 `.agents/skills/exam-revision/`。重新打开该项目或开启新对话，然后发送：

> 使用 $exam-revision，读取 ./课件 中的 Word 和 PDF，生成详细版期末复习包，附3套练习卷和单独答案，输出到 ./复习包-详细。考试范围未提供，不要猜测必考内容。

精简版将“详细版”改成“精简版”；也可以说“详细和精简都生成”。资料可按宿主支持的方式上传，或放进本地项目。全局安装目录请以你所用 Codex 版本的官方技能设置为准；本包不自动修改配置。

### WorkBuddy
官方技能说明支持上传本地技能包。按你版本的“技能”管理界面导入本包，或导入包含 `SKILL.md` 的文件夹，然后用自然语言要求“使用 exam-revision 整理课件”。界面名称可能随版本变化；此包未做 WorkBuddy 实机验证。如果未识别，可把 `SKILL.md` 及整个文件夹交给工具，要求读取后执行，而不是仅上传 SKILL.md 丢掉脚本和参考文件。

兼容说明：核心指令不依赖专有工具；脚本需要 Python 3.10+。Codex 与 WorkBuddy 的模型能力、权限、视觉读取和依赖环境不同，不能保证同一包在所有版本即装即用。

官方参考：
- https://learn.chatgpt.com/docs/build-skills
- https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market

## 直接试用原创示例

本仓库 `examples/demo-inputs/` 是原创微型课程：2页PDF与1份DOCX；`examples/demo-output/` 是实际生成的双模式复习包、3套练习卷及独立答案。它用于演示流程，不代表真实课程的质量保证。

可以对模型说：“使用 exam-revision，读取 examples/demo-inputs，生成详细与精简两版、3套练习卷，输出到新目录 demo-my-result。”

## 输入与依赖
支持 `.docx`、文字型 `.pdf`。旧 `.doc` 先在 Word/LibreOffice 另存为 `.docx`。扫描 PDF、手写内容、图表及复杂公式需要宿主视觉/OCR能力与人工核对；提取脚本不提供 OCR。

使用本机的 Python（Windows 也可用 `py -3`）：
```
python -m pip install -r path/to/exam-revision/requirements.txt
python path/to/exam-revision/scripts/extract_sources.py ./课件 --out ./复习包/_sources
```
脚本不访问网络，不上传资料；安装依赖本身会访问包仓库。生成复习内容仍由 Codex/WorkBuddy 的模型完成，模型可能在云端处理资料，相关费用和数据处理规则取决于宿主。

返回码：0=提取完成（仍可能有警告）；2=有失败/不支持文件，已写出清单；1=整体错误。请阅读清单，不要把非零返回简单等同于没有结果。输出目录已存在时拒绝覆盖，重跑请换新目录。

## 交付目录
开始阅读、知识地图、详细/精简讲义、考前速查、覆盖与待核对清单、练习卷/、答案/、_sources/。
PDF 引用按物理页；DOCX 引用按正文块，不伪造 Word 页码。引用ID可检查，但仍需核对内容是否真正得到来源支持。

## 隐私与质量
不修改原课件；不会自动发布或分享。不要将老师的课件和真题未经许可上传公开仓库。生成材料用于复习，重要公式、答案和课程范围需核验。没有“零幻觉”“全覆盖”“必考”保证。

## 验证
```
python -m unittest discover -s tests -v
python scripts/check_pack.py ./复习包
```
测试针对解析和结构，不证明模型能正确理解任何课程。`examples/试用提示词.md` 可直接复制；测试边界见 `TEST_REPORT.md`。
