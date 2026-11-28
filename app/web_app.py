"""新版主窗口：用 WebView2 显示 web/index.html，把界面上的操作接到导出、汇总和定时任务。

页面只通过 Bridge 的公开方法和 Python 通信（pywebview 会把公开方法暴露成 window.pywebview.api）。
导出等耗时操作在后台线程里运行，进度放进事件队列，由页面长轮询 poll() 取走，
所以后台线程不需要直接调用 evaluate_js。这台电脑用不了 WebView2 时，run() 返回 False，
main.py 会改用旧的 tkinter 界面。
"""

from __future__ import annotations

import functools
import os
import sys
import threading
import time
import uuid
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from app_auth import clear_session, forget_credentials, has_credentials, has_session, launch_login, save_credentials
from app_runtime import (
    APP_DATA, APP_NAME, PICKED_REPORT_NAME, Settings, export_message, load_settings, open_run_log,
    public_error, run_export, run_lock, run_summary, save_settings,
)
from run_history import RunRecorder, history_signature, is_progress, period_label, read_runs, tone_of
from site_profile import ProfileError, SiteProfile, load_site_profile, save_site_profile
from summary_report import REPORT_NAME, find_sources, read_overview
from win_schedule import get_schedule, remove_schedule, set_schedule


PAGE = Path(__file__).resolve().parent / "web" / "index.html"
WINDOW_SIZE = (1120, 720)
MIN_SIZE = (1024, 640)
BOOT_TIMEOUT = 15   # 页面这么久还没连上 Python，就关掉窗口改用旧界面
POLL_WAIT = 15
BUSY_TEXT = {"export": "导出", "summary": "生成汇总", "login": "浏览器登录", "settings": "保存设置"}
LOCALIZATION = {
    "global.quitConfirmation": "确定要退出吗？",
    "global.ok": "确定",
    "global.quit": "退出",
    "global.cancel": "取消",
    "global.saveFile": "保存文件",
    "windows.fileFilter.allFiles": "所有文件",
    "windows.fileFilter.otherFiles": "其他文件类型",
}


def _expected(error: Exception) -> bool:
    """站点、登录、导出、汇总自己抛出的错误都带着给用户看的说明；其他的是程序问题，要记下堆栈。"""
    return isinstance(error, (ValueError, RuntimeError, OSError))


def _log_failure(message: str, *args) -> None:
    logger = open_run_log()
    try:
        logger.exception(message, *args)
    finally:
        for handler in logger.handlers:
            handler.close()


def _log_note(message: str) -> None:
    logger = open_run_log()
    try:
        logger.info(message)
    finally:
        for handler in logger.handlers:
            handler.close()


def _guard(method):
    """页面调用的入口：出错时返回能给用户看的说明，不把异常抛给页面。"""

    @functools.wraps(method)
    def call(self, *args):
        try:
            result = method(self, *args)
        except Exception as error:
            if not _expected(error):
                _log_failure("界面操作 %s 出错。", method.__name__)
            return {"ok": False, "error": public_error(error)}
        return {"ok": True, **(result or {})}

    return call


def _day(value) -> date:
    try:
        day = date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("请选择有效的日期。") from None
    return day


def _reveal(path: Path) -> None:
    os.startfile(path)  # Windows 用默认程序打开文件，或在资源管理器里打开文件夹


