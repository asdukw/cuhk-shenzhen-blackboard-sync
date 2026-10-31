"""把课程 Due / To Do 数据渲染为按优先级排列的 ``due.md``。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Collection
from datetime import date, datetime, timedelta
from pathlib import Path

from bb_sync.blackboard.models import BASE, Course, DueItem

#: 分组顺序就是学生处理任务的优先级；「已过期事件」只是留档回看，所以排最后。
_BUCKET_ORDER = ("overdue", "today", "tomorrow", "next_7_days", "future", "unknown", "past_events")
_BUCKET_LABELS = {
    "overdue": "已逾期",
    "today": "今天",
    "tomorrow": "明天",
    "next_7_days": "未来 7 天",
    "future": "之后",
    "unknown": "日期未知",
    "past_events": "已过期事件",
}

#: 非普通任务的待办类型标签（来自公告）；顺序即汇总文案里的出现顺序。
#: ``assignment`` 是公告里推断出的作业 deadline，和 To Do 模块的普通任务区分开。
_KIND_LABELS = {"quiz": "测验", "exam": "考试", "assignment": "作业"}

#: 一次性事件：测验 / 考试日期过了只能回看。作业不同——逾期可能只是还没交，
#: 仍然要留在「已逾期」里提醒。
_EVENT_KINDS = frozenset({"quiz", "exam"})


def kind_label(kind: str) -> str:
    """返回待办类型的中文标签；普通任务返回空串。"""
    return _KIND_LABELS.get(kind, "")


def _is_past_event(item: DueItem, today: date) -> bool:
    """公告里的一次性事件（测验 / 考试）日期已过：它只能回看，没法再「做」。

    与 ``overdue`` 的区别：To Do 模块的逾期任务意味着「还没交」，仍然要行动；
    考完的测验 / 考试已是历史，混进待办里只会淹没真正要做的事。
    """
    return item.kind in _EVENT_KINDS and item.due_date is not None and item.due_date < today


def _bucket(item: DueItem, today: date) -> str:
    """按剩余时间归类；无法解析日期的任务放最后，避免被误判成低优先级。"""
    if item.due_date is None:
        return "unknown"
    if _is_past_event(item, today):
        return "past_events"
    if item.due_date < today:
        return "overdue"
    if item.due_date == today:
        return "today"
    if item.due_date == today + timedelta(days=1):
        return "tomorrow"
    if item.due_date <= today + timedelta(days=7):
        return "next_7_days"
    return "future"


def relative_due(item: DueItem, today: date) -> str:
    """生成截止日期旁的中文提示。"""
    if item.due_date is None:
        return item.due_text or "日期未知"
    delta = (item.due_date - today).days
    if delta < 0:
        # 逾期的作业 / To Do 是「还没交」，公告里的测验 / 考试是「已经考过」，措辞分开。
        return f"已过 {-delta} 天" if item.kind in _EVENT_KINDS else f"逾期 {-delta} 天"
    if delta == 0:
        return "今天"
    if delta == 1:
        return "明天"
    return f"还有 {delta} 天"


def _escape_markdown(text: str) -> str:
    """转义会改变 Markdown 结构的常见字符，同时保留可读标题。"""
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"([\\`*_\[\]])", r"\\\1", text)


def _sort_key(item: DueItem) -> tuple[date, str, str]:
    return (item.due_date or date.max, item.course_label, item.title)


def sort_due_items(items: list[DueItem]) -> list[DueItem]:
    """按截止日期、课程和任务名返回稳定排序的新列表。"""
    return sorted(items, key=_sort_key)


#: 标题分词：拉丁字母串与数字。中文标题走子串包含，见 :func:`_same_event`。
_TITLE_TOKEN_RE = re.compile(r"[a-z]+|\d+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

#: 不承载区分度的词，比较「是不是同一件事」时忽略。
_TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "be",
        "by",
        "deadline",
        "due",
        "for",
        "in",
        "is",
        "new",
        "of",
        "on",
        "release",
        "released",
        "reminder",
        "the",
        "to",
        "update",
        "updated",
    }
)


def _title_tokens(text: str) -> set[str]:
    """标题里可用于判重的实义词；纯数字不算（「HW 2」与「Quiz 2」不是同一件事）。"""
    return {
        token
        for token in _TITLE_TOKEN_RE.findall(text.casefold())
        if token not in _TITLE_STOPWORDS and not token.isdigit()
    }


def _compact(text: str) -> str:
    """去掉空格与标点，便于中文标题做包含判断。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _same_event(left: DueItem, right: DueItem) -> bool:
    """同一课程、同一天、标题指向同一件事 → 视为重复条目。"""
    same_course = bool(
        (left.course_id and left.course_id == right.course_id)
        or (left.course_code and left.course_code == right.course_code)
    )
    if not same_course or left.due_date is None or left.due_date != right.due_date:
        return False
    if _CJK_RE.search(left.title) or _CJK_RE.search(right.title):
        a, b = _compact(left.title), _compact(right.title)
        return bool(a and b and (a in b or b in a))
    return bool(_title_tokens(left.title) & _title_tokens(right.title))


