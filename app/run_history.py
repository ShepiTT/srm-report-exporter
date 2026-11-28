"""运行记录：每次导出或生成汇总结束后追加一行 JSON，界面的「运行记录」从这里读取。

手动导出和定时任务写同一个文件。完整的过程日志仍按天写在 logs 目录。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock


HISTORY_FILE = "history.jsonl"
KEEP = 200        # 文件超过 2×KEEP 行时，只保留最近 KEEP 条
MAX_LINES = 150   # 每条记录最多保留的过程行
_PROGRESS = re.compile(r"正在读取 SRM 第 \d+ 页|正在核对客诉详情，已核对 \d+/\d+ 条")
_lock = Lock()


def is_progress(text: str) -> bool:
    """翻页和核对详情的进度只在界面上滚动显示，不写进运行记录。"""
    return bool(_PROGRESS.match(text))


def tone_of(text: str) -> str | None:
    if text.startswith(("已保存", "已更新汇总报告", "已生成")):
        return "ok"
    if text.startswith("汇总报告没有更新"):
        return "warn"
    return None


def period_label(start: date, end: date, today: date | None = None) -> str:
    """「11月26日」或「11月20日 – 11月26日」；不是今年的日期带上年份。"""
    year = (today or date.today()).year

    def label(day: date) -> str:
        return ("" if day.year == year else f"{day.year}年") + f"{day.month}月{day.day}日"

    return label(start) if start == end else f"{label(start)} – {label(end)}"


class RunRecorder:
    """收集一次运行的过程，结束时写进运行记录。写记录失败不影响导出本身。"""

    def __init__(self, data_dir: Path, kind: str, title: str, sub: str = ""):
        self.path = Path(data_dir) / HISTORY_FILE
        self.record = {
            "id": uuid.uuid4().hex[:12], "kind": kind, "title": title, "sub": sub,
            "start": _now(), "end": None, "status": "running", "message": "", "lines": [],
        }

    def add(self, text: str, tone: str | None = None) -> list | None:
        """记下一行过程。进度类的消息不记，返回 None。"""
        text = str(text)
        if is_progress(text):
            return None
        tone = tone or tone_of(text)
        line = [datetime.now().strftime("%H:%M:%S"), text] + ([tone] if tone else [])
        lines = self.record["lines"]
        if len(lines) < MAX_LINES:
            lines.append(line)
        return line

    def finish(self, ok: bool, message: str) -> dict:
        self.record.update(end=_now(), status="ok" if ok else "fail", message=str(message))
        try:
            append_run(self.path.parent, self.record)
        except OSError:
            pass
        return self.record


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def append_run(data_dir: Path, record: dict) -> None:
    path = Path(data_dir) / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
        _prune(path)


def _prune(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError):
        return
    if len(lines) <= 2 * KEEP:
        return
    with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
        stream.writelines(lines[-KEEP:])
    try:
        staged.replace(path)
    except OSError:
        staged.unlink(missing_ok=True)


def history_signature(data_dir: Path):
    """文件有变化时值会变，用来发现定时任务新写的记录。"""
    try:
        stat = (Path(data_dir) / HISTORY_FILE).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def read_runs(data_dir: Path, limit: int = 60) -> list[dict]:
    """最近的运行记录，新的在前。坏行直接跳过。"""
    try:
        text = (Path(data_dir) / HISTORY_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    runs = []
    for raw in reversed(text.splitlines()):
        if len(runs) >= limit:
            break
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if (isinstance(item, dict) and isinstance(item.get("start"), str) and isinstance(item.get("title"), str)
                and item.get("status") in ("ok", "fail") and isinstance(item.get("lines"), list)):
            runs.append(item)
    return runs
