# 参与开发

本文面向修改 bb-sync 源码的开发者。普通安装与使用请先阅读 [README.md](README.md)。
实现约定见 [docs/architecture.md](docs/architecture.md)，测试细节见 [docs/testing.md](docs/testing.md)。

## 开发环境

需要：

- Python 3.11 或更高版本；
- [uv](https://docs.astral.sh/uv/)；
- Git；
- Chrome 或 Edge（只有真实跑 `run` / `course list` 时才用到）

macOS 可用 `brew install git uv`；Windows 可按 README 用 `winget` 安装。

初始化并安装开发依赖：

```shell
uv sync
```

## 常用检查

```shell
uv run pytest          # 单元测试 + CLI 端到端测试（默认全离线）
uv run ruff check .    # 静态检查
uv run ruff format .   # 格式化
uv run pyright         # 类型检查
```

提交前至少运行一次能覆盖改动的测试；涉及 CLI 契约、配置或输出通道时，应运行完整测试：

```shell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## 测试分层

- `tests/test_units.py`：纯逻辑单元测试，覆盖配置分层与行级编辑、文件名和分类推断、异常与退出码映射等。
- `tests/test_cli_e2e.py`：把完整命令链跑在进程内的端到端测试，覆盖命令行契约、退出码、stdout/stderr 分流和配置读写。
- `tests/test_update_e2e.py`：自动更新提示的通道行为。

测试环境通过 `tests/conftest.py` 隔离 `BB_SYNC_HOME`、工作目录、系统钥匙串和浏览器 profile 路径，
不应访问真实网站、下载文件或读取真实凭据，也不应真的拉起浏览器进程。fixture 清单与测试相关坑见
[docs/testing.md](docs/testing.md)。

## CI

`.github/workflows/ci.yml` 在 push 和 PR 时运行：

- Ruff lint；
- Ruff format check；
- Pyright；
- pytest；

以上四项跑在 Ubuntu、macOS 与 Windows 三平台矩阵上；另有干净容器里的安装冒烟测试（Ubuntu）。

启动浏览器、登录 Blackboard 和真实下载不属于默认离线测试范围。修改相关逻辑时，请在本地补充可重复的手工验证步骤。

## 代码风格

- 格式与静态检查统一由工具把关：ruff（line-length 100、目标 py311、`known-first-party = ["bb_sync"]`）
  与 ruff format；pyright 用 `standard` 模式且必须零报错。
- 注释 / docstring 用中文，解释职责与「为什么」；模块 docstring 说明该模块的关键约束。
- 全面类型标注，模块头统一 `from __future__ import annotations`。
- 面向用户的错误信息要带可操作的 hint（下一步敲什么命令）。

## 提交习惯

- 提交信息使用中文，格式 `feat|fix|docs|refactor|test|chore(范围): 摘要`；
- 一个提交只处理一件事；
- 不提交密钥、`.env`、浏览器 profile、课程文件、构建产物或其他生成物；
- 只暂存本次改动相关的文件。

## 发布

- 版本号写在 `pyproject.toml`，发布前在本地跑完整四件套（见上文「常用检查」）；
- 打 `v*` tag 触发 `.github/workflows/release.yml`：发布会校验 wheel 文件名与 tag 一致，
  并同步更新 `CHANGELOG.md`。
