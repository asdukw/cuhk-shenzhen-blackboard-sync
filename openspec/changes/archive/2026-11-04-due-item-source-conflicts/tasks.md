# Tasks

## 1. 放宽公告作业名识别

- [x] 1.1 把 `_ASSIGNMENT_NAME_RE` 改为「作业词 + 可选编号 + 可选主题」，并把守卫改成「截止行、上一行或公告标题含作业词」，验证：`pytest tests/test_units.py -k announcement` 全绿，且新增的 `Homework on Probabilistic Reasoning` 用例解析出 `2026-11-15`
- [x] 1.2 补两条回归夹具（CSC5010 无编号作业公告、DDA5002 `Homework assignment 4` 公告），验证：两条公告分别得到 `assignment` 条目，日期为 `2026-11-15` 与 `2026-11-13`
- [x] 1.3 补反例测试确认守卫仍然有效（`Week 4 Materials Uploaded` 的截止提醒不产生待办；标题含 `homework` 但截止行日期指别的事也不收录），验证：新增用例通过且未放宽既有用例
- [x] 1.4 更新 `scraper.py` 中与作业名相关的注释与文档字符串，说明编号可选、语境守卫存在，验证：`ruff check src/bb_sync/blackboard/scraper.py` 通过

## 2. 合并语义改为对账

- [x] 2.1 给 `DueItem` 增加 `aliases: tuple[str, ...] = ()` 与 `as_dict()` 的 `aliases` 字段，验证：`pytest tests/test_units.py -k due_item` 与序列化用例通过
- [x] 2.2 实现标题归一化（编号抽取 + 主题词集合）与分歧判定，验证：`HW4` vs `Homework assignment 4` 判为无分歧、`Assignment 5` vs `Homework assignment 4` 判为分歧，单测覆盖 D2 表格四种情形
- [x] 2.3 改写 `merge_due_items()`：命中同一事件时用 `dataclasses.replace()` 把公告标题写入 To Do 条目的 `aliases`，验证：合并结果保留 To Do 的日期与类型，且别名非空
- [x] 2.4 补合并层测试（冲突保留别名、无对应 To Do 时独立补入、措辞差异不产生别名），验证：`pytest tests/test_units.py -k merge` 通过
- [x] 2.5 更新 CHANGELOG 中该能力的条目草稿（2.3.0 段落），验证：条目描述与 D1/D2 决策一致

## 3. 渲染与可观测性

- [x] 3.1 `build_due_markdown()` 在带别名条目后追加 `（公告称 <别名>）`，并转义 Markdown，验证：渲染用例断言行内容含 `Assignment 5（公告称 Homework assignment 4）`
- [x] 3.2 `due.md` 头部增加括号含义说明行，验证：`test_build_due_markdown_*` 用例断言该行存在
- [x] 3.3 确认 `_item_signature()` 仍只含基础标题，并补测试：上一版为 `[x]`、本次别名消失，新行为 `[x]`，验证：该用例通过
- [x] 3.4 `service` 汇总输出「发现 N 处来源分歧」，验证：带别名的扫描结果在汇总字符串里出现该提示，并有对应单测
- [x] 3.5 `--json` 输出验证：存在别名时条目含非空 `aliases` 数组，验证：JSON 快照或断言用例通过

## 4. 文档与版本

- [x] 4.1 更新 `README.md` 中 `due.md` 的示例与说明，加入别名括号样例，验证：示例与 `build_due_markdown()` 实际输出一致
- [x] 4.2 在 `CHANGELOG.md` 写入 2.3.0 段落，标注 `due.md` 行格式与 `as_dict()` 字段的 BREAKING 变化，验证：`pyproject.toml` 版本号同步为 2.3.0 且 CHANGELOG 段落存在

## 5. 集成验证

- [x] 5.1 更新 `openspec` 变更后跑 `pytest` 全量，验证：全部测试通过，无既有用例被静默放宽
- [x] 5.2 在课程仓库跑一次真实 `bb-sync due`，验证：`due.md` 中 DDA5002 的 11-13 条目出现 `（公告称 Homework assignment 4）`，且 CSC5010 出现 `2026-11-15` 的作业条目
- [x] 5.3 跑 `openspec validate due-item-source-conflicts --strict`，验证：无 error 与 warning

## Workflow follow-up

- 实现完成并经用户确认后，用 `openspec archive due-item-source-conflicts` 归档。