def merge_due_items(todo_items: list[DueItem], announcement_items: list[DueItem]) -> list[DueItem]:
    """合并 To Do 模块与公告推断的待办，去掉同一件事的重复条目。

    To Do 模块是站点的原生数据，说明更准确（标题、逾期状态都来自 Blackboard），
    所以冲突时保留它；公告条目只在没有对应 To Do 时补进来。
    """
    merged = list(todo_items)
    merged.extend(
        item
        for item in announcement_items
        if not any(_same_event(item, existing) for existing in todo_items)
    )
    return merged


#: due.md 里复选框行的形状：``- [ ] …`` / ``- [x] …``。
_CHECKBOX_LINE_RE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<body>.*)$")

#: 行内的相对时间（如「还有 3 天」）；每天都会变，不参与勾选状态的匹配。
_RELATIVE_TIME_RE = re.compile(r"（[^）]*）")


def _item_signature(item: DueItem) -> str:
    """条目的稳定签名：日期 + 课程 + 标题，不含随日期变化的相对时间。

    用户在 due.md 里勾选后，下次运行靠它认回同一条待办并保留 ``[x]``。
    """
    due = item.due_date.isoformat() if item.due_date else "日期未知"
    course_url = f"{BASE}/webapps/blackboard/execute/launcher?type=Course&id={item.course_id}"
    label = kind_label(item.kind)
    badge = f"【{label}】" if label else ""
    return (
        f"**{due}** — [{_escape_markdown(item.course_label)}]({course_url}) — "
        f"{badge}{_escape_markdown(item.title)}"
    )


def _checked_signatures(markdown: str) -> set[str]:
    """从现有 due.md 读出已勾选条目的签名。"""
    done: set[str] = set()
    for line in markdown.splitlines():
        match = _CHECKBOX_LINE_RE.match(line)
        if not match or match.group("mark").lower() != "x":
            continue
        done.add(_RELATIVE_TIME_RE.sub("", match.group("body"), count=1))
    return done


