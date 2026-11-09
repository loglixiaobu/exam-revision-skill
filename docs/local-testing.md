# 先试一章 · Try one chapter first

[中文](#中文) · [English](#english)

## 中文

不需要第一次就处理一整学期。选一章你熟悉的材料，才能看出它有没有真的帮上忙。

### 1. 单独建一个课程项目

把课件放在仓库之外的课程项目里，先用副本。安装方法见 [README](../README.md#中文)。已有旧版安装时不要直接覆盖，先在新项目试新版本。

没有合适材料时，可先用[原创示例](../examples/demo-inputs/)。建议之后再试一份含公式、表格或图片的真实材料；这些位置尤其需要人工核对。

### 2. 先要详细版

> 使用 $exam-revision，只处理我选定的这一章，生成详细版复习资料。复杂概念先用通俗例子解释，再给正式定义和适用条件。先出一套小练习卷，答案单独放；看不清的公式和图示列入待核对，不要猜。

重点看这五件事：

- 知识点有没有漏掉？图片、备注、公式里没读到的内容是否明确列出？
- 解释能否帮助理解，而不是换词复述？例子的条件和边界对不对？
- 任取几处引用，能不能定位回原课件，而且原文确实支持结论？
- 独立做一遍小练习，核对每道题的条件、答案与步骤。不是只看脚本有没有报错。
- 保存为文件后，Markdown 导航、表格、公式和题答分离是否好读？不同预览器的公式渲染可能不同。

### 3. 再看精简版和续做

请生成同一章的精简版，检查核心公式及条件是否保留、删减是否有说明。

测试续做时，用可丢弃的复习包副本：完成第一章并保存检查点，在讲义里加一条自己的笔记，然后新开对话，请它继续下一章。预期是**旧笔记保留、变化被报告、新章节单独写入**，而不是悄悄覆盖或把冲突标为已解决。课程只有一章时，可先跳过续做测试。

### 4. 留一条有用的反馈

“哪里不好用 + 希望发生什么 + 实际发生什么”就够了。记录宿主/版本、系统、输入格式和仓库提交或下载日期，方便比较下一版。可通过[反馈模板](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose)提交。

**不要把私人课件、笔记或完整复习包贴到公开 Issue。** 文件名、路径和截图也要脱敏。原创最小例子比整门课上传更容易复现问题。

## English

Start with one familiar chapter, not an entire semester. It is easier to notice missing material and incorrect explanations.

1. **Use a separate course project.** Keep coursework outside this repository and start with copies. Follow the [README](../README.md#english); try upgrades in a fresh project rather than overwriting an existing installation. The [original demo inputs](../examples/demo-inputs/) are a safe starting point.
2. **Ask for a detailed pack and one small practice paper.** Request an intuitive example before formal definitions and conditions, separate answers, and explicit flags for unreadable images or formulas.
3. **Check the result yourself.** Compare coverage with the source, verify a few citations and their actual support, solve every practice question, and inspect navigation, tables, and formulas in your Markdown viewer. Text extraction and structural checks do not prove accuracy.
4. **Compare concise mode.** It should keep essential formulas and conditions while explaining omissions, not merely list terms.
5. **Try resuming on a disposable copy.** Save a checkpoint after chapter one, add a personal annotation, then start a new conversation and continue chapter two. The annotation should remain, differences should be reported, and new work should use new files. Conflicts must not silently disappear. Skip this step for a single-chapter course.
6. **Report what helped or failed.** Include host/version, OS, file type, commit or download date, expected result, and actual result using an [issue template](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose).

**Do not post private course files, notes, or full revision packs in public issues.** Redact identifying filenames, paths, and screenshots. A small original example is usually more useful than a full course upload.
