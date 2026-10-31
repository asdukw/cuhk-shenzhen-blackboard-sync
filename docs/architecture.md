# bb-sync 架构与实现约定

本文面向修改 bb-sync 源码的人，讲清模块分工和五条**不能破**的实现约定（附理由）。
红线速记版在 [AGENTS.md](../AGENTS.md)；测试相关的约定见 [testing.md](testing.md)。

## 目录导航

| 路径 | 职责 |
| --- | --- |
| `src/bb_sync/cli.py` | 入口：Typer / Click 组装、全局选项、`LazyGroup` 延迟注册、统一异常兜底与退出码 |
| `src/bb_sync/context.py` | 全局 Context（`--json` / `--quiet` / `--verbose` / `--config`），惰性导入 |
| `src/bb_sync/paths.py` | `BB_SYNC_HOME`（默认 `~/.bb-sync`）与配置文件查找 |
| `src/bb_sync/creds.py` | keyring 凭据读写 |
| `src/bb_sync/commands/` | 子命令，一个命令一个模块：run / due / doctor / config / auth / course / browser |
| `src/bb_sync/core/` | config（分层加载）、config_store（行级 YAML 编辑）、service（同步编排）、due（待办生成）、doctor、output（Console 与语义色板）、errors（退出码）、help（help 样式）、update（版本检查） |
| `src/bb_sync/blackboard/` | login（ADFS SSO）、scraper（列表 / 内容抓取）、downloader、models |
| `src/bb_sync/browser/launcher.py` | 本机浏览器探测 / 分离启动 / CDP 接入、持久 profile |
| `tests/` | 全部离线：`test_units.py`（纯逻辑）、`test_cli_e2e.py`（进程内 CLI 契约）、`test_update_e2e.py`（更新提示通道） |
| `scripts/debug_*.py` | 手工调试脚本，会真实登录 / 访问站点；不属于测试，不要在 CI 或非必要时运行 |
| `docs/` | 用户与开发者文档：`config.md`、`scripting.md`、`architecture.md`（本文）、`testing.md` |

## 1. 输出通道：stdout 只放结果，stderr 只放诊断

- 所有输出走 `core.output.Console`，**禁止直接 `print`**。
- 诊断行需要强调时用 `console.line((文本, 样式), ...)` 并引用 `output.STYLE_*` 语义色板，
  不要在调用点新造颜色名。
- **不要打开 Rich markup**——诊断里到处是 `[new]`、`[作业]` 这类方括号文本，会被当成标签吃掉。
  着色在非 TTY、`NO_COLOR`、`--json` 下自动关闭。
- `--json` 时 stdout 有且仅有一个 JSON 文档；出错时 stdout 保持为空，错误走 stderr。
- 新增命令或字段时，同步更新 [scripting.md](scripting.md) 的 JSON 结构表与对应测试。

## 2. 退出码语义化

可预期错误一律抛 `BbSyncError` 子类（`core/errors.py`），由自带的 `exit_code` 决定进程退出码：

| 退出码 | 含义 | 异常类型 |
| --- | --- | --- |
| 0 | 成功 | — |
| 1 | 未分类 | `BbSyncError` |
| 2 | 用法错误 | `UsageError` |
| 3 | 登录 / 凭据 | `AuthError` |
| 4 | 配置 | `ConfigError` |
| 5 | 网络 | `NetworkError` |
| 6 | 目标不存在 | `NotFoundError` |
| 7 | 环境依赖 | `EnvironmentError_` |
| 8 | 中断 | — |

不要用裸 `sys.exit(1)` 或临时整数代替错误类型；未捕获的意外异常统一归为 1，并把堆栈打到 stderr。
用户可见的错误信息要带可操作的 hint（下一步该敲什么命令）。

## 3. 冷启动：入口与 Context 不做重量级顶层导入

`cli.py` / `context.py` / `commands/__init__.py` 顶层不得导入 playwright、pydantic、rich 等，
命令模块按需延迟导入（`cli.py` 的 `LazyGroup`），保证 `--version` / `--help` 快速返回。
`tests/test_cli_e2e.py` 有对应回归防线，不要绕过。

## 4. 配置：四层优先级 + 注释保留

- 优先级：CLI 参数 > `BB_SYNC_<KEY>` 环境变量 > config.yaml > 内置默认。
- 配置文件查找：CWD 优先，其次 `BB_SYNC_HOME/config.yaml`；完整配置项见 [config.md](config.md)。
- `config set/unset` 通过 `core/config_store.py` 做**行级编辑**，必须保留注释与未知键；
  不要改成整份 YAML 重写。
- 路径常量在 import 时快照，测试靠 monkeypatch 覆盖。

## 5. 浏览器后端：分离进程 + 自有 profile

浏览器就是用户机器上的 Chrome / Edge，由 `browser/launcher.py` 以
`--remote-debugging-port=0` 拉起，Playwright 只当 CDP 客户端。下面几条不能破：

- **跑完自动关**：默认命令结束（成功或失败）就关掉浏览器，不留后台进程。
  `browser_session` 的 finally 负责收尾，`--keep-open` 才保留实例供手动过 MFA
  或连续多次运行——不要在命令里留下没人管的浏览器。
- **分离**：进程独立于 CLI 存活（Windows 用 `CREATE_NO_WINDOW|CREATE_NEW_PROCESS_GROUP`，
  POSIX 用 `start_new_session`），命令跑到一半终端被关掉也不会把它带走，
  `--keep-open` 保留下来的实例下次运行直接复用。
- **端口自发现**：只认浏览器自己写下的 `DevToolsActivePort`，不要改成固定端口或自建注册表。
- **profile 隔离**：`--user-data-dir` 只能是 `BB_SYNC_HOME/.browser-profile/<chrome|edge>`，
  任何情况下不读不写用户日常使用的浏览器 profile。
- **关闭方式**：只能走 CDP 的 `Browser.close`（`stop_browser`），不要按 PID 杀进程——
  记录下来的 PID 可能已被系统回收。
- **无额外运行时**：不引入 Node / npm，也不要加回任何需要联网下载的浏览器依赖
  （国内网络下代价太高）。

## 常见坑

- 直接 kill 浏览器进程会留下失效的 `DevToolsActivePort`：下次启动虽会清掉，但 profile 可能
  没落盘，登录态白丢——关它只能走 `bb-sync browser stop`（CDP `Browser.close`）。
- Windows 与 macOS 都是主要目标平台，CI 三平台都跑；路径、后台进程和浏览器探测相关改动
  两个平台都要考虑。
- 浏览器后端不需要任何联网安装步骤；如果哪天又引入需要下载的组件，先想清楚国内网络下的代价。
- 下载目录默认 `~/courses`，课程资料有版权；禁止提交或外传 `courses/`、`.workbuddy/` 内容。
