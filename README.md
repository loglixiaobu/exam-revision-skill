# 期末复习 Skill · Exam Revision

[中文](#中文) · [English](#english) · [MIT](LICENSE)

<a id="中文"></a>
## 中文

**课件攒了一学期，复习不用从空白文档开始。** 用 Codex 把 DOCX、PDF 和 PPTX 整理成 Markdown 复习包：知识地图、讲解与例题、考前速查，以及默认 3 套自编练习卷（答案单独放）。可以选详细版、精简版或两版都要。

[详细版示例](examples/demo-output/02-详细复习.md) · [精简版示例](examples/demo-output/02-精简复习.md) · [练习卷](examples/demo-output/练习卷/A-基础.md) · [答案](examples/demo-output/答案/A-解析.md)

### 安装

下载本仓库，在仓库根目录运行（Python 3.10+，课程目录须已存在）：

```sh
python scripts/install.py --project "你的课程目录" --install
python -m pip install -r requirements.txt
```

第二条安装 PDF 文字提取依赖；只用 DOCX 或 PPTX 可以跳过。安装器不覆盖已有 Skill。[安装与升级说明](references/install.md)

WorkBuddy 可尝试[导入完整 Skill 目录](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)，本仓库尚未做实机兼容测试。

### 使用

在课程目录打开新的 Codex 对话，把课件放入 `课件/`，然后说：

> 用 $exam-revision 把「课件」整理成详细复习包，难点用例子讲清楚，出 3 套练习卷，答案单独放。

没做完就说「继续复习包，先读进度，不覆盖我改过的笔记」。默认使用中文，练习题不是押题。

### 需要时再看

- [输入与限制](references/input-handling.md) · [续做说明](references/resume.md) · [先试一章](docs/local-testing.md#中文)
- [贡献与测试](CONTRIBUTING.md#中文) · [反馈问题](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose)

脚本不做 OCR；扫描页、图片和复杂公式需另行核对。题目和答案由宿主模型生成，请自行复核。使用云端模型时，课件仍受宿主的数据处理规则约束；不要把私人课件贴到公开 Issue。

<a id="english"></a>
## English

**A semester of course files, one revision pack.** Use Codex to turn DOCX, PDF, and PPTX files into Markdown notes with a topic map, worked examples, a quick reference, and three original practice papers with separate answers by default. Choose detailed notes, concise notes, or both.

Chinese demos: [Detailed](examples/demo-output/02-详细复习.md) · [Concise](examples/demo-output/02-精简复习.md) · [Practice paper](examples/demo-output/练习卷/A-基础.md) · [Answers](examples/demo-output/答案/A-解析.md)

### Install

Download this repository and run from its root (Python 3.10+; the course directory must already exist):

```sh
python scripts/install.py --project "YOUR_COURSE_DIR" --install
python -m pip install -r requirements.txt
```

The second command installs the PDF text extraction dependency. Skip it for DOCX or PPTX only. The installer does not overwrite an existing Skill. See the [install and upgrade guide](references/install.md) (Chinese).

For WorkBuddy, see [how to import the full Skill folder](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market). This project has not been tested in WorkBuddy.

### Use

Start a new Codex chat in your course directory and put your files in `course-materials/`. Then ask:

> Use $exam-revision to turn “course-materials” into detailed notes in English. Explain difficult topics with examples, create three practice papers, and keep the answers separate.

To pick up later, ask it to check saved progress and continue without overwriting your edits. Chinese is the default output language. The papers are for practice, not exam predictions.

### More help

- [Input limits](references/input-handling.md) · [Resuming](references/resume.md) (Chinese) · [Try one chapter](docs/local-testing.md#english)
- [Contributing and tests](CONTRIBUTING.md#english) · [Report an issue](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose)

There is no OCR. Check scans, images, complex formulas, and model-written answers separately. If you use a cloud model, your materials are subject to its data policies. Keep private materials out of public issues.
