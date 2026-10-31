"""同步服务：编排「登录 → 列课 → 抓内容 → 下载」的完整流程。

这一层是 CLI 与站点抓取之间的胶水，负责：
- 把 :class:`~bb_sync.core.config.Settings` 转成具体执行参数
- 驱动浏览器实例的生命周期（复用/启动分离的 Chrome/Edge、接入 CDP）
- 逐课程推进并把结果汇总成 :class:`SyncStats`

本层不直接 ``print``：全部通过注入的 :class:`~bb_sync.core.output.Console`。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from playwright.sync_api import sync_playwright

from bb_sync.blackboard import downloader, scraper
from bb_sync.blackboard.login import ensure_login
from bb_sync.blackboard.models import (
    Course,
    DueItem,
    DueStats,
    FileItem,
    SavedFile,
    SyncStats,
)
from bb_sync.browser import launcher
from bb_sync.core import due
from bb_sync.core.config import Settings
from bb_sync.core.errors import ConfigError, NetworkError, NotFoundError
from bb_sync.core.output import (
    STYLE_ACCENT,
    STYLE_BADGE,
    STYLE_ERROR,
    STYLE_HEADING,
    STYLE_MUTED,
    STYLE_SUCCESS,
    STYLE_TEXT,
    STYLE_WARN,
    Console,
)


@dataclass
class SyncOptions:
    """一次同步的运行时选项（已完成配置分层合并）。"""

    settings: Settings
    config_path: Path
    root: Path
    console: Console
    headed: bool = False
    dry_run: bool = False
    courses: list[str] | None = None
    #: 跑完保留后台浏览器（默认跑完就关）
    keep_open: bool = False


@dataclass
class DueOptions:
    """``bb-sync due`` 的运行时选项。"""

    settings: Settings
    root: Path
    console: Console
    headed: bool = False
    courses: list[str] | None = None
    #: 跑完保留后台浏览器（默认跑完就关）
    keep_open: bool = False


@dataclass
class DueScan:
    """一次全课程待办扫描的结果与失败统计。"""

    items: list[DueItem] = field(default_factory=list)
    todo_failed: int = 0  # Due / To Do 模块抓取失败的课程数
    announcement_failed: int = 0  # 公告抓取失败的课程数
    both_failed: int = 0  # 两个来源都失败的课程数（该课程结果完全缺失）

    @property
    def incomplete(self) -> int:
        """至少一个来源失败的课程数，用于提示 due.md 可能不完整。"""
        return self.todo_failed + self.announcement_failed - self.both_failed


def plan_root(settings: Settings, config_path: Path, cli_root: str | None) -> Path:
    """计算下载根目录：CLI ``--root`` > 配置 ``root``。

    相对路径基准：CLI 传的相对路径以 CWD 为基准，配置里的相对路径以配置文件目录为基准。
    """
    if cli_root:
        raw = Path(cli_root).expanduser()
        return raw if raw.is_absolute() else (Path.cwd() / raw).resolve()
    return settings.resolve_root(config_path)


def _macos_volume_root(root: Path) -> Path | None:
    """返回根目录所属的 macOS ``/Volumes/<名称>``，不在该位置则返回 None。"""
    if sys.platform != "darwin":
        return None
    posix = PurePosixPath(str(root).replace("\\", "/"))
    if len(posix.parts) < 3 or posix.parts[:2] != ("/", "Volumes"):
        return None
    return Path(posix.parts[0]) / posix.parts[1] / posix.parts[2]


def _drive_available(root: Path) -> bool:
    """检查盘符或 macOS 外接卷的根位置当前是否存在。"""
    location = Path(root.anchor) if root.drive else _macos_volume_root(root)
    if location is None:
        return True
    try:
        return location.exists()
    except OSError:
        return False


def _drive_label(root: Path) -> str:
    """磁盘不可用时，用于错误信息的盘符或挂载点。"""
    if root.drive:
        return root.drive
    volume = _macos_volume_root(root)
    return str(volume) if volume is not None else str(root)


def ensure_root_directory(root: Path) -> bool:
    """确保下载根目录可用，返回调用前该目录是否尚不存在。"""
    first_run = not root.exists()
    if not _drive_available(root):
        raise ConfigError(
            f"下载根目录所在磁盘不可用：{_drive_label(root)}（当前配置：{root}）",
            "请确认该磁盘已连接/挂载，或用 --root <可用目录> 临时指定；"
            "也可运行 bb-sync config set root <可用目录> 永久修改",
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(
            f"无法创建下载根目录：{root}",
            f"{exc}；请检查路径权限，或运行 bb-sync config set root <可用目录> 修改配置",
        ) from exc
    return first_run


def folder_name(course: Course, explicit_dirs: dict[str, str]) -> str:
    """课程本地文件夹名：显式映射优先，否则自动生成。"""
    if course.code and course.code in explicit_dirs:
        return explicit_dirs[course.code]
    return scraper.make_slug(course)


def sync_course(
    page,
    course: Course,
    course_dir: Path,
    options: SyncOptions,
    stats: SyncStats,
    downloads: downloader.DownloadSession,
) -> None:
    """同步单门课程：公告 → 内容区 → 逐文件下载。"""
    console = options.console
    settings = options.settings
    keywords = settings.keywords

    console.line(
        ("=== ", STYLE_MUTED),
        (course.code or "?", f"{STYLE_ACCENT} {STYLE_HEADING}"),
        (" | ", STYLE_MUTED),
        (course.title, STYLE_HEADING),
        (" → ", STYLE_MUTED),
        (str(course_dir), STYLE_MUTED),
        (" ===", STYLE_MUTED),
    )
    if not options.dry_run:
        course_dir.mkdir(parents=True, exist_ok=True)

    if settings.announcements:
        scraper.scrape_announcements(page, course, course_dir, options.dry_run, console)

    all_items: list[FileItem] = []
    visited: set[str] = set()
    menu = scraper.collect_menu_links(page, course)
    areas = ", ".join(n for _, n in menu) or "(无)"
    console.line(("    内容区: ", STYLE_MUTED), (areas, STYLE_TEXT))
    for area_url, area_name in menu:
        all_items += scraper.find_files(
            page, area_url, area_name, 1, settings.max_depth, keywords, visited
        )

    # 去重（同一文件可能出现在多个位置）
    uniq: dict[str, FileItem] = {}
    for item in all_items:
        uniq.setdefault(item.url, item)
    console.line(
        ("    发现 ", STYLE_MUTED),
        (str(len(uniq)), STYLE_HEADING),
        (" 个文件", STYLE_MUTED),
    )

    index = downloader.build_index(course_dir)
    label = course.code or course.title
    for item in uniq.values():
        try:
            status, name = downloads.download_item(item, course_dir, options.dry_run, index)
        except Exception as exc:  # 单个文件失败不中断整门课
            stats.bump("failed")
            console.warn(f"    [{item.category}] 下载失败: {exc}")
            continue
        stats.bump(status)
        if status == "downloaded":
            _record_saved(stats, label, course_dir, item, name)
        _log_item(console, status, item.category, name)


def _record_saved(
    stats: SyncStats, course_label: str, course_dir: Path, item: FileItem, name: str
) -> None:
    """把本次新落盘的文件记入明细，供末尾汇总与 ``--json`` 使用。

    落盘位置直接复用 :func:`bb_sync.blackboard.downloader.category_dir`，
    与真实写入保持同一套目录规则（作业会落到 ``assignments/hwN/``）。
    """
    target = downloader.category_dir(course_dir, item) / name
    stats.files.append(
        SavedFile(
            course=course_label,
            category=item.category,
            name=downloader.relative_path(target, course_dir),
            path=str(target),
        )
    )


def _log_item(console: Console, status: str, category: str, name: str) -> None:
    """按状态打印单条下载结果（全部走 stderr）。

    状态用符号 + 颜色双重表达（``↓`` 绿 = 新下载、``=`` 淡 = 已存在、
    ``?`` 黄 = dry-run），丢掉颜色后依然一眼分得清。
    """
    badge = (f"[{category}] ", STYLE_MUTED)
    if status == "downloaded":
        console.line(("    ↓ ", STYLE_SUCCESS), badge, (name, STYLE_TEXT))
    elif status == "would-download":
        console.line(("    ? ", STYLE_WARN), badge, (f"{name} (dry-run)", STYLE_TEXT))
    elif status == "exists":
        console.line(("    = ", STYLE_MUTED), badge, (f"{name} (已存在，跳过)", STYLE_MUTED))
    elif status == "empty":
        console.warn(f"    [{category}] {name} 内容为空，跳过")


def _print_plan(console: Console, courses: list[Course], root: Path, dry_run: bool) -> None:
    """开始下载前，先打印「将要写入哪些目录」的计划，方便确认落点。

    每个课程目录都显示为**绝对路径**——相对路径容易让人误判落盘位置。
    """
    console.rule("同步计划")
    console.line(("根目录: ", STYLE_MUTED), (str(root), STYLE_TEXT))
    console.log("课程目录:", level="muted")
    for course in courses:
        label = course.code or course.title
        console.line(
            ("  ", STYLE_TEXT),
            (f"{label:<10}", STYLE_ACCENT),
            (" → ", STYLE_MUTED),
            (str(root / course.slug), STYLE_MUTED),
        )
    console.line(
        ("合计 ", STYLE_MUTED),
        (str(len(courses)), STYLE_HEADING),
        (" 门课程", STYLE_MUTED),
        ("（dry-run，不会写入）" if dry_run else "", STYLE_WARN),
    )
    console.log("")


def _scan_due_items(page, courses: list[Course], console: Console) -> DueScan:
    """逐课程抓取 Due / To Do 与公告里的课堂测验 / 考试，并统计失败情况。"""
    scan = DueScan()
    for course in courses:
        label = course.code or course.title
        todo_items: list[DueItem] = []
        announcement_items: list[DueItem] = []
        todo_ok = False
        announcement_ok = False
        try:
            todo_items = scraper.scrape_due_items(page, course, console)
            todo_ok = True
        except Exception as exc:  # 单门课失败不阻断其它课程
            scan.todo_failed += 1
            console.warn(f"[due] {label} To Do 抓取失败: {exc}")
        try:
            entries = scraper.scrape_announcement_entries(page, course)
            announcement_items = scraper.parse_announcement_due_items(entries, course)
            announcement_ok = True
        except Exception as exc:  # 公告失败不影响已读到的 To Do
            scan.announcement_failed += 1
            console.warn(f"[due] {label} 公告抓取失败: {exc}")
        if not todo_ok and not announcement_ok:
            scan.both_failed += 1
        scan.items.extend(todo_items)
        scan.items.extend(announcement_items)
        parts = []
        if todo_ok:
            parts.append(f"待办 x{len(todo_items)}")
        if announcement_items:
            parts.append(f"公告测验/考试 x{len(announcement_items)}")
        console.line(
            ("    ", STYLE_TEXT),
            (label, STYLE_ACCENT),
            (": ", STYLE_MUTED),
            ("，".join(parts) if parts else "未读取到内容", STYLE_TEXT),
        )
    scan.items = due.sort_due_items(scan.items)
    return scan


def run_sync(options: SyncOptions) -> SyncStats:
    """执行一次完整同步。"""
    console = options.console
    settings = options.settings

    first_run = ensure_root_directory(options.root)
    if first_run:
        console.log(f"[info] 首次运行：课程文件将下载到 {options.root}")
        console.log("       （永久修改：bb-sync config set root <目录>；临时指定：--root）")

    include = options.courses if options.courses else settings.include
    explicit_dirs = settings.course_dirs
    stats = SyncStats()

    # ---- 浏览器：独立 profile，登录态跨次运行保留；跑完默认自动关闭 ----
    scope = launcher.browser_session(console, headed=options.headed, keep_open=options.keep_open)

    with scope as session, sync_playwright() as p:
        pw_browser, ctx, page = launcher.connect(p, session)
        console.debug(f"[browser] CDP 已接入 (UA: {ctx.browser.version if ctx.browser else '?'})")

        ensure_login(page, console, headed=options.headed)

        courses = scraper.scrape_courses(page, include, console)
        if not courses:
            raise NotFoundError(
                "未发现课程",
                "确认已登录且账号下有课程；也可用 bb-sync course list 先看看",
            )

        # 先算出每门课的落盘目录并整体打印，再逐门开始下载
        for course in courses:
            course.slug = folder_name(course, explicit_dirs)
        _print_plan(console, courses, options.root, options.dry_run)

        downloads = downloader.DownloadSession(page, ctx.request)
        for course in courses:
            stats.courses.append(course.code or course.title)
            sync_course(page, course, options.root / course.slug, options, stats, downloads)

        scan = _scan_due_items(page, courses, console)
        due_items = scan.items
        due_path = options.root / "due.md"
        if options.dry_run:
            if scan.both_failed == len(courses):
                message = "待办抓取全部失败"
            elif not due_items and not scan.incomplete:
                message = "Congratulations! 没有待办"
            else:
                message = f"待办 {len(due_items)} 项"
            console.line(
                ("[due] ", STYLE_ACCENT),
                (f"{message}（dry-run，未写入 due.md）", STYLE_MUTED),
            )
        elif scan.both_failed == len(courses):
            console.warn("[due] 所有课程待办抓取失败，保留现有 due.md")
        else:
            due.write_due_markdown(due_path, courses, due_items, failed=scan.incomplete)
            if due_items:
                console.line(
                    ("[due] ", STYLE_ACCENT), (f"{len(due_items)} 项 → due.md", STYLE_TEXT)
                )
            elif scan.incomplete:
                console.line(
                    ("[due] ", STYLE_ACCENT), ("未读取到待办（部分课程失败）→ due.md", STYLE_MUTED)
                )
            else:
                console.line(
                    ("[due] ", STYLE_ACCENT), ("Congratulations! 没有待办 → due.md", STYLE_SUCCESS)
                )

    # 浏览器由 browser_session 收尾：默认已关闭（--keep-open 则留在后台）
    _print_summary(console, stats, options.dry_run)
    _print_saved_files(console, stats.files)
    if scan.both_failed < len(courses):
        _print_due_details(console, due_items, scan.incomplete)
    return stats


def _print_summary(console: Console, stats: SyncStats, dry_run: bool) -> None:
    """汇总输出（stderr，人读）。"""
    console.rule("汇总")
    if dry_run:
        console.line(
            ("待下载: ", STYLE_TEXT),
            (str(stats.would_download), f"{STYLE_HEADING} {STYLE_WARN}"),
            (" 个文件（未实际下载）", STYLE_MUTED),
        )
    else:
        console.line(
            ("新下载 ", STYLE_TEXT),
            (str(stats.downloaded), f"{STYLE_HEADING} {STYLE_SUCCESS}"),
            (" 个，已存在跳过 ", STYLE_MUTED),
            (str(stats.exists), STYLE_HEADING),
            (" 个", STYLE_MUTED),
        )
    if stats.failed:
        console.line(
            ("! 失败 ", STYLE_WARN),
            (str(stats.failed), f"{STYLE_HEADING} {STYLE_WARN}"),
            (" 个", STYLE_WARN),
        )


def _print_saved_files(console: Console, files: list[SavedFile]) -> None:
    """在 ``run`` 最后逐行列出本次新下载的文件（stderr）。

    行格式 ``[new] 课程 | 相对路径``——路径本身以类别目录开头（``lectures/``、
    ``assignments/hw2/``），不必再单独标一次类别。逐文件日志负责「跑的时候看进度」，
    这里负责「跑完了看这一轮到底多了什么」。没有新文件时不打印标题，避免空区块。
    """
    if not files:
        return
    console.rule("新下载明细")
    for saved in files:
        console.line(
            ("[new] ", STYLE_SUCCESS),
            (saved.course, STYLE_ACCENT),
            (" | ", STYLE_MUTED),
            (saved.name, STYLE_TEXT),
        )


def _print_due_details(
    console: Console, items: list[DueItem], failed: int = 0, *, today: date | None = None
) -> None:
    """在 ``run`` 最后逐行打印待办明细（stderr）。

    行格式 ``[due] 日期（状态）| 课程 | 标题``；只有**已经过去**的条目才带状态，
    否则整屏都是「还有 N 天」，反而看不出哪条已经过期。
    """
    if not items:
        if failed:
            console.log("[due] 没有可显示的待办明细（部分课程抓取失败）")
        else:
            console.log("[due] Congratulations! 没有待办。")
        return
    day = today or date.today()
    console.rule("待办明细")
    for item in items:
        due_date = item.due_date.isoformat() if item.due_date else "日期未知"
        date_style = STYLE_TEXT if item.due_date is not None else STYLE_MUTED
        if item.due_date is not None and item.due_date < day:
            due_date = f"{due_date}（{due.relative_due(item, day)}）"
            date_style = STYLE_ERROR  # 逾期 / 已考过：唯一需要马上去看的
        elif item.due_date == day:
            date_style = STYLE_WARN
        label = due.kind_label(item.kind)
        badge = f"【{label}】" if label else ""
        console.line(
            ("[due] ", STYLE_ACCENT),
            (due_date, date_style),
            (" | ", STYLE_MUTED),
            (item.course_label, STYLE_ACCENT),
            (" | ", STYLE_MUTED),
            (badge, STYLE_BADGE),
            (item.title, STYLE_TEXT),
        )


def list_courses(options: SyncOptions) -> list[Course]:
    """仅列出课程（不下载），供 ``bb-sync course list`` 使用。"""
    console = options.console
    scope = launcher.browser_session(console, headed=options.headed, keep_open=options.keep_open)
    with scope as session, sync_playwright() as p:
        _pw_browser, _ctx, page = launcher.connect(p, session)
        ensure_login(page, console, headed=options.headed)
        include = options.courses if options.courses else "all"
        courses = scraper.scrape_courses(page, include, console)
        for course in courses:
            course.slug = folder_name(course, options.settings.course_dirs)
    return courses


def run_due(options: DueOptions) -> DueStats:
    """扫描课程主页的 To Do 模块，并生成全局 ``due.md``。"""
    console = options.console
    settings = options.settings
    first_run = ensure_root_directory(options.root)
    if first_run:
        console.log(f"[info] 待办文件将写入 {options.root / 'due.md'}")

    include = options.courses if options.courses else settings.include
    stats = DueStats(path=str(options.root / "due.md"))

    scope = launcher.browser_session(console, headed=options.headed, keep_open=options.keep_open)
    with scope as session, sync_playwright() as p:
        _pw_browser, _ctx, page = launcher.connect(p, session)
        ensure_login(page, console, headed=options.headed)

        courses = scraper.scrape_courses(page, include, console)
        if not courses:
            raise NotFoundError(
                "未发现课程",
                "确认已登录且账号下有课程；也可用 bb-sync course list 先看看",
            )

        stats.courses = [course.code or course.title for course in courses]
        scan = _scan_due_items(page, courses, console)
        stats.failed = scan.todo_failed
        stats.announcement_failed = scan.announcement_failed

        if scan.both_failed == len(courses):
            raise NetworkError(
                "所有课程的待办与公告都抓取失败",
                "检查网络连接与登录状态，或先用 bb-sync run --headed 刷新登录态",
            )

        stats.items = scan.items
        due.write_due_markdown(
            options.root / "due.md",
            courses,
            scan.items,
            failed=scan.incomplete,
        )

    console.rule("待办汇总")
    console.line(
        ("发现 ", STYLE_TEXT),
        (str(stats.total), f"{STYLE_HEADING} {STYLE_WARN if stats.total else STYLE_SUCCESS}"),
        (" 项待办，已写入 ", STYLE_TEXT),
        (stats.path, STYLE_MUTED),
    )
    problems = []
    if stats.failed:
        problems.append(f"{stats.failed} 门课程 To Do 抓取失败")
    if stats.announcement_failed:
        problems.append(f"{stats.announcement_failed} 门课程公告抓取失败")
    if problems:
        console.warn("；".join(problems) + "，due.md 可能不完整")
    return stats


__all__ = [
    "SyncOptions",
    "DueOptions",
    "ensure_root_directory",
    "folder_name",
    "list_courses",
    "plan_root",
    "run_sync",
    "run_due",
    "sync_course",
]