def build_due_markdown(
    courses: list[Course],
    items: list[DueItem],
    *,
    failed: int = 0,
    today: date | None = None,
    generated_at: datetime | None = None,
    done: Collection[str] = (),
) -> str:
    """生成全局 ``due.md`` 文本。

    输出按「已逾期 → 今天 → 明天 → 未来 7 天 → 之后 → 日期未知 → 已过期事件」排序；
    同一分组内再按日期、课程和任务名稳定排序。

    ``done`` 是已勾选条目的签名集合（见 :func:`_item_signature`），命中的条目会渲染成
    ``- [x]``；调用方通常从上一版 due.md 里读出它，从而跨次同步保留完成状态。
    """
    day = today or date.today()
    generated = generated_at or datetime.now().astimezone()
    grouped: dict[str, list[DueItem]] = defaultdict(list)
    for item in items:
        grouped[_bucket(item, day)].append(item)
    for bucket_items in grouped.values():
        bucket_items.sort(key=_sort_key)

    # 过期事件单独成区，汇总行也不把它算进「待办」，否则「测验 2 项」里混着考完的。
    past_events = grouped.get("past_events", [])
    kind_counts = Counter(item.kind for item in items if not _is_past_event(item, day))
    # 只统计公告整理出的待办，按 _KIND_LABELS 的固定顺序列出（测验 → 考试）。
    announcement_parts = [
        f"{label} {kind_counts[kind]} 项"
        for kind, label in _KIND_LABELS.items()
        if kind_counts[kind]
    ]
    lines = [
        "# Blackboard 待办",
        "",
        f"> 更新时间：{generated.strftime('%Y-%m-%d %H:%M')}（本地时间）",
        f"> 已检查 {len(courses)} 门课程，发现 {len(items)} 项待办；按优先级和截止日期排列。",
    ]
    if announcement_parts:
        lines.append(f"> 其中公告里的{'、'.join(announcement_parts)}已一并作为待办列出。")
    if past_events:
        lines.append(f"> 另有 {len(past_events)} 项公告里的测验/考试日期已过，列在最后仅供回看。")
    if failed:
        lines.append(f"> 注意：{failed} 门课程抓取失败，结果可能不完整。")
    if items:
        lines.append("> 完成一项就在前面打勾（`- [ ]` → `- [x]`），下次同步会保留完成状态。")
    lines.append("")

    if not items:
        if failed:
            lines.extend(["本次未读取到待办，但由于部分课程抓取失败，结果可能不完整。", ""])
        else:
            lines.extend(["## Congratulations! 🎉", "", "当前没有待办事项。", ""])
        return "\n".join(lines)

    for bucket in _BUCKET_ORDER:
        bucket_items = grouped.get(bucket, [])
        if not bucket_items:
            continue
        lines.append(f"## {_BUCKET_LABELS[bucket]}（{len(bucket_items)}）")
        lines.append("")
        for item in bucket_items:
            due = item.due_date.isoformat() if item.due_date else "日期未知"
            course_url = (
                f"{BASE}/webapps/blackboard/execute/launcher?type=Course&id={item.course_id}"
            )
            label = kind_label(item.kind)
            badge = f"【{label}】" if label else ""
            box = "[x]" if _item_signature(item) in done else "[ ]"
            lines.append(
                f"- {box} **{due}**（{relative_due(item, day)}） — "
                f"[{_escape_markdown(item.course_label)}]({course_url}) — "
                f"{badge}{_escape_markdown(item.title)}"
            )
        lines.append("")
    return "\n".join(lines)


#: 头部「更新时间」行的前缀；比较内容是否变化时先把它去掉。
_UPDATE_LINE_PREFIX = "> 更新时间："


def _without_timestamp(text: str) -> str:
    """去掉头部的更新时间行，用于判断待办内容本身有没有变化。"""
    return "\n".join(line for line in text.splitlines() if not line.startswith(_UPDATE_LINE_PREFIX))


def write_due_markdown(
    path: Path,
    courses: list[Course],
    items: list[DueItem],
    *,
    failed: int = 0,
    today: date | None = None,
    generated_at: datetime | None = None,
) -> bool:
    """写入 ``due.md``；父目录不存在时自动创建。返回是否真的写了文件。

    内容（除更新时间外）和现有文件一样时保持原样：每次运行都重写会把「更新时间」
    一起改掉，即使待办一条没变，git 里也多出一份只有时间戳的 diff。
    """
    previous = ""
    if path.exists():
        try:
            previous = path.read_text(encoding="utf-8")
        except OSError:
            previous = ""
    content = build_due_markdown(
        courses,
        items,
        failed=failed,
        today=today,
        generated_at=generated_at,
        # 用户在上一版里勾选的条目，重新生成时保持 [x]
        done=_checked_signatures(previous),
    )
    if previous and _without_timestamp(previous) == _without_timestamp(content):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


__all__ = [
    "build_due_markdown",
    "kind_label",
    "merge_due_items",
    "relative_due",
    "sort_due_items",
    "write_due_markdown",
]
