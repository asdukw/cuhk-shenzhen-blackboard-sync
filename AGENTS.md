# AGENTS.md

给 AI 编码代理的最小必要上下文。展开细节按需查阅：
[architecture.md](docs/architecture.md)（目录与实现约定）、[testing.md](docs/testing.md)（测试与门禁）、
[CONTRIBUTING.md](CONTRIBUTING.md)（开发流程、风格、发布）。

## 项目速览

- Blackboard 课程资源同步 CLI：登录港中深 `bb.cuhk.edu.cn`（ADFS SSO），把课件 / 作业 / 指导
  增量下载到课程目录，公告存 `announcements.md`，全部待办汇总到 `due.md`。
- **只适配** `bb.cuhk.edu.cn` 及其 ADFS 登录流程；不要为其他站点引入通用化假设。
- 目标平台 Windows 10/11（PowerShell）与 macOS（Intel / Apple Silicon，zsh / bash）；
  Python ≥3.11，技术栈 Typer + Click、pydantic v2、PyYAML、rich、keyring、Playwright。
- 代码注释、docstring、提交信息、文档一律中文；命令与路径示例同时覆盖 PowerShell 与 zsh / bash。

## 五条不能破的红线

1. **输出分流**：结果走 stdout、诊断走 stderr，一律经 `core.output.Console`；禁止 `print`，
   不要打开 Rich markup（诊断里满是 `[new]`、`[作业]` 这类方括号）。`--json` 时 stdout 只有一个 JSON 文档。
2. **错误语义化**：可预期错误抛 `BbSyncError` 子类（`core/errors.py`），退出码由自带的 `exit_code`
   决定；不要裸 `sys.exit(1)` 或临时整数。
3. **冷启动**：`cli.py` / `context.py` / `commands/__init__.py` 顶层不得导入 playwright、pydantic、rich；
   命令模块靠 `LazyGroup` 延迟导入，`--version` / `--help` 必须快速返回。
4. **配置**：CLI > `BB_SYNC_<KEY>` > config.yaml > 内置默认；`config set/unset` 必须走
   `core/config_store.py` 的行级编辑，保留注释与未知键，不要整份 YAML 重写。
5. **浏览器**：只驱动本机已装的 Chrome / Edge（分离进程 + CDP + 自有 profile），不引入 Node / npm
   或任何需联网下载的运行时；默认跑完即关，关闭只走 CDP `Browser.close`，绝不读写用户的日常 profile。

## 常用命令

```shell
uv sync                       # 安装依赖（含 dev 组）
uv run bb-sync --help         # 从源码运行 CLI
uv run pytest                 # 单元 + CLI 端到端，默认全离线
uv run ruff check .           # 静态检查；格式化检查用 ruff format --check .
uv run pyright                # 类型检查
```

改动提交前 `pytest` / `ruff check` / `ruff format --check` / `pyright` 必须全绿；
纯文档改动至少自查命令示例。测试与检查完全离线，只有真实 `run` / `doctor` 才需要浏览器和凭据。

## 文档地图

| 想知道 | 看 |
| --- | --- |
| 目录结构、模块职责、五条红线的细节与理由 | [docs/architecture.md](docs/architecture.md) |
| 测试分层、`conftest` 隔离、CI、真实站点手工验证 | [docs/testing.md](docs/testing.md) |
| 代码风格、提交信息、版本与发布 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 配置项与 `--json` 输出结构 | [docs/config.md](docs/config.md)、[docs/scripting.md](docs/scripting.md) |
| 安装与用户侧用法 | [README.md](README.md) |