class _Events:
    """后台线程把事件放进来，页面用 poll() 取。只保留最近的一段，太旧的页面会重新读状态。"""

    def __init__(self, keep: int = 300):
        self._keep = keep
        self._items: list[tuple[int, dict]] = []
        self._seq = 0
        self._closed = False
        self._cond = threading.Condition()

    @property
    def cursor(self) -> int:
        with self._cond:
            return self._seq

    def emit(self, event: dict) -> None:
        with self._cond:
            self._seq += 1
            self._items.append((self._seq, event))
            del self._items[:-self._keep]
            self._cond.notify_all()

    def wait(self, cursor: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._seq <= cursor and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            oldest = self._items[0][0] if self._items else self._seq + 1
            return {
                "cursor": self._seq,
                "events": [event for seq, event in self._items if seq > cursor],
                "reset": cursor < self._seq and cursor + 1 < oldest,
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()


class _Job:
    """一次后台操作。导出和汇总会写进运行记录和当天日志，保存设置之类的只在界面上显示。"""

    def __init__(self, events: _Events, kind: str, title: str, sub: str = "", *, record: bool = False):
        self.events = events
        self.kind, self.title, self.sub = kind, title, sub
        self.recorder = RunRecorder(APP_DATA, kind, title, sub) if record else None
        self.id = self.recorder.record["id"] if self.recorder else uuid.uuid4().hex[:12]
        self.lines = self.recorder.record["lines"] if self.recorder else []
        self.start = datetime.now().isoformat(timespec="seconds")
        self.stage = "正在准备…"
        self.logger = open_run_log() if record else None

    def report(self, text, tone: str | None = None) -> None:
        text = str(text)
        if self.logger:
            self.logger.info(text)
        self.stage = text
        if self.recorder:
            line = self.recorder.add(text, tone)
        elif is_progress(text):
            line = None
        else:
            tone = tone or tone_of(text)
            line = [datetime.now().strftime("%H:%M:%S"), text] + ([tone] if tone else [])
            self.lines.append(line)
        self.events.emit({"type": "progress", "id": self.id, "stage": text, "line": line})

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "sub": self.sub, "start": self.start,
                "stage": self.stage, "lines": list(self.lines), "status": "running"}


class Bridge:
    """暴露给页面的接口。只有公开方法会出现在页面里，内部状态都用下划线开头的名字。"""

    def __init__(self):
        self._window = None
        self._events = _Events()
        self._lock = threading.RLock()
        self._job: _Job | None = None
        self._booted = threading.Event()
        self._closed = threading.Event()
        self._failed = False
        self._watching = False
        self._overview_cache: dict[str, tuple] = {}
        self._schedule = {"loading": True}
        self._seen_history = history_signature(APP_DATA)
        try:
            self._settings = load_settings()
            self._notice = None
        except ValueError as error:
            self._settings = Settings()
            self._notice = str(error)

    # ------------------------------------------------------------ 窗口
    def _attach(self, window) -> None:
        self._window = window
        window.events.closing += self._on_closing
        window.events.closed += self._on_closed

    def _on_closing(self):
        job = self._job
        if job is not None:
            self._events.emit({"type": "toast", "tone": "warn",
                               "text": f"正在{BUSY_TEXT.get(job.kind, '处理')}，完成后再关闭窗口。"})
            return False
        self._events.close()
        self._closed.set()
        return True

    def _on_closed(self):
        self._events.close()
        self._closed.set()

    # ------------------------------------------------------------ 状态
    def _site_state(self) -> dict:
        try:
            profile = load_site_profile(APP_DATA)
        except ProfileError as error:
            missing = not (APP_DATA / "site.json").exists()
            return {"ready": False, "srm": "", "complaint": "", "templates": "", "error": None if missing else str(error)}
        return {"ready": True, "srm": profile.srm_origin, "complaint": profile.complaint_origin or "",
                "templates": ", ".join(profile.complaint_template_ids)}

    def _login_state(self) -> dict:
        state = {}
        for key, check in (("stored", has_credentials), ("session", has_session)):
            try:
                state[key] = bool(check(APP_DATA))
            except Exception:
                state[key] = False
        return state

    def _summary_state(self) -> dict:
        text = self._settings.output_dir.strip()
        folder = Path(text)
        if not text or not folder.is_absolute():
            return {"folder": False, "sources": 0, "report": False, "modified": None, "overview": None}
        report = folder / REPORT_NAME
        try:
            sources = len(find_sources(folder))
            stat = report.stat() if report.is_file() else None
        except OSError:
            sources, stat = 0, None
        overview = None
        if stat:
            key, version = str(report), (stat.st_mtime_ns, stat.st_size)
            cached = self._overview_cache.get(key)
            if cached and cached[0] == version:
                overview = cached[1]
            else:
                overview = read_overview(report)
                self._overview_cache[key] = (version, overview)
        return {"folder": True, "sources": sources, "report": stat is not None, "overview": overview,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="minutes") if stat else None}

    def _state(self) -> dict:
        settings = self._settings
        job = self._job
        return {
            "frozen": bool(getattr(sys, "frozen", False)),
            "prefs": {"output_dir": settings.output_dir, "deduct": settings.deduct,
                      "complaints": settings.complaints, "summary_auto": settings.summary_after_export},
            "plan": {"enabled": settings.schedule_enabled, "frequency": settings.frequency,
                     "time": settings.time_hhmm, "weekday": settings.weekday},
            "schedule": self._schedule,
            "site": self._site_state(),
            "login": self._login_state(),
            "summary": self._summary_state(),
            "runs": read_runs(APP_DATA),
            "job": job.public() if job else None,
        }

    def _query_schedule(self) -> dict:
        try:
            schedule = get_schedule()
        except Exception:
            return {"loading": False, "enabled": False, "error": "任务状态读取失败"}
        if not schedule or not schedule.enabled:
            return {"loading": False, "enabled": False}
        status = {"loading": False, "enabled": True, "frequency": schedule.frequency,
                  "time": schedule.time_hhmm, "weekday": schedule.weekday}
        if not self._settings.schedule_enabled:
            status["warning"] = "Windows 里的任务和设置不一致，请保存一次。"
        elif schedule.executable != Path(sys.executable):
            status["warning"] = "任务指向的 EXE 位置不对，请保存一次。"
        return status

    def _refresh_schedule(self) -> None:
        def query():
            self._schedule = self._query_schedule()
            self._events.emit({"type": "schedule", "schedule": self._schedule})

        self._schedule = {**self._schedule, "loading": True}
        self._events.emit({"type": "schedule", "schedule": self._schedule})
        threading.Thread(target=query, daemon=True).start()

    def _watch_history(self) -> None:
        """定时任务在另一个进程里运行，写了新记录就把最新状态推给页面。"""
        while not self._closed.wait(5):
            current = history_signature(APP_DATA)
            if current != self._seen_history and self._job is None:
                self._seen_history = current
                self._events.emit({"type": "state", "state": self._state()})

    # ------------------------------------------------------------ 后台任务
    def _start_job(self, kind, title, work, *, sub="", record=False, after=None) -> dict:
        with self._lock:
            if self._job is not None:
                raise ValueError("请等当前操作完成后再试。")
            job = self._job = _Job(self._events, kind, title, sub, record=record)
        self._events.emit({"type": "job", "job": job.public()})
        threading.Thread(target=self._run_job, args=(job, work, after), daemon=True).start()
        return {"job": job.public()}

    def _run_job(self, job: _Job, work, after) -> None:
        toast = None
        try:
            result = work(job) or {}
            ok, message, toast = True, result.get("message", "已完成。"), result.get("toast")
        except Exception as error:
            ok, message = False, public_error(error)
            if not _expected(error):
                _log_failure("%s失败。", job.title)
            elif job.logger:
                job.logger.error("%s失败。%s", job.title, message)
        finally:
            if job.logger:
                for handler in job.logger.handlers:
                    handler.close()
        if job.recorder:
            job.recorder.finish(ok, message)
            self._seen_history = history_signature(APP_DATA)
        with self._lock:
            self._job = None
        if after:
            after()
        self._events.emit({"type": "done", "id": job.id, "kind": job.kind, "ok": ok, "message": message,
                           "toast": toast, "state": self._state()})

    # ------------------------------------------------------------ 页面调用
    @_guard
    def boot(self):
        """页面加载完成后调用一次，拿到全部状态和事件游标。"""
        self._booted.set()
        with self._lock:
            start_watch, self._watching = not self._watching, True
        if start_watch:
            threading.Thread(target=self._watch_history, daemon=True).start()
            self._refresh_schedule()
        notice, self._notice = self._notice, None
        cursor = self._events.cursor   # 先取游标再读状态：中间到达的事件页面还会收到一次
        return {"state": self._state(), "cursor": cursor, "notice": notice}

    @_guard
    def state(self):
        cursor = self._events.cursor
        return {"state": self._state(), "cursor": cursor}

    def poll(self, cursor=0):
        """长轮询：有新事件立即返回，否则最多等 POLL_WAIT 秒。"""
        try:
            cursor = int(cursor)
        except (TypeError, ValueError):
            cursor = 0
        return self._events.wait(cursor, POLL_WAIT)

    @_guard
    def save_prefs(self, changes):
        """保存目录、报表勾选和「导出后自动更新」改了就存，定时任务也用这几项。"""
        if not isinstance(changes, dict):
            raise ValueError("设置格式有误。")
        updates = {}
        for key, field in (("deduct", "deduct"), ("complaints", "complaints"), ("summary_auto", "summary_after_export")):
            if key in changes:
                updates[field] = bool(changes[key])
        with self._lock:
            candidate = replace(self._settings, **updates)
            try:
                candidate.validate()
            except ValueError:
                return {"saved": False}   # 两种报表都没勾时先不存，界面会提示
            save_settings(candidate)
            self._settings = candidate
        return {"saved": True}

    @_guard
    def choose_folder(self):
        import webview

        current = self._settings.output_dir
        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                   directory=current if os.path.isdir(current) else "")
        if not selected:
            return {"path": None}
        path = selected[0] if isinstance(selected, (list, tuple)) else selected
        with self._lock:
            candidate = replace(self._settings, output_dir=str(Path(path)))
            candidate.validate()
            save_settings(candidate)
            self._settings = candidate
        return {"path": candidate.output_dir, "summary": self._summary_state()}

    @_guard
    def open_path(self, what):
        if what == "logs":
            folder = APP_DATA / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            _reveal(folder)
            return
        text = self._settings.output_dir.strip()
        if not text or not Path(text).is_absolute():
            raise ValueError("请先选择报表保存位置。")
        folder = Path(text)
        if what == "output":
            folder.mkdir(parents=True, exist_ok=True)
            _reveal(folder)
        elif what in ("report", "picked"):
            report = folder / (REPORT_NAME if what == "report" else PICKED_REPORT_NAME)
            if not report.is_file():
                raise ValueError("还没有生成汇总报告。")
            _reveal(report)
        else:
            raise ValueError("无法打开这个位置。")

    @_guard
    def start_export(self, options):
        if not isinstance(options, dict):
            raise ValueError("导出设置格式有误。")
        settings = replace(self._settings, deduct=bool(options.get("deduct")),
                           complaints=bool(options.get("complaints")))
        settings.validate()
        load_site_profile(APP_DATA)
        start, end = _day(options.get("start")), _day(options.get("end"))
        if start > end:
            raise ValueError("开始日期不能晚于结束日期。")

        def work(job: _Job):
            def saved(result):   # Excel 写好后先记下来，再更新汇总
                for warning in result.warnings:
                    job.report(warning, "warn")
                for path in result.files:
                    job.report(f"已保存 {path.name}")

            outcome = run_export(settings, start, end, job.report, saved=saved)
            return {"message": export_message(outcome),
                    "toast": {"text": f"导出完成，已生成 {len(outcome.files)} 份报表", "action": "打开文件夹",
                              "open": "output"}}

        return self._start_job("export", "手动导出", work, sub=period_label(start, end), record=True)

    @_guard
    def start_summary(self, pick=False):
        settings = self._settings
        files = None
        if pick:
            import webview

            folder = settings.output_dir if os.path.isdir(settings.output_dir) else ""
            selected = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=folder,
                                                       allow_multiple=True, file_types=("Excel 工作簿 (*.xlsx)",))
            if not selected:
                return {"cancelled": True}
            files = [str(path) for path in selected]

        def work(job: _Job):
            if files:
                job.report(f"将汇总所选的 {len(files)} 份文件，报告保存为 {PICKED_REPORT_NAME}")
            result = run_summary(settings, job.report, files=files)
            for warning in result.warnings:
                job.report(warning, "warn")
            job.report(f"已生成 {result.path.name}")
            try:
                _reveal(result.path)
                toast = {"text": "汇总已生成，已在浏览器中打开"}
            except OSError:
                toast = {"text": "汇总已生成", "action": "打开报告", "open": "picked" if files else "report"}
            return {"message": (f"{result.files} 份文件、{result.documents:,} 张单据，"
                                f"{result.first_day} 至 {result.last_day}"), "toast": toast}

        title, sub = ("汇总所选文件", f"{len(files)} 份") if files else ("生成汇总", "")
        return self._start_job("summary", title, work, sub=sub, record=True)

    @_guard
    def refresh_schedule(self):
        self._refresh_schedule()

    @_guard
    def save_schedule(self, plan):
        if not isinstance(plan, dict):
            raise ValueError("定时设置格式有误。")
        previous = self._settings
        if not plan.get("enabled"):
            settings = replace(previous, schedule_enabled=False)

            def disable(job: _Job):
                with run_lock():
                    remove_schedule()
                    save_settings(settings)
                self._settings = settings
                return {"message": "自动任务已停用。", "toast": {"text": "自动导出已停用"}}

            return self._start_job("settings", "停用自动导出", disable, after=self._refresh_schedule)

        try:
            weekday = int(plan.get("weekday", 0))
        except (TypeError, ValueError):
            raise ValueError("请选择有效的运行频率和星期。") from None
        settings = replace(previous, schedule_enabled=True, frequency=str(plan.get("frequency", "")),
                           time_hhmm=str(plan.get("time", "")).strip(), weekday=weekday)
        settings.validate()
        load_site_profile(APP_DATA)
        if not getattr(sys, "frozen", False):
            raise ValueError("请在打包的 EXE 中启用自动任务。")
        if not has_credentials(APP_DATA):
            raise ValueError("请先在登录设置保存 SRM 凭据，定时任务才能在会话过期后重新登录。")
        updating = bool(self._schedule.get("enabled"))

        def enable(job: _Job):
            with run_lock():
                save_settings(settings)
                try:
                    set_schedule(Path(sys.executable), settings.frequency, settings.time_hhmm, settings.weekday)
                except Exception:
                    save_settings(previous)
                    raise
            self._settings = settings
            text = "自动导出已更新" if updating else "自动导出已启用"
            return {"message": text + "。", "toast": {"text": text}}

        return self._start_job("settings", "保存自动导出", enable, after=self._refresh_schedule)

    @_guard
    def save_site(self, form):
        if not isinstance(form, dict):
            raise ValueError("站点设置格式有误。")
        templates = str(form.get("templates", "")).replace("，", ",")
        candidate = SiteProfile(str(form.get("srm", "")).strip(), str(form.get("complaint", "")).strip() or None,
                                tuple(item.strip() for item in templates.split(",") if item.strip())).normalized()
        try:
            current = load_site_profile(APP_DATA)
        except ProfileError:
            current = SiteProfile("")

        def store(job: _Job):
            with run_lock():
                save_site_profile(APP_DATA, candidate)
            changed = current.srm_origin != candidate.srm_origin
            message = "站点已保存。请在登录设置完成 SRM 登录。" if changed else "站点已保存。"
            return {"message": message, "toast": {"text": message.rstrip("。")}}

        return self._start_job("settings", "保存站点", store)

    @_guard
    def save_login(self, form):
        if not isinstance(form, dict):
            raise ValueError("登录信息格式有误。")
        account, sub, password = (str(form.get(key) or "") for key in ("account", "sub", "password"))
        if not account.strip() or not password:
            raise ValueError("请输入企业账号和密码。")
        load_site_profile(APP_DATA)

        def store(job: _Job):
            with run_lock():
                save_credentials(APP_DATA, account, sub, password)
            return {"message": "登录凭据已加密保存。", "toast": {"text": "登录凭据已加密保存"}}

        return self._start_job("settings", "保存登录凭据", store)

    @_guard
    def browser_login(self):
        load_site_profile(APP_DATA)

        def login(job: _Job):
            job.report("请在 Edge 窗口中完成登录")
            with run_lock():
                session = launch_login(APP_DATA, manual=True)
                session.close()
            return {"message": "浏览器登录成功，可以手动导出。", "toast": {"text": "浏览器登录成功，可以手动导出"}}

        return self._start_job("login", "浏览器登录", login)

    @_guard
    def clear_login(self):
        def remove(job: _Job):
            with run_lock():
                forget_credentials(APP_DATA)
                clear_session(APP_DATA)
            return {"message": "已清除登录凭据和本地会话。", "toast": {"text": "已清除登录凭据和本地会话"}}

        return self._start_job("settings", "清除登录", remove)


