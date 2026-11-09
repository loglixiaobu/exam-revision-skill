# 期末复习 Skill · Exam Revision

**课件攒了一学期，复习不用从“新建空白文档”开始。**

把 **Word、PDF、PPTX 课件**整理成 Markdown 复习包：知识地图、好懂的讲解、例题、考前速查，以及默认 3 套练习卷。答案单独放，先做题时少一点“顺手偷看”。

[中文](#中文) · [English](#english) · [MIT License](LICENSE) · [CI](https://github.com/loglixiaobu/exam-revision-skill/actions/workflows/tests.yml)

<a id="中文"></a>
## 中文

### 先翻两页，看看合不合胃口

- [详细复习示例](examples/demo-output/02-详细复习.md)：概念怎么理解、题怎么一步步做、哪里容易踩坑。
- [精简复习示例](examples/demo-output/02-精简复习.md)：核心结论、使用条件和最小例题，方便考前回顾。
- [自测卷](examples/demo-output/练习卷/A-基础.md) · [独立解析](examples/demo-output/答案/A-解析.md)：做完再对答案。
- [原创 Word / PDF 示例输入](examples/demo-inputs/)：可以直接试跑，不含私人课件。

它适合 Codex 等支持本地 Skill 的工具，不是独立聊天网站。**宿主模型负责理解和讲解，脚本负责提取来源、保存进度和基础检查。**

### 安装：把这段话交给 Codex

> 请将 https://github.com/loglixiaobu/exam-revision-skill 下载到临时目录，阅读 README 和安装脚本后，把 exam-revision Skill 安装到当前项目。如果已有安装，先检查差异，不要覆盖我的修改。安装后检查所需 Python 依赖，并告诉我如何开始。

也可以自己下载仓库，在仓库目录执行。需要 **Python 3.10+**；Windows 可以把 `python` 换成 `py -3`，macOS/Linux 可按环境使用 `python3`。将下方路径替换成已存在的课程项目目录：

```bash
python scripts/install.py --project "你的课程项目目录" --install
```

安装位置是 `项目/.agents/skills/exam-revision/`。安装脚本只复制必要文件，**不联网、不安装依赖、不修改已有安装**。相同版本无需重装；发现已有文件不同、缺失或多余时会停止，避免覆盖你改过的 Skill。升级可先在新项目试用，再确认迁移。

早期版本可能缺少新增的 `LICENSE` 或 `agents/openai.yaml`，安装器也会停止。请保留旧目录，按[升级说明](references/install.md#已有安装和安全边界)备份后迁移，不要直接覆盖或补空文件。

安装后，在目标项目中开启新的 Codex 对话。若技能列表还没显示，可请 Codex 读取 `.agents/skills/exam-revision/SKILL.md` 并按步骤工作。更多选项见[安装说明](references/install.md)。

**WorkBuddy：**官方说明支持本地 Skill 包，可按技能管理界面导入包含 `SKILL.md` 的完整目录，别漏掉 `scripts/` 和 `references/`。不同版本的界面和依赖环境可能不同；本仓库尚未做 WorkBuddy 实机兼容验收，不承诺所有版本即装即用。

### 开始：给课件，再说一句话

把资料放进课程项目的 `课件` 文件夹，或按宿主支持的方式上传，然后说：

> 使用 $exam-revision，把课件整理成详细版期末复习包，复杂概念用容易理解的例子讲清楚，再出3套练习卷，答案单独放。输出到“复习包”。

PPT 课件也可以这样说：

> 读取“课件”里的 PPTX、Word 和 PDF。PPTX 的备注也一起看，图片和公式看不清的地方列出来，不要猜。生成详细版复习包，输出到新的“复习包”目录。

不用先填一张配置表。未指定时默认 **详细版、中文、3 套自编练习卷**：A 基础、B 综合、C 易错与迁移。考试范围、题型和时长未知，会明确标记“未提供”；练习卷不是押题卷。

| 你现在需要什么 | 可以这样说 |
|---|---|
| 想学明白 | “用详细版，先给直观例子，再讲正式定义和解题步骤。” |
| 考前快速回顾 | “用精简版，保留核心知识点、公式、算法和代表例题，不要省略使用条件。” |
| 两种都要 | “详细版用于学习，精简版用于考前回顾，共用练习卷和答案。” |
| 上次没做完 | “继续复习包，先查看已有进度，从未完成的章节接着做，不要覆盖我改过的笔记。” |

更多可复制的用法见[试用提示词](examples/试用提示词.md)。

**第一次试用？** 先选熟悉的一章，照[本地试用清单](docs/local-testing.md)核对讲解、引用、答案和续做。项目仍在迭代，欢迎告诉我们哪一步不省心。

### PPT、Word、PDF，分别能读到哪里？

| 输入 | 能提取什么 | 需要留意 |
|---|---|---|
| `.pptx` | 幻灯片文字、表格和演讲者备注 | 按实际幻灯片顺序定位，备注单独标记；文字提取不等于看懂整张幻灯片。 |
| `.docx` | 正文段落和表格 | 按正文块定位，不伪造随软件排版变化的 Word 页码。 |
| 文字型 `.pdf` | 可提取的文字 | 按物理页码定位；扫描页可能没有可用文字。 |
| 旧 `.ppt` / `.doc` | 不直接解析 | 用可信工具将 `.ppt` 转成 `.pptx` 或 PDF，将 `.doc` 转成 `.docx`。**改后缀不算转换。** |

**“提取到文字”不等于“整份课件都看完了”。** 图片、手写、复杂公式、图表和布局关系仍需额外视觉核对；PPTX 里的截图或示意图也一样。脚本不提供 OCR 或视觉理解。宿主有合适能力时可进一步核对，否则把遗漏和不确定内容列入待核对清单。转换旧文件后也要检查公式、图片和备注是否保留。

Python 提取依赖可在仓库目录安装，先遵循宿主的权限流程：

```bash
python -m pip install -r requirements.txt
```

脚本本身不调用网络 API。**宿主模型的收费和数据处理规则仍然适用**，本地脚本不代表课件一定不会发送给云端模型。输入细节见[输入说明](references/input-handling.md)。

### 复习包里有什么？

| 文件 | 用途 |
|---|---|
| `00-开始阅读.md` | 先看范围、限制和推荐顺序 |
| `01-知识地图.md` | 找章节和知识点 |
| `02-详细复习.md` / `02-精简复习.md` | 对应模式的讲义；长课程链接到章节文件 |
| `03-考前速查.md` | 快速找公式、概念和步骤 |
| `04-覆盖与待核对.md` | 看已覆盖内容、精简省略项和资料疑点 |
| `练习卷/` 与 `答案/` | 默认 3 套自编练习及独立解析 |
| `_sources/` | 来源文本与定位清单 |

复杂概念按“**一句话理解 → 直观例子 → 正式定义与条件 → 逐步例题 → 易错点**”展开。类比会说明适用边界，精简版也保留必要条件。目标是方便理解和核对，不是把课件换个格式再抄一遍。

### 课很多，今天做不完怎么办？

每完成一章就保存文件和检查点。下次对话先读取本地进度，再接着做。长课程分章保存，主讲义负责导航，不把整学期挤成一篇超长笔记。

进度工具会检查原课件和已登记输出有没有变化：

- **你改过笔记：**保留修改并报告差异；符合条件时可继续写全新章节，已有冲突仍会保留，不会假装全部检查通过。
- **课件新增、变动或文件丢失：**停止登记进度，先处理版本差异，避免把新旧资料混在一起。
- **需要最终一致的修订版：**另建输出目录，明确保留或迁移你的笔记。

这不是后台自动任务，需要在宿主里继续发起执行。检查点也不是备份或安全隔离，不能从代码层阻止宿主绕过流程改写文件。技术用法见[续做说明](references/resume.md)，内部检查点不需要手工编辑。

### 几件先说清楚的事

- 脚本能检查文件、改动、引用 ID、本地链接、请求的模式和卷数，以及可识别的题答编号。有检查点时，结构检查默认读取保存的模式和卷数，也可显式指定；代码示例中的伪引用会被忽略。特殊编号仍需人工核对。
- 模型负责解释、例题、练习题和答案。**检查通过不代表引用一定支持结论，也不代表答案一定正确。**
- 没有零幻觉、必考、全覆盖或提分保证。首次试用建议选自己熟悉的一章，核对重要知识点和全部答案，再扩大范围。
- 工作流程要求保留原资料，不自动发布课件或共享复习包。公开仓库只放原创微型示例；老师的课件、往年卷和私人笔记请放在仓库外。

### 开发与测试

在仓库目录运行：

```bash
python -m unittest discover -s tests -v
python scripts/check_pack.py examples/demo-output --mode both --papers 3
```

GitHub Actions 配置会在 Ubuntu、Windows、macOS 的 Python 3.12 上运行测试，并在 Ubuntu 检查最低支持的 Python 3.10。**配置存在不代表三平台已通过**，请以对应提交的实际运行结果为准；脚本测试也不等于 Codex 或 WorkBuddy 应用级验收。

测试范围和未验证项见[测试报告](TEST_REPORT.md)，技能入口为 [SKILL.md](SKILL.md)。

### 帮它变得更好用

安装卡住、讲解绕口、引用对不上？欢迎[反馈问题或建议](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose)。模板会提醒需要哪些信息，也欢迎直接用中文描述。**Issue 是公开的，请不要上传私人课件、个人笔记或完整复习包。** 参与开发见[贡献指南](CONTRIBUTING.md)。

### 许可证与材料归属

本项目的原创代码、说明和仓库内原创示例采用 [MIT 许可证](LICENSE)，可修改、分发和商用，需保留版权与许可声明；不提供担保。

该许可**不会改变你输入的课件、第三方材料或生成内容中引用材料的权利归属**，也不自动授予公开复习包的权限。依赖项保留各自的许可证，宿主 AI 工具的使用与数据条款仍然适用。安装脚本会保留项目的 `LICENSE` 文件。

官方安装参考：[Codex Skills](https://learn.chatgpt.com/docs/build-skills) · [WorkBuddy Skills](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)

<a id="english"></a>
## English

**Start revising a semester's worth of material without staring at a blank page.**

Turn **Word, PDF, and PPTX course materials** into a Markdown revision pack: a knowledge map, approachable explanations, worked examples, a quick reference, and **3 practice papers by default**. Answers live in separate files, so you can try the questions before peeking.

[Back to 中文](#中文)

### Take a look before installing

The included demo is in Chinese:

- [Detailed notes](examples/demo-output/02-详细复习.md): concepts, intuitive examples, formal steps, and common mistakes.
- [Concise notes](examples/demo-output/02-精简复习.md): core results, essential conditions, and small worked examples.
- [Practice paper](examples/demo-output/练习卷/A-基础.md) · [Separate answers](examples/demo-output/答案/A-解析.md)
- [Original Word / PDF demo inputs](examples/demo-inputs/): ready to try, with no private course materials.

This is a local Skill for tools such as Codex, not a standalone chat app. **The host model explains the material and writes the pack. The scripts extract sources, save progress, and run basic checks.**

### Install: give Codex this prompt

> Download https://github.com/loglixiaobu/exam-revision-skill to a temporary directory. Read the README and installer, then install the exam-revision Skill in the current project. If an installation already exists, check the differences first and do not overwrite my changes. Check the required Python dependencies afterward and tell me how to start.

Or download the repository and run the following from its root. You need **Python 3.10+**. On Windows, replace `python` with `py -3` if needed; on macOS/Linux, use `python3` if that is your Python command. Replace `YOUR_COURSE_PROJECT` with an existing course project directory:

```bash
python scripts/install.py --project "YOUR_COURSE_PROJECT" --install
```

The destination is `PROJECT/.agents/skills/exam-revision/`. The installer copies only the required files. It **does not access the network, install dependencies, or modify an existing installation**. Identical files need no reinstall; changed, missing, or extra files make it stop rather than overwrite your work. For upgrades, try a new project first, then decide what to migrate.

Older installations may lack the new `LICENSE` or `agents/openai.yaml`; the installer stops for those differences too. Keep the old directory, back it up and move it aside before installing, then compare and migrate your customizations. Do not overwrite it or add empty files to silence the check.

Start a new Codex conversation in the target project after installation. If the Skill does not appear yet, ask Codex to read `.agents/skills/exam-revision/SKILL.md` and follow it. See the [installation guide](references/install.md) for more options.

**WorkBuddy:** its official documentation supports local Skill packages. Use its skill-management interface to import the complete directory containing `SKILL.md`, including `scripts/` and `references/`. Interfaces and dependency environments may vary by version. This repository has not completed on-device WorkBuddy compatibility testing, so plug-and-play compatibility is not guaranteed.

### Start with your materials and one sentence

Put your materials in a `course-materials` folder in the project, or upload them as supported by your host, then say:

> Use $exam-revision to turn “course-materials” into a detailed exam revision pack in English. Explain difficult ideas with approachable examples, create 3 practice papers, and keep the answers separate. Save everything to a new “revision-pack” directory.

For a mix of slide decks and documents:

> Read the PPTX, Word, and PDF files in “course-materials”. Include PPTX speaker notes. Flag any images or formulas you cannot verify rather than guessing. Create a detailed revision pack in English in a new “revision-pack” directory.

No long setup form required. Unless you specify otherwise, the defaults are **detailed mode, Chinese, and 3 original practice papers**: A for foundations, B for combined applications, and C for common mistakes and transfer. Unknown exam scope, question formats, and duration are marked as not provided. These are practice papers, not predictions of the actual exam.

| What you need | What to ask for |
|---|---|
| Learn it properly | “Use detailed mode. Start with an intuitive example, then explain the formal definition and solution steps.” |
| Review before the exam | “Use concise mode. Keep core concepts, formulas, algorithms, and representative examples, including their conditions.” |
| Both versions | “Create detailed notes for learning and concise notes for review, sharing the practice papers and answers.” |
| Pick up where you stopped | “Continue the revision pack. Check saved progress first, resume unfinished chapters, and do not overwrite my edited notes.” |

More examples are available in the [sample prompts](examples/试用提示词.md), in Chinese.

**First try?** Use one familiar chapter and the [local testing checklist](docs/local-testing.md#english) to check explanations, citations, answers, and resuming. The project is still being refined; feedback about confusing steps is welcome.

### What can it read?

| Input | Extracted content | Keep in mind |
|---|---|---|
| `.pptx` | Slide text, tables, and speaker notes | Located in actual slide order, with notes marked separately. Text extraction does not capture everything a slide communicates. |
| `.docx` | Body paragraphs and tables | Located by body block, not invented Word page numbers that change with layout. |
| Text-based `.pdf` | Extractable text | Located by physical page number. Scanned pages may have no usable text. |
| Legacy `.ppt` / `.doc` | Not parsed directly | Use a trusted tool to convert `.ppt` to `.pptx` or PDF, and `.doc` to `.docx`. **Renaming the extension is not conversion.** |

**Extracted text is not proof that the whole document was read.** Images, handwriting, complex formulas, charts, and spatial relationships still need separate visual review. That includes screenshots and diagrams inside PPTX files. The scripts do not provide OCR or visual understanding. If the host has suitable tools, it can review those elements; otherwise, gaps and uncertainties belong on the review checklist. Check formulas, images, and notes after converting legacy files, too.

Install the extraction dependencies from the repository root, following your host's permission process:

```bash
python -m pip install -r requirements.txt
```

The scripts themselves make no network API calls. **Your host model's pricing and data-handling rules still apply.** Local scripts do not mean your course materials will necessarily stay off cloud models. See [input handling](references/input-handling.md) for details.

### What is in the pack?

These are the documented output names; the examples use Chinese filenames:

| File | Purpose |
|---|---|
| `00-开始阅读.md` | Scope, limitations, and suggested reading order |
| `01-知识地图.md` | Chapter and knowledge-point navigation |
| `02-详细复习.md` / `02-精简复习.md` | Detailed / concise notes, with chapter links for longer courses |
| `03-考前速查.md` | Quick reference for formulas, concepts, and procedures |
| `04-覆盖与待核对.md` | Coverage, concise-mode omissions, and items needing review |
| `练习卷/` and `答案/` | 3 original practice papers by default, with separate solutions |
| `_sources/` | Extracted text and source locations |

Difficult ideas follow **one-sentence intuition → concrete example → formal definition and conditions → worked example → common mistakes**. Analogies explain their limits. Concise mode keeps the conditions needed to use a result correctly, rather than reducing the course to a list of terms.

### Too much for one sitting?

Save a chapter, save a checkpoint, and continue later. A new conversation reads progress from disk instead of relying on chat memory. Long courses use separate chapter files, with the main notes providing navigation.

The progress tool checks source files and registered outputs for changes:

- **You edited your notes:** it keeps the edits and reports the differences. When the documented conditions are met, new chapters can be added while the old conflicts remain visible. That is not an all-clear result.
- **Sources changed, new materials appeared, or files went missing:** progress registration stops so versions do not silently get mixed together.
- **You need a consistent revised pack:** create a new output directory and explicitly preserve or migrate your notes.

This is not an automatic background task. You must ask the host to continue. Checkpoints are not backups or a security boundary, and cannot prevent the host from bypassing the workflow and writing files directly. See the [resume guide](references/resume.md); internal checkpoints do not need manual editing.

### A few honest limits

- Scripts check files, changes, source IDs, local links, requested modes and paper counts, and recognizable question/answer numbering. When checkpoints exist, the pack checker uses saved mode/count settings by default, unless specified explicitly. It ignores example citations inside code; unusual numbering still needs manual review.
- The model writes explanations, examples, questions, and answers. **Passing the checks does not prove that a citation supports a claim or that an answer is correct.**
- There is no guarantee of zero hallucinations, complete coverage, exam predictions, or better grades. Start with a familiar chapter, check the important points and every answer, then expand.
- The workflow requires original materials to be preserved and does not automatically publish course files or share revision packs. The public repository contains only original miniature examples. Keep teachers' slides, past papers, and private notes outside the repository.

### Development and tests

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python scripts/check_pack.py examples/demo-output --mode both --papers 3
```

GitHub Actions is configured to run Python 3.12 tests on Ubuntu, Windows, and macOS, plus the minimum supported Python 3.10 on Ubuntu. **A workflow file does not prove that all three platforms passed.** Check the actual runs for the relevant commit. Script tests are also not application-level acceptance tests for Codex or WorkBuddy.

See the [test report](TEST_REPORT.md) for tested scope and remaining gaps, and [SKILL.md](SKILL.md) for the Skill entry point. The supporting technical guides are currently in Chinese.

### Help make it easier to use

Installation trouble, a confusing explanation, or a citation that does not match? [Report a problem or suggestion](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose). The templates list useful details; Chinese and English are both welcome. **Issues are public. Do not upload private course materials, notes, or full revision packs.** See the [contribution guide](CONTRIBUTING.md#english) for development instructions.

### License and course-material rights

The project's original code, documentation, and included original examples use the [MIT License](LICENSE). You may modify, redistribute, and use them commercially while retaining the copyright and permission notices. No warranty is provided.

This license **does not change rights in your input coursework, third-party materials, or material quoted in generated outputs**, and does not automatically authorize publishing a revision pack. Dependencies keep their own licenses; your host AI tool's terms and data policies still apply. The installer preserves the project's `LICENSE` file.

Official installation references: [Codex Skills](https://learn.chatgpt.com/docs/build-skills) · [WorkBuddy Skills](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)
