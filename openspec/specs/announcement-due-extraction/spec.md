# announcement-due-extraction Specification

## Purpose
从 Blackboard 公告正文中识别可预期的待办日期（考试、测验、作业截止），产出可合并进待办清单的条目，并在无法可靠识别时放弃而不是猜测。

## Requirements

### Requirement: 作业截止行支持无编号的作业名

系统 SHALL 把「作业词 + 可选编号 + 可选主题」形式的名称识别为作业名，包括
`Homework on Probabilistic Reasoning`、`Problem Set 2`、`Lab 3`；编号 SHALL 不再是无编号作业名被收录的前提。

#### Scenario: 无编号的主题式作业名被收录

- **WHEN** 公告标题为 `Homework on Probabilistic Reasoning`，正文含一行 `Deadline is Nov 15, 2026`
- **THEN** 该公告产生一条 `assignment` 待办，日期为 `2026-11-15`，标题取自公告标题

#### Scenario: 编号式作业名继续被收录

- **WHEN** 公告正文含 `- **HW4:** Due by **Oct. 31 at 11:59 PM**.`
- **THEN** 产生一条 `assignment` 待办，标题含 `HW4`，日期为 `2026-10-31`

#### Scenario: 截止行上一行可提供作业名

- **WHEN** 正文先有一行 `2. Coding Assignment 2 Release`，下一行为 `- Deadline: 23:59, November 2, 2026`
- **THEN** 产生一条 `assignment` 待办，标题含 `Assignment 2`，日期为 `2026-11-02`

### Requirement: 无作业语境的日期不产生待办

系统 SHALL 在公告标题与截止行相邻行都不含作业词时放弃该截止行，即使该行同时含日期和 `due`/`deadline` 措辞。

#### Scenario: 材料上传公告里的截止提醒被忽略

- **WHEN** 公告标题为 `Week 4 Materials Uploaded`，正文为 `Reminder: the deadline is 11:59 pm, Oct. 29th.`
- **THEN** 该公告不产生 `assignment` 待办

### Requirement: 公告待办受发布日期与保留期约束

系统 SHALL 丢弃日期早于公告发布日期、或早于当前日期超过 7 天的公告推断条目。

#### Scenario: 过期的测验不再进入待办

- **WHEN** 当前日期为 `2026-11-04`，公告提到 `2026-10-20` 的 quiz
- **THEN** 该 quiz 不进入待办

#### Scenario: 保留期内的逾期作业仍保留

- **WHEN** 当前日期为 `2026-11-04`，作业公告的截止日期为 `2026-10-31`
- **THEN** 该 `assignment` 待办仍被收录，供用户确认是否已交

### Requirement: 同一公告内的重复事项只收录一次

系统 SHALL 按「日期 + 标题」对同一公告解析出的条目去重。

#### Scenario: 正文两处提到同一截止

- **WHEN** 同一公告的正文和标题各出现一次 `Homework 4`、`Due Nov 2, 2026`
- **THEN** 只产生一条 `assignment` 待办
