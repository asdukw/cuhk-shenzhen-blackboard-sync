# due-item-reconciliation Specification

## Purpose
把 Blackboard To Do 模块与公告两个来源的待办对账成一份清单：日期与类型取 To Do，来源之间的叫法分歧保留并显式呈现给用户，而不是静默丢弃其中一方。

## Requirements

### Requirement: 同一事件的公告条目作为别名保留

当 To Do 条目与公告条目属于同一课程、同一天且指向同一件事时，合并结果 SHALL 保留 To Do 条目的日期与类型，并 SHALL 记录公告条目的标题作为别名。

#### Scenario: 编号冲突时保留公告标题

- **WHEN** To Do 条目为 `Assignment 5`、日期 `2026-11-13`，公告条目为 `Homework assignment 4`、同日
- **THEN** 合并结果为一条待办，日期 `2026-11-13`，标题 `Assignment 5`，别名包含 `Homework assignment 4`

#### Scenario: 没有对应 To Do 时公告条目直接补入

- **WHEN** 公告推断出 `2026-11-15` 的作业截止，而 To Do 模块没有当天条目
- **THEN** 清单中出现一条独立待办，日期 `2026-11-15`，无别名

### Requirement: 仅在实质分歧时标注

系统 SHALL 把待办标题归一为「编号 + 主题词集合」后比较，只在编号不同、或双方编号相同但主题矛盾时标记分歧；纯措辞差异 SHALL NOT 标记。

#### Scenario: 措辞差异不标记

- **WHEN** To Do 条目为 `HW4`，公告条目为 `Homework assignment 4`，同日
- **THEN** 合并结果不产生别名标注

#### Scenario: 编号不同标记分歧

- **WHEN** To Do 条目为 `Assignment 5`，公告条目为 `Homework assignment 4`，同日
- **THEN** 合并结果带有一个分歧标记

### Requirement: due.md 渲染显式标注来源分歧

`due.md` 中带别名的条目 SHALL 在标题后追加 `（公告称 <别名>）`，且文件头部 SHALL 说明该括号的含义。

#### Scenario: 冲突条目渲染

- **WHEN** 待办标题为 `Assignment 5`，别名为 `Homework assignment 4`，日期 `2026-11-13`
- **THEN** `due.md` 该行包含 `Assignment 5（公告称 Homework assignment 4）`

### Requirement: 别名不影响勾选状态

完成状态的签名 SHALL 只由「日期 + 课程 + 基础标题」构成，别名出现、消失或变化 SHALL NOT 改变条目的完成状态。

#### Scenario: 公告措辞变化后已完成仍为已完成

- **WHEN** 上一版 `due.md` 中 `Assignment 5（公告称 Homework assignment 4）` 已标记为 `[x]`，本次同步别名消失
- **THEN** 新生成的行仍为 `[x]`

### Requirement: 来源分歧在运行时可观测

`bb-sync due` 与 `bb-sync run` SHALL 在运行汇总中报告本次发现的分歧条目数量；终端的待办明细行 SHOULD 在标题后标注公告里的另一种叫法；机器可读输出 SHALL 为每个条目提供别名列表。

#### Scenario: 终端汇总提示分歧

- **WHEN** 本次同步产生 1 条带别名的待办
- **THEN** 终端汇总包含「发现 1 处来源分歧」类提示

#### Scenario: 待办明细标注分歧

- **WHEN** `bb-sync run` 打印待办明细，其中一条标题为 `Assignment 5`、别名为 `Homework assignment 4`
- **THEN** 该行标题显示为 `Assignment 5（公告称 Homework assignment 4）`

#### Scenario: JSON 输出包含别名

- **WHEN** 以 `--json` 运行时存在带别名的待办
- **THEN** 该条目的 JSON 对象包含非空的 `aliases` 数组
