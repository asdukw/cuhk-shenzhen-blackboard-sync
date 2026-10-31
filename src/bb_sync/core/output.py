"""输出通道：结果走 stdout，诊断走 stderr。

Unix CLI 的核心约定，本项目严格遵守：

======================  =========================  ====================
通道                    内容                       典型用法
======================  =========================  ====================
stdout                  命令的「数据结果」           ``bb-sync course list | jq '.[].code'``
stderr                  日志 / 进度 / 警告 / 错误    人读，或 ``2>/dev/null`` 丢弃
======================  =========================  ====================

:class:`Console` 是唯一的输出入口，两个职责：

1. **结果输出**（``result`` / ``table`` / ``emit``）—— 支持「人读」与「JSON」双模式。
   机器模式（``--json``）下，只有 ``emit`` 会往 stdout 吐**一个** JSON 文档，
   Rich 表格与人类可读文本全部被抑制，保证 stdout 是干净可解析的。
2. **诊断输出**（``log`` / ``line`` / ``warn`` / ``error`` / ``success`` / ``hint``）——
   一律走 stderr，且随 ``--quiet`` 降级。

**颜色**：诊断用下面 :data:`STYLE_*` 这套语义色板——16 色 ANSI 基本色，浅色 / 深色
主题都交给终端映射；颜色只做强调，状态同时用符号和文字表达，重定向或色觉差异下
依然分得清。着色由 Rich 按终端能力自动开关：非 TTY、设置 ``NO_COLOR`` 或 ``--json``
时都不会输出转义序列，stdout 永远保持干净。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from typing import Any

from rich.console import Console as RichConsole
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------- 语义色板
#
# 只用 16 色 ANSI 基本色，不写死 256 色 / 真彩色代码：浅色和深色主题都由终端
# 映射到合适的对比度，不会出现「白底上看不清的亮黄」。命令里只引用这些名字，
# 不在调用点随手挑颜色，保证整条输出看起来是一套设计。
STYLE_TEXT = ""  # 正文：空样式 = 终端默认前景色，不多发一条转义序列
STYLE_MUTED = "dim"  # 次要信息：路径、计数单位、分隔符
STYLE_ACCENT = "cyan"  # 标识符：课程代码、命令名
STYLE_SUCCESS = "green"  # 成功 / 新下载
STYLE_WARN = "yellow"  # 警告 / 待办
STYLE_ERROR = "bold red"  # 失败 / 逾期
STYLE_BADGE = "magenta"  # 类型徽标：测验 / 考试
STYLE_HEADING = "bold"  # 强调的正文、关键数字


class Console:
    """统一输出出口。

    :param json_mode: ``--json``：stdout 只输出机器可读 JSON。
    :param quiet: ``--quiet``：抑制 stderr 上的普通日志（错误与警告仍显示）。
    :param verbose: ``--verbose``：stderr 上追加调试信息。
    """

    def __init__(self, *, json_mode: bool = False, quiet: bool = False, verbose: bool = False):
        self.json_mode = json_mode
        self.quiet = quiet
        self.verbose = verbose
        # 结果通道：人读内容可能带颜色；JSON 模式绝不带颜色
        self._out = RichConsole(
            file=sys.stdout,
            soft_wrap=True,
            no_color=json_mode,
            highlight=False,
        )
        # 诊断通道：始终 stderr，颜色随 TTY 自适应
        self._err = RichConsole(file=sys.stderr, stderr=True, soft_wrap=True, highlight=False)

    # ------------------------------------------------------------ 诊断（stderr）
    def log(self, message: str = "", *, level: str = "info") -> None:
        """常规日志 → stderr。``--quiet`` 时不显示。

        正文用终端默认前景色；``level="muted"`` 才是淡色次要信息。
        """
        if self.quiet:
            return
        style = {"info": STYLE_TEXT, "muted": STYLE_MUTED, "step": STYLE_ACCENT}.get(
            level, STYLE_TEXT
        )
        self._err.print(message, style=style, markup=False, highlight=False)

    def line(self, *segments: tuple[str, str]) -> None:
        """按 ``(文本, 样式)`` 片段输出一行诊断到 stderr，``--quiet`` 时不显示。

        为什么不用 Rich 的 markup：诊断里到处都是 ``[new]``、``[作业]`` 这类方括号
        文本，全局打开标签解析会被误判成样式甚至报错。片段式拼接只给需要强调的部分
        上色，其余保持原样。
        """
        if self.quiet:
            return
        text = Text()
        for chunk, style in segments:
            text.append(chunk, style=style)
        self._err.print(text, markup=False, highlight=False)

    def step(self, message: str) -> None:
        """阶段性标题 → stderr，如 ``[scan] 获取课程列表 ...``。"""
        if self.quiet:
            return
        self._err.print(message, style="bold cyan", markup=False, highlight=False)

    def success(self, message: str) -> None:
        """成功提示 → stderr，带 ✓。"""
        if self.quiet:
            return
        self._err.print(f"✓ {message}", style="green", markup=False, highlight=False)

    def warn(self, message: str) -> None:
        """警告 → stderr，``--quiet`` 时仍显示。"""
        self._err.print(f"! {message}", style="yellow", markup=False, highlight=False)

    def error(self, message: str) -> None:
        """错误 → stderr，始终显示。"""
        self._err.print(f"✗ {message}", style="bold red", markup=False, highlight=False)

    def hint(self, message: str) -> None:
        """修复建议 → stderr，缩进显示在错误下方。"""
        self._err.print(f"  → {message}", style="dim", markup=False, highlight=False)

    def debug(self, message: str) -> None:
        """调试信息 → stderr，仅 ``--verbose`` 显示。"""
        if self.verbose and not self.quiet:
            self._err.print(f"[debug] {message}", style="dim", markup=False, highlight=False)

    def rule(self, title: str = "") -> None:
        """分隔线 → stderr：标题加粗，线条淡色（装饰性，不与内容抢注意力）。"""
        if not self.quiet:
            self._err.rule(Text(title, style=STYLE_HEADING) if title else "", style=STYLE_MUTED)

    # ------------------------------------------------------------ 结果（stdout）
    def emit(self, data: Any) -> None:
        """输出结构化结果到 stdout。

        人读模式（默认）只输出**标量**——因为 ``bb-sync run`` 的结果人类是通过
        stderr 上的汇总看的，stdout 应保持干净，避免干扰 ``$(...)`` 取值。
        容器类型（dict/list）在人读模式下**不输出**，仅在 ``--json`` 时输出，
        这样 ``--json`` 的语义就是「stdout 上有且仅有一个 JSON 文档」。
        """
        if self.json_mode:
            self._write_json(data)
            return
        if isinstance(data, (str, int, float, bool)):
            self._out.print(str(data), markup=False, highlight=False)

    def _write_json(self, data: Any) -> None:
        """stdout 上输出单个 JSON 文档，UTF-8 原样保留中文。"""
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    def table(
        self,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
        *,
        title: str = "",
        json_data: Any = None,
    ) -> None:
        """表格输出。

        ``--json`` 模式下抑制表格，改为输出 ``json_data``（缺省时把 rows 转成
        以 columns 为键的记录列表），保证脚本拿到的是稳定结构。
        """
        rows = list(rows)
        if self.json_mode:
            if json_data is None:
                json_data = [dict(zip(columns, r, strict=False)) for r in rows]
            self._write_json(json_data)
            return
        table = Table(title=title or None, header_style="bold", box=None, pad_edge=False)
        for col in columns:
            table.add_column(str(col))
        for row in rows:
            table.add_row(*[str(c) for c in row])
        # 表格本身是「人读结果」，所以走 stdout
        self._out.print(table if table.row_count else "", markup=False)

    def print_raw(self, text: str) -> None:
        """逐字输出到 stdout（不加样式），用于 ``config show`` 之类。"""
        self._out.print(text, markup=False, highlight=False, soft_wrap=True)


__all__ = [
    "STYLE_ACCENT",
    "STYLE_BADGE",
    "STYLE_ERROR",
    "STYLE_HEADING",
    "STYLE_MUTED",
    "STYLE_SUCCESS",
    "STYLE_TEXT",
    "STYLE_WARN",
    "Console",
]
