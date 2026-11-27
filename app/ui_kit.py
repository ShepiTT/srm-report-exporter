"""界面组件：圆角卡片、按钮、开关标签、分段选择、输入框、状态标签和运行记录。

只用 tkinter。圆角用预先混合好背景色的角图片画出，在 Windows 上也有平滑边缘；
所有像素尺寸都经过 px() 按屏幕 DPI 缩放。
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import ttk

# ---------------------------------------------------------------- 主题
BG = "#f6f5f2"
PANEL = "#ffffff"
SUNKEN = "#f3f2ee"
BORDER = "#e4e2dc"
FIELD_BORDER = "#d6d3cb"
INK = "#1d1d1b"
INK2 = "#55534e"
MUTED = "#625e56"
BRAND = "#24694a"
BRAND_HOVER = "#1d5a3e"
BRAND_PRESSED = "#174b33"
BRAND_TINT = "#e6f0ea"
BRAND_LINE = "#b9d3c3"
WARN = "#a87814"
WARN_TINT = "#fbf2dc"
WARN_LINE = "#e3c77f"
CRIT = "#c2412f"
CRIT_TINT = "#fbe9e5"
HOVER = "#f4f3ef"
PRESSED = "#ebeae5"
DISABLED_BG = "#f1f0ec"
DISABLED_INK = "#a3a098"

SCALE = 1.0
FONTS: dict[str, tkfont.Font] = {}
_PREFERRED_FAMILIES = ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
                       "Source Han Sans SC", "WenQuanYi Micro Hei")


def enable_dpi_awareness() -> None:
    """让 Windows 按真实 DPI 绘制窗口，避免高分屏下模糊。必须在创建 Tk 之前调用。"""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def init(root: tk.Tk) -> None:
    """按屏幕 DPI 计算缩放比例，建立字体。"""
    global SCALE
    SCALE = max(1.0, min(3.0, root.winfo_fpixels("1i") / 96.0))
    families = set(tkfont.families(root))
    family = next((name for name in _PREFERRED_FAMILIES if name in families), "TkDefaultFont")
    for name, size, weight in (("title", 17, "bold"), ("h2", 12, "bold"), ("body", 10, "normal"),
                               ("strong", 10, "bold"), ("small", 9, "normal"), ("small_bold", 9, "bold")):
        FONTS[name] = tkfont.Font(root=root, family=family, size=size, weight=weight)
    root.option_add("*Font", FONTS["body"])
    style = ttk.Style(root)
    style.theme_use("clam")
    style.layout("Thin.Vertical.TScrollbar", [(
        "Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.configure("Thin.Vertical.TScrollbar", troughcolor=PANEL, background="#dcd9d2", bordercolor=PANEL,
                    lightcolor="#dcd9d2", darkcolor="#dcd9d2", arrowsize=px(8), gripcount=0, relief="flat")
    style.map("Thin.Vertical.TScrollbar", background=[("active", "#c8c5bd")])


def px(value: float) -> int:
    return int(round(value * SCALE))


def _parent_bg(widget) -> str:
    try:
        return widget.cget("background")
    except tk.TclError:
        return BG


# ---------------------------------------------------------------- 圆角
_corner_cache: dict[tuple, list] = {}


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _corners(radius: int, fill: str, outline: str, bg: str, border: int) -> list[tk.PhotoImage]:
    """四个角的图片（左上、右上、右下、左下），边缘按覆盖率和背景色混合。"""
    key = (radius, fill, outline, bg, border)
    if key in _corner_cache:
        return _corner_cache[key]
    f, o, b = _hex(fill), _hex(outline), _hex(bg)
    samples = 4
    rows = []
    for y in range(radius):
        row = []
        for x in range(radius):
            acc = [0.0, 0.0, 0.0]
            for sy in range(samples):
                for sx in range(samples):
                    dx = radius - (x + (sx + 0.5) / samples)
                    dy = radius - (y + (sy + 0.5) / samples)
                    distance = (dx * dx + dy * dy) ** 0.5
                    color = f if distance <= radius - border else o if distance <= radius else b
                    acc[0] += color[0]
                    acc[1] += color[1]
                    acc[2] += color[2]
            count = samples * samples
            row.append("#%02x%02x%02x" % (round(acc[0] / count), round(acc[1] / count), round(acc[2] / count)))
        rows.append(row)
    images = []
    for flip_x, flip_y in ((False, False), (True, False), (True, True), (False, True)):
        image = tk.PhotoImage(width=radius, height=radius)
        data = []
        for y in range(radius):
            source = rows[radius - 1 - y] if flip_y else rows[y]
            line = source[::-1] if flip_x else source
            data.append("{" + " ".join(line) + "}")
        image.put(" ".join(data), to=(0, 0))
        images.append(image)
    _corner_cache[key] = images
    return images


def round_rect(canvas: tk.Canvas, x0, y0, x1, y1, radius, *, fill, outline=None, bg=None, border=None, tag="shape"):
    """在画布上画一个带平滑圆角的矩形。x1、y1 不含。"""
    outline = outline or fill
    bg = bg or _parent_bg(canvas)
    border = border if border is not None else max(1, px(1))
    radius = max(1, min(int(radius), (x1 - x0) // 2, (y1 - y0) // 2))
    tl, tr, br, bl = _corners(radius, fill, outline, bg, border)
    canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1, fill=fill, width=0, tags=tag)
    canvas.create_rectangle(x0, y0 + radius, x1, y1 - radius, fill=fill, width=0, tags=tag)
    if outline != fill:
        canvas.create_rectangle(x0 + radius, y0, x1 - radius, y0 + border, fill=outline, width=0, tags=tag)
        canvas.create_rectangle(x0 + radius, y1 - border, x1 - radius, y1, fill=outline, width=0, tags=tag)
        canvas.create_rectangle(x0, y0 + radius, x0 + border, y1 - radius, fill=outline, width=0, tags=tag)
        canvas.create_rectangle(x1 - border, y0 + radius, x1, y1 - radius, fill=outline, width=0, tags=tag)
    canvas.create_image(x0, y0, image=tl, anchor="nw", tags=tag)
    canvas.create_image(x1 - radius, y0, image=tr, anchor="nw", tags=tag)
    canvas.create_image(x1 - radius, y1 - radius, image=br, anchor="nw", tags=tag)
    canvas.create_image(x0, y1 - radius, image=bl, anchor="nw", tags=tag)


def _states(spec) -> bool | None:
    """把 ttk 风格的 state(("disabled",)) 参数转成 True/False。"""
    if isinstance(spec, str):
        spec = (spec,)
    for item in spec or ():
        if item == "disabled":
            return True
        if item == "!disabled":
            return False
    return None


# ---------------------------------------------------------------- 卡片
class Card(tk.Canvas):
    """圆角白色卡片。内容放在 .body 里，用 grid 布局。"""

    def __init__(self, parent, *, title: str | None = None, note: str | None = None, pad=18, radius=10):
        super().__init__(parent, highlightthickness=0, bd=0, background=_parent_bg(parent))
        self.pad, self.radius = px(pad), px(radius)
        self.body = tk.Frame(self, background=PANEL)
        self.body.columnconfigure(0, weight=1)
        self._window = self.create_window(self.pad, self.pad, window=self.body, anchor="nw")
        self.header = None
        self.note_label = None
        if title:
            self.header = tk.Frame(self.body, background=PANEL)
            self.header.grid(row=0, column=0, sticky="ew")
            self.header.columnconfigure(1, weight=1)
            tk.Label(self.header, text=title, font=FONTS["h2"], fg=INK, bg=PANEL).grid(row=0, column=0, sticky="w")
        if note:
            self.note_label = tk.Label(self.body, text=note, font=FONTS["small"], fg=MUTED, bg=PANEL,
                                       justify="left", anchor="w", wraplength=px(260))
            self.note_label.grid(row=1, column=0, sticky="ew", pady=(px(2), 0))
        self.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", self._content)

    def header_right(self, widget):
        widget.grid(in_=self.header, row=0, column=2, sticky="e")
        return widget

    def _content(self, _event=None):
        height = self.body.winfo_reqheight() + 2 * self.pad
        if int(float(self.cget("height"))) != height:
            self.configure(height=height)

    def _resize(self, event):
        width, height = event.width, event.height
        self.itemconfigure(self._window, width=max(1, width - 2 * self.pad), height=max(1, height - 2 * self.pad))
        if self.note_label is not None:
            self.note_label.configure(wraplength=max(px(120), width - 2 * self.pad))
        self.delete("shape")
        round_rect(self, 0, 0, width, height, self.radius, fill=PANEL, outline=BORDER)
        self.tag_lower("shape")


# ---------------------------------------------------------------- 按钮
class Button(tk.Canvas):
    STYLES = {
        # kind: (fill, outline, ink, hover fill, pressed fill)
        "primary": (BRAND, BRAND, "#ffffff", BRAND_HOVER, BRAND_PRESSED),
        "secondary": (PANEL, FIELD_BORDER, INK, HOVER, PRESSED),
        "ghost": (None, None, BRAND, BRAND_TINT, BRAND_LINE),
    }

    def __init__(self, parent, text, command, *, kind="secondary", width=None, small=False):
        self.bg = _parent_bg(parent)
        self.kind, self.command, self.text = kind, command, text
        font = FONTS["strong"] if kind == "primary" else FONTS["small" if small else "body"]
        self.font = font
        height = px(30 if small else 34)
        natural = font.measure(text) + px(22 if small else 30)
        super().__init__(parent, width=width or natural, height=height, highlightthickness=0, bd=0,
                         background=self.bg, cursor="hand2", takefocus=1)
        self.disabled = False
        self.hovered = self.pressed = False
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Enter>", lambda _e: self._set(hovered=True))
        self.bind("<Leave>", lambda _e: self._set(hovered=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda _e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<KeyPress-space>", lambda _e: self.invoke())
        self.bind("<KeyPress-Return>", lambda _e: self.invoke())
        self.bind("<FocusIn>", lambda _e: self.draw())
        self.bind("<FocusOut>", lambda _e: self.draw())

    def _set(self, **flags):
        for key, value in flags.items():
            setattr(self, key, value)
        self.draw()

    def _release(self, event):
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        was_pressed = self.pressed
        self._set(pressed=False)
        if inside and was_pressed:
            self.invoke()

    def invoke(self):
        if not self.disabled and self.command:
            self.command()

    def state(self, spec=None):
        disabled = _states(spec)
        if disabled is not None and disabled != self.disabled:
            self.disabled = disabled
            self.configure(cursor="arrow" if disabled else "hand2")
            self.draw()
        return ("disabled",) if self.disabled else ()

    def set_text(self, text):
        self.text = text
        self.draw()

    def draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            width, height = int(self.cget("width")), int(self.cget("height"))
        fill, outline, ink, hover, pressed = self.STYLES[self.kind]
        if self.disabled:
            fill, outline, ink = ({"primary": (BRAND_TINT, BRAND_LINE, DISABLED_INK),
                                   "secondary": (DISABLED_BG, BORDER, DISABLED_INK),
                                   "ghost": (None, None, DISABLED_INK)})[self.kind]
        elif self.pressed:
            fill = pressed
        elif self.hovered:
            fill = hover
        if self.kind == "ghost" and fill:
            outline = fill
        if fill:
            round_rect(self, 0, 0, width, height, px(7), fill=fill, outline=outline, bg=self.bg)
        if self.focus_get() is self and not self.disabled:
            ring = BRAND if self.kind != "primary" else "#ffffff"
            self.create_rectangle(px(4), px(4), width - px(4), height - px(4), outline=ring, dash=(1, 2))
        self.create_text(width // 2, height // 2, text=self.text, fill=ink, font=self.font)


# ---------------------------------------------------------------- 勾选标签
class Check(tk.Canvas):
    """可勾选的圆角标签，绑定 BooleanVar。"""

    def __init__(self, parent, text, variable: tk.BooleanVar, *, command=None):
        self.bg = _parent_bg(parent)
        self.text, self.variable, self.command = text, variable, command
        self.font = FONTS["body"]
        width = self.font.measure(text) + px(46)
        super().__init__(parent, width=width, height=px(34), highlightthickness=0, bd=0,
                         background=self.bg, cursor="hand2", takefocus=1)
        self.disabled = self.hovered = False
        variable.trace_add("write", lambda *_: self.draw())
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))
        self.bind("<ButtonRelease-1>", lambda _e: self.toggle())
        self.bind("<KeyPress-space>", lambda _e: self.toggle())
        self.bind("<FocusIn>", lambda _e: self.draw())
        self.bind("<FocusOut>", lambda _e: self.draw())

    def _hover(self, value):
        self.hovered = value
        self.draw()

    def toggle(self):
        if self.disabled:
            return
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def state(self, spec=None):
        disabled = _states(spec)
        if disabled is not None and disabled != self.disabled:
            self.disabled = disabled
            self.configure(cursor="arrow" if disabled else "hand2")
            self.draw()
        return ("disabled",) if self.disabled else ()

    def draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            width, height = int(self.cget("width")), int(self.cget("height"))
        on = bool(self.variable.get())
        if self.disabled:
            fill, outline, ink, box = DISABLED_BG, BORDER, DISABLED_INK, DISABLED_INK
        elif on:
            fill, outline, ink, box = BRAND_TINT, BRAND_LINE, INK, BRAND
        else:
            fill, outline, ink, box = (HOVER if self.hovered else PANEL), FIELD_BORDER, INK2, FIELD_BORDER
        round_rect(self, 0, 0, width, height, px(7), fill=fill, outline=outline, bg=self.bg)
        size = px(16)
        left, top = px(12), (height - size) // 2
        if on:
            round_rect(self, left, top, left + size, top + size, px(4), fill=box, outline=box, bg=fill)
            self.create_line(left + px(4), top + px(8.5), left + px(7), top + px(11.5), left + px(12.5), top + px(5),
                             fill="#ffffff", width=max(2, px(2)), capstyle="round", joinstyle="round")
        else:
            round_rect(self, left, top, left + size, top + size, px(4), fill=PANEL, outline=box, bg=fill)
        if self.focus_get() is self:
            self.create_rectangle(px(3), px(3), width - px(3), height - px(3), outline=BRAND, dash=(1, 2))
        self.create_text(left + size + px(8), height // 2, text=self.text, fill=ink, font=self.font, anchor="w")


# ---------------------------------------------------------------- 分段选择
class Segmented(tk.Canvas):
    """一排互斥选项，绑定 StringVar。"""

    def __init__(self, parent, options, variable: tk.StringVar, *, command=None, min_width=0, small=False):
        self.bg = _parent_bg(parent)
        self.options, self.variable, self.command = list(options), variable, command
        self.font = FONTS["small" if small else "body"]
        self.bold = FONTS["small_bold" if small else "strong"]
        self.segment = max(max(self.bold.measure(option) for option in self.options) + px(24), px(min_width))
        height = px(30 if small else 34)
        super().__init__(parent, width=self.segment * len(self.options) + px(6), height=height,
                         highlightthickness=0, bd=0, background=self.bg, cursor="hand2")
        self.disabled = False
        self.hover_index = None
        variable.trace_add("write", lambda *_: self.draw())
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._hover(None))
        self.bind("<ButtonRelease-1>", self._click)

    def _index(self, x):
        width = self.winfo_width()
        segment = (width - px(6)) / len(self.options)
        return max(0, min(len(self.options) - 1, int((x - px(3)) // segment)))

    def _hover(self, index):
        if index != self.hover_index:
            self.hover_index = index
            self.draw()

    def _motion(self, event):
        self._hover(None if self.disabled else self._index(event.x))

    def _click(self, event):
        if self.disabled:
            return
        self.variable.set(self.options[self._index(event.x)])
        if self.command:
            self.command()

    def state(self, spec=None):
        disabled = _states(spec)
        if disabled is not None and disabled != self.disabled:
            self.disabled = disabled
            self.configure(cursor="arrow" if disabled else "hand2")
            self.draw()
        return ("disabled",) if self.disabled else ()

    def draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            width, height = int(self.cget("width")), int(self.cget("height"))
        track = DISABLED_BG if self.disabled else SUNKEN
        round_rect(self, 0, 0, width, height, px(8), fill=track, outline=BORDER, bg=self.bg)
        segment = (width - px(6)) / len(self.options)
        value = self.variable.get()
        for index, option in enumerate(self.options):
            x0 = px(3) + round(index * segment)
            x1 = px(3) + round((index + 1) * segment)
            selected = option == value
            if selected:
                fill = PANEL if not self.disabled else DISABLED_BG
                round_rect(self, x0, px(3), x1, height - px(3), px(6), fill=fill,
                           outline=FIELD_BORDER if not self.disabled else BORDER, bg=track)
            elif index == self.hover_index:
                round_rect(self, x0, px(3), x1, height - px(3), px(6), fill="#ebe9e3", outline="#ebe9e3", bg=track)
            ink = DISABLED_INK if self.disabled else (BRAND if selected else INK2)
            self.create_text((x0 + x1) // 2, height // 2, text=option, fill=ink,
                             font=self.bold if selected and not self.disabled else self.font)


# ---------------------------------------------------------------- 输入框
class Field(tk.Canvas):
    """圆角输入框，获得焦点时边框变成品牌色。"""

    def __init__(self, parent, variable: tk.StringVar, *, width=120, show="", placeholder=""):
        self.bg = _parent_bg(parent)
        super().__init__(parent, width=px(width), height=px(34), highlightthickness=0, bd=0, background=self.bg)
        self.entry = tk.Entry(self, textvariable=variable, show=show, relief="flat", bd=0, highlightthickness=0,
                              font=FONTS["body"], fg=INK, bg=PANEL, insertbackground=INK,
                              disabledbackground=DISABLED_BG, disabledforeground=DISABLED_INK,
                              selectbackground=BRAND_TINT, selectforeground=INK)
        self._window = self.create_window(px(10), px(17), window=self.entry, anchor="w")
        self.disabled = False
        self.focused = False
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<ButtonPress-1>", lambda _e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda _e: self._focus(True), add="+")
        self.entry.bind("<FocusOut>", lambda _e: self._focus(False), add="+")

    def _focus(self, value):
        self.focused = value
        self.draw()

    def focus_set(self):
        self.entry.focus_set()

    def state(self, spec=None):
        disabled = _states(spec)
        if disabled is not None and disabled != self.disabled:
            self.disabled = disabled
            self.entry.configure(state="disabled" if disabled else "normal")
            self.draw()
        return ("disabled",) if self.disabled else ()

    def draw(self):
        self.delete("shape")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            width, height = int(self.cget("width")), int(self.cget("height"))
        fill = DISABLED_BG if self.disabled else PANEL
        outline = BRAND if self.focused and not self.disabled else (BORDER if self.disabled else FIELD_BORDER)
        border = max(1, px(1.5)) if self.focused else max(1, px(1))
        round_rect(self, 0, 0, width, height, px(7), fill=fill, outline=outline, bg=self.bg, border=border)
        self.tag_lower("shape")
        self.coords(self._window, px(10), height // 2)
        self.itemconfigure(self._window, width=max(1, width - px(20)))


# ---------------------------------------------------------------- 状态标签
class Pill(tk.Canvas):
    """带圆点的状态标签；给了 command 时可点击。"""

    TONES = {
        "ok": (BRAND_TINT, BRAND_LINE, BRAND, INK),
        "warn": (WARN_TINT, WARN_LINE, WARN, INK),
        "crit": (CRIT_TINT, "#efb7ac", CRIT, INK),
        "idle": (SUNKEN, BORDER, MUTED, INK2),
    }

    def __init__(self, parent, text="", *, tone="idle", command=None, small=False):
        self.bg = _parent_bg(parent)
        self.text, self.tone, self.command = text, tone, command
        self.font = FONTS["small"]
        self.small = small
        super().__init__(parent, width=px(80), height=px(26 if small else 30), highlightthickness=0, bd=0,
                         background=self.bg, cursor="hand2" if command else "arrow")
        self.hovered = False
        self.bind("<Configure>", lambda _e: self.draw())
        if command:
            self.bind("<Enter>", lambda _e: self._hover(True))
            self.bind("<Leave>", lambda _e: self._hover(False))
            self.bind("<ButtonRelease-1>", lambda _e: self.command())
        self.set(text, tone)

    def _hover(self, value):
        self.hovered = value
        self.draw()

    def set(self, text, tone=None):
        self.text = text
        self.tone = tone or self.tone
        extra = px(14) if self.command else 0
        self.configure(width=self.font.measure(text) + px(34) + extra)
        self.draw()

    def draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            width, height = int(self.cget("width")), int(self.cget("height"))
        fill, line, dot, ink = self.TONES[self.tone]
        if self.hovered:
            line = dot
        round_rect(self, 0, 0, width, height, height // 2, fill=fill, outline=line, bg=self.bg)
        radius = px(3.5)
        cx, cy = px(14), height // 2
        self.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=dot, outline=dot)
        self.create_text(px(24), cy, text=self.text, fill=ink, font=self.font, anchor="w")
        if self.command:
            x = width - px(14)
            self.create_line(x - px(3), cy - px(3), x, cy, x - px(3), cy + px(3), fill=INK2, width=max(1, px(1.4)))


# ---------------------------------------------------------------- 忙碌条
class Busy(tk.Canvas):
    """细的不确定进度条。"""

    def __init__(self, parent):
        super().__init__(parent, height=px(3), highlightthickness=0, bd=0, background=_parent_bg(parent))
        self.running = False
        self.offset = 0.0

    def start(self):
        if not self.running:
            self.running = True
            self._tick()

    def stop(self):
        self.running = False
        self.delete("all")

    def _tick(self):
        if not self.running:
            return
        self.delete("all")
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        self.create_rectangle(0, 0, width, height, fill=BRAND_TINT, width=0)
        length = width * 0.28
        start = (self.offset % 1.3 - 0.3) * width
        self.create_rectangle(max(0, start), 0, min(width, start + length), height, fill=BRAND, width=0)
        self.offset += 0.012
        self.after(16, self._tick)


# ---------------------------------------------------------------- 运行记录
class LogView(tk.Frame):
    """带时间和状态圆点的运行记录。"""

    ERROR_WORDS = ("失败", "无法", "错误", "不能", "异常")
    WARN_WORDS = ("请", "未", "有 ", "跳过", "过期", "不可用", "留空", "缺")
    OK_WORDS = ("完成", "已保存", "成功", "已启用", "已停用", "已更新", "已生成", "已清除")

    def __init__(self, parent):
        super().__init__(parent, background=PANEL)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.text = tk.Text(self, height=6, wrap="word", state="disabled", relief="flat", bd=0, highlightthickness=0,
                            font=FONTS["body"], fg=INK, bg=PANEL, padx=px(2), pady=px(2), cursor="arrow",
                            spacing1=px(3), spacing3=px(3), selectbackground=BRAND_TINT, selectforeground=INK)
        self.text.grid(row=0, column=0, sticky="nsew")
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview, style="Thin.Vertical.TScrollbar")
        self.bar.grid(row=0, column=1, sticky="ns", padx=(px(6), 0))
        self.bar.grid_remove()
        self.text.configure(yscrollcommand=self._scrolled)
        indent = FONTS["small"].measure("00:00:00") + px(30)
        self.text.tag_configure("time", foreground=MUTED, font=FONTS["small"])
        self.text.tag_configure("line", lmargin2=indent)
        for tone, color in (("info", "#c9c6bd"), ("ok", BRAND), ("warn", WARN), ("error", CRIT)):
            self.text.tag_configure(tone, foreground=color)
        self.text.tag_configure("errortext", foreground=CRIT)

    def _scrolled(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.bar.grid_remove()
        else:
            self.bar.grid()
        self.bar.set(first, last)

    def tone(self, message: str) -> str:
        if any(word in message for word in self.ERROR_WORDS):
            return "error"
        if any(word in message for word in self.OK_WORDS):
            return "ok"
        if any(message.startswith(word) or f"，{word}" in message for word in self.WARN_WORDS):
            return "warn"
        return "info"

    def add(self, message, tone=None):
        message = str(message)
        tone = tone or self.tone(message)
        self.text.configure(state="normal")
        self.text.insert("end", datetime.now().strftime("%H:%M:%S"), ("time", "line"))
        self.text.insert("end", "   ●  ", (tone, "line"))
        self.text.insert("end", message + "\n", ("line", "errortext") if tone == "error" else ("line",))
        self.text.see("end")
        self.text.configure(state="disabled")


def label(parent, text="", *, font="body", fg=INK, textvariable=None, **options):
    widget = tk.Label(parent, text=text, textvariable=textvariable, font=FONTS[font], fg=fg,
                      bg=_parent_bg(parent), anchor="w", justify="left", **options)
    return widget


def frame(parent, **options):
    return tk.Frame(parent, background=_parent_bg(parent), **options)


def center_over(window: tk.Toplevel, parent: tk.Misc):
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 3)
    window.geometry(f"+{max(0, x)}+{max(0, y)}")
