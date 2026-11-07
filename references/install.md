# 安装到当前项目

安装脚本仅使用 Python 标准库，将审核过的运行文件复制到项目的 `.agents/skills/exam-revision`。不会联网、调用 pip、改动系统权限或安装到全局目录，也不会复制课程资料、示例、测试、Git 历史或生成结果。

需要 Python 3.10 或更新版本。以下命令在本仓库根目录运行；macOS/Linux 通常用 `python3`，Windows 可将 `python3` 换成 `py -3`。项目目录必须已经存在，含空格的路径要加引号。

## 先预览，再安装

```sh
python3 scripts/install.py --project "/path/to/your project"
python3 scripts/install.py --project "/path/to/your project" --install
```

不传 `--project` 时使用当前目录。默认只预览，只有 `--install` 才写入文件。安装到当前仓库本身也可以。

## 检查安装和运行环境

```sh
python3 scripts/install.py --project "/path/to/your project" --verify
python3 scripts/install.py --project "/path/to/your project" --verify --check-deps
```

验证会逐文件比较本仓库与安装目录。重复安装相同版本不会重写文件。`--check-deps` 只报告 Python 和 `pypdf` 状态，不安装任何包；未满足 PDF 依赖时返回退出码 2。DOCX/PPTX 解析和输出结构检查不依赖 `pypdf`。检查通过只证明文件一致及基础依赖可发现，不证明 Codex 已刷新技能列表或所有输入都能成功解析。

安装后，在目标项目中开启新的 Codex 对话，要求使用 `exam-revision`。若技能列表尚未显示它，可以请 Codex 读取项目中的 `.agents/skills/exam-revision/SKILL.md` 并按其步骤工作。

## 已有安装和安全边界

- 目标目录有修改、缺失或多余文件（包括多余空目录）时停止，不覆盖、不合并。请先检查并自行备份/移开旧目录，再安装；没有强制覆盖选项。
- 项目目录本身、运行文件、安装路径及已有安装内的符号链接、Windows junction/reparse point 会被拒绝。明确指定的项目目录上层的路径别名会解析为实际路径。
- 安装采用独占创建，不改现有文件权限。若磁盘满、无写入权限或安装中断，可能留下不完整目录；报错会标明位置，不会自动递归删除文件。检查并移开该目录后再试。
- 这是正常本地文件操作的防误写保护，不是抵御其他进程同时恶意替换目录的安全隔离机制。安装时不要让其他程序改动源文件或目标目录。
- 返回码：`0` 成功/预览/一致，`1` 安装或验证失败，`2` 请求依赖检查时缺少所需 PDF 依赖（参数错误也使用 Python argparse 的退出码 `2`）。