# ---------------------------------------------------------------- 启动

def webview2_ready() -> bool:
    """这台电脑能否用 WebView2 显示新界面：需要 pythonnet、.NET Framework 4.6.2 和 WebView2 运行时。"""
    try:
        from webview.platforms import winforms
    except Exception:
        return False
    return getattr(winforms, "renderer", None) == "edgechromium"


def _dark_mode() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError):
        return False


def _window_size() -> tuple[tuple[int, int], tuple[int, int]]:
    """按主显示器的可用区域（逻辑像素）收小窗口，免得 150% 缩放的笔记本上放不下。"""
    width, height = WINDOW_SIZE
    try:
        import ctypes
        from ctypes import wintypes

        area = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):  # SPI_GETWORKAREA
            try:
                scale = ctypes.windll.user32.GetDpiForSystem() / 96 or 1
            except AttributeError:
                scale = 1
            width = min(width, int((area.right - area.left) / scale) - 40)
            height = min(height, int((area.bottom - area.top) / scale) - 40)
    except (AttributeError, OSError, ValueError):
        pass
    width, height = max(width, 800), max(height, 520)
    return (width, height), (min(MIN_SIZE[0], width), min(MIN_SIZE[1], height))


def run() -> bool:
    """显示新版主窗口，关闭后返回 True。用不了 WebView2 或页面没能连上时返回 False，改用旧界面。"""
    if not webview2_ready():
        _log_note("这台电脑没有可用的 WebView2 运行时，使用旧界面。")
        return False
    import webview

    bridge = Bridge()
    (width, height), min_size = _window_size()
    window = webview.create_window(
        APP_NAME, html=PAGE.read_text(encoding="utf-8"), js_api=bridge, width=width, height=height,
        min_size=min_size, background_color="#0c0e11" if _dark_mode() else "#f3f4f6",
    )
    bridge._attach(window)

    def watchdog():
        if not bridge._booted.wait(BOOT_TIMEOUT) and not bridge._closed.is_set():
            bridge._failed = True
            bridge._closed.set()
            bridge._events.close()
            window.destroy()

    webview.start(watchdog, gui="edgechromium", localization=LOCALIZATION)
    if bridge._failed:
        _log_note(f"新界面 {BOOT_TIMEOUT} 秒内没有加载完成，已改用旧界面。")
    return not bridge._failed
