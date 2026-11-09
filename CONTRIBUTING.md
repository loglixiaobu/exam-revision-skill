# 一起让复习省点心 · Contributing

[中文](#中文) · [English](#english)

## 中文

欢迎报告难用的地方、补测试、改说明。先让一件小事更好用，不用一次重做整个项目。

### 反馈问题

- 先搜 [Issues](https://github.com/loglixiaobu/exam-revision-skill/issues)，再选[问题或建议模板](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose)。
- 写清操作系统、宿主及版本、Python 版本、仓库提交或下载日期，以及输入格式、复现步骤、预期和实际结果。
- **Issue 和 PR 都是公开的。** 用原创微型文档复现；不要提交老师课件、往年卷、个人笔记、完整聊天记录、凭据或含个人信息的路径和截图。无法公开材料时，描述现象即可。
- 内容错误请指出具体知识点或答案步骤。结构检查通过不能证明模型写得正确。
- 试用时可参照[本地试用清单](docs/local-testing.md)，不要求你先完成整门课。

### 提交改进

1. 从最新 `main` 建一个独立分支。每个 PR 集中解决一个问题，大改动先开 Issue 讨论。
2. 阅读相关脚本与测试。脚本须兼容 Python 3.10+；解析逻辑保持本地运行，不添加隐式网络调用。
3. 为行为变化补测试。测试使用临时目录和原创小型文件，不能依赖私人课件、真实账号或外部模型 API。
4. 保留原课件、用户笔记和续做冲突提示。安装器不覆盖既有修改，新增运行文件必须加入 `scripts/install.py` 的显式清单。
5. 同步维护 README 中英文说明，区分实际测过的能力和仍未验证的宿主兼容性。

在仓库根目录运行，建议使用独立 Python 虚拟环境：

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/check_pack.py examples/demo-output --mode both --papers 3
```

检查 `git diff --check` 和 `git status --short`，确认只提交预期文件。PR 写明变化、测试和未验证项，不把自动检查称为学习效果验证。

项目使用 [MIT](LICENSE)。新增内容需由你原创或有权按兼容许可贡献；引入第三方文件时保留其许可和出处，不把它们直接改标成 MIT。

## English

Reports about confusing workflows, focused tests, and clearer instructions are welcome. A small, useful improvement is enough.

### Report a problem

- Search [Issues](https://github.com/loglixiaobu/exam-revision-skill/issues), then use a [report template](https://github.com/loglixiaobu/exam-revision-skill/issues/new/choose).
- Include your OS, host/version, Python version, commit or download date, input format, steps, and expected versus actual results.
- **Issues and PRs are public.** Reproduce problems with small original documents. Do not submit private course materials, past papers, notes, full chat histories, credentials, or identifying paths/screenshots. A description is enough if you cannot share a safe example.
- For content errors, identify the concept or incorrect answer step. Passing structural checks does not prove model-generated content correct.
- The [local testing checklist](docs/local-testing.md#english) helps you try one chapter without generating a whole course first.

### Make a change

1. Branch from current `main`. Keep each PR focused; discuss substantial changes in an issue first.
2. Read the relevant scripts and tests. Maintain Python 3.10+ compatibility and local parsing without implicit network calls.
3. Add tests for changed behavior. Use temporary directories and original small fixtures, not private course files, live accounts, or model APIs.
4. Preserve source files, edited notes, and visible resume conflicts. The installer must not overwrite an existing installation; add new runtime files to the explicit list in `scripts/install.py`.
5. Keep the Chinese and English README aligned. Distinguish tested capabilities from unverified host compatibility.

Run the three commands above from the repository root, preferably in a separate Python virtual environment. Check `git diff --check` and `git status --short` before committing. Describe the change, actual test results, and untested behavior in the PR.

The project uses the [MIT License](LICENSE). Contribute original work or material you may share under compatible terms. Preserve the source and license of third-party files rather than relabeling them as MIT.
