# bb-sync 测试与质量门禁

本文说明测试怎么分层、为什么默认全离线，以及提交前必须跑什么。
实现约定见 [architecture.md](architecture.md)，日常开发流程见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

## 离线红线

默认测试套件**不登录、不下载、不起浏览器、不碰真实钥匙串**。
只有真实运行 `run` / `course list` / `doctor`（未加 `--skip-network`）才需要本机的
Chrome 或 Edge 和真实凭据；测试与质量检查完全离线。

`tests/conftest.py` 自动把这些边界隔离掉，新测试直接用既有 fixture，不要连接真实环境：

| fixture | 作用 |
| --- | --- |
| `isolated_env`（autouse） | `BB_SYNC_HOME` 与 CWD 都指向临时目录，杜绝读到仓库里的 `config.yaml` |
| `fake_keyring`（autouse） | 换成内存假后端，凭据读写不落真钥匙串 |
| `isolated_home` | 单独拿隔离后的 `BB_SYNC_HOME` 路径 |
| `config_file` | 预置一份隔离的 `config.yaml` 路径 |
| `cli` | 进程内驱动完整 CLI，返回已归一化的退出码 / stdout / stderr |
| `runner` | Click 原生 `CliRunner`，需要看 `output` 等原始字段时用 |

## 测试分层

- `tests/test_units.py`：纯逻辑。配置分层与行级编辑、文件名与分类推断、待办解析与排序、
  异常与退出码映射等。
- `tests/test_cli_e2e.py`：把完整命令链跑在进程内，覆盖命令行契约、退出码、stdout / stderr
  分流、配置读写、冷启动与 help 样式。
- `tests/test_update_e2e.py`：自动更新提示的通道行为（提示走 stderr，stdout 保持干净）。

新行为要带测试：纯逻辑进 `test_units.py`，CLI 契约 / 退出码 / 输出分流进 `test_cli_e2e.py`。

## 提交前门禁（改动必须全绿）

```shell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

涉及 CLI 契约、配置或输出通道的改动必须跑完整四件套；纯文档改动至少自查命令示例。
只跑子集时用 `uv run pytest tests/test_units.py -k <pattern>`。

## CI

`.github/workflows/ci.yml` 在 push 与 PR 时运行：

- `quality`（ubuntu-latest、macos-latest、windows-latest 三平台矩阵）：Ruff lint、
  Ruff format check、Pyright、pytest；
- `install smoke`：干净容器里装 wheel 并冒烟，验证打包与入口可用。

启动浏览器、登录 Blackboard 和真实下载不在 CI 范围内。

## 真实站点逻辑怎么验

登录、抓取、下载这类逻辑无法离线覆盖，改动时在提交信息或 PR 里写清**可重复的手工验证步骤**
（用哪门课、敲什么命令、期望看到什么）。`scripts/debug_*.py` 是为此准备的手工脚本，
会真实登录并访问站点，不要放进测试、也不要在 CI 里跑。

## 测试相关常见坑

- 冷启动回归用例（`test_root_help_lists_subcommands_without_importing_them`、
  `test_help_does_not_import_rich`）会先清掉 `bb_sync.commands.*` / `rich` 再断言 `--help`
  没有把它们导回来；新增 help 逻辑时不要触发真实导入。
- `bb-sync doctor` 的诊断输出走 stderr，stdout 只留给 `--json`；断言输出时先确认通道。
- GitHub Actions 的 run 默认 `set -e`，断言非零退出码需用 `|| true` 兜住（见 `ci.yml` 注释）。
- 不要在测试里真的拉起浏览器进程；`browser` 子命令的用例都用 monkeypatch 假造实例状态。
