# 变更提案：待办来源冲突显式标注

## Why

2026-11-04 的真实同步里有两条待办出问题，都不是随机故障，而是同一个设计假设的两面：

1. **来源冲突被静默吞掉**。Blackboard 的「Assignments and Exams」页把 HW4 的容器命名成
   `Assignment 5`（附件仍是 `DDA5002HW4_Fall26.pdf`），To Do 模块照抄该容器名；同一天、
   同一件事的公告却写着 `Homework assignment 4`。`merge_due_items()` 判定两条为「同一件事」
   后直接丢弃公告条目，于是 `due.md` 只剩下 `Assignment 5`，公告里正确的编号连痕迹都不留。
   To Do 被当作「原生数据更可信」，但原生数据本身可能被教务贴错标签。
2. **作业识别门槛过窄**。CSC5010 公告正文写 `Homework on Probabilistic Reasoning is
   assigned.` / `Deadline is Nov 15, 2026`，日期和截止词都能解析，但
   `_ASSIGNMENT_NAME_RE` 强制要求编号（`HW4`、`Assignment 2`），没有数字的作业名一律
   返回 `None`，整条静默丢弃。

两处漏报在 `due.md` 里都毫无提示，只能靠人肉比对公告才发现。随着学期推进公告量增加，
这类静默失败只会更频繁，所以现在改。

## What Changes

- **公告作业识别放宽**：允许「作业词 + 可选编号 + 可选主题」的名字形态
  （`Homework on Probabilistic Reasoning`、`Problem Set 2`、`Lab 3`）。守卫从「必须带数字」
  换成「公告标题或截止行相邻行含作业词」，仍拒绝没有作业语境的日期（例如
  `Week 4 Materials Uploaded` 里的 `deadline is 11:59 pm, Oct. 29th`）。
- **去重改为对账**：`_same_event()` 命中时不再丢弃公告条目，而是把公告标题作为**别名**
  保留在 To Do 条目上，日期与类型仍以 To Do 为准。
- **冲突判定只认实质分歧**：把两个标题归一成 `(编号, 主题词集合)`，只有编号不同、或双方
  编号相同但主题矛盾时才标注；`HW4` 与 `Homework assignment 4` 属于措辞差异，不标注。
- **`due.md` 显式标注分歧**：渲染为 `Assignment 5（公告称 Homework assignment 4）`，
  表头补一行说明括号含义。**BREAKING**：别名存在时 `due.md` 的行内容会变化。
- **勾选状态不受别名影响**：`_item_signature()` 继续只由「日期 + 课程 + 基础标题」构成，
  公告措辞变化不会让已勾选条目复位。
- **分歧可观测**：`bb-sync due` 结束汇总「发现 N 处来源分歧」，`--json` 的条目里带
  `aliases` 字段。**BREAKING**：`as_dict()` 新增字段。
- **真实案例进测试**：把这两条公告文本与对应的 To Do 条目做成回归夹具，防止同类问题
  再次静默复发。

## Capabilities

### New Capabilities

- `announcement-due-extraction`：从公告正文识别可预期的待办日期（考试 / 测验 / 作业截止），
  包括作业名识别规则、日期抽取窗口、过期保留期。
- `due-item-reconciliation`：To Do 与公告两个来源的合并语义、冲突别名、`due.md` 渲染格式、
  勾选状态签名与运行时可观测性。

### Modified Capabilities

本次是项目首次建立 specs（`openspec/specs/` 目前为空），没有既有能力需要修改。

## Impact

- 代码：`src/bb_sync/blackboard/scraper.py`（作业名规则）、`src/bb_sync/blackboard/models.py`
  （`DueItem` 增加别名）、`src/bb_sync/core/due.py`（对账与渲染）、
  `src/bb_sync/core/service.py`（汇总提示）、`src/bb_sync/commands/due.py`（帮助文本）。
- 输出：`due.md` 行格式、终端汇总、`--json` 结构。
- 测试：`tests/test_units.py` 现有公告解析与合并用例需扩充；新增两条真实公告夹具。
- 文档：`README.md` 的 `due.md` 示例、`CHANGELOG.md`。
