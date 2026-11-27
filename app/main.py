from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import replace
from datetime import date
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from app_auth import clear_session, forget_credentials, has_credentials, launch_login, save_credentials
from app_runtime import (
    APP_DATA, APP_NAME, Settings, completed_period, load_settings, open_run_log,
    public_error, run_export, run_lock, run_scheduled, save_settings,
)
from site_profile import ProfileError, SiteProfile, load_site_profile, save_site_profile
from win_schedule import get_schedule, remove_schedule, set_schedule


INK = "#182632"
SECONDARY = "#536874"
BACKGROUND = "#edf2f2"
PANEL = "#ffffff"
ACCENT = "#155b56"
ACTIVE = "#0d4945"
LINE = "#d9e4e3"
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
FREQUENCY = {"每天": "daily", "每周": "weekly"}
ASSETS = Path(__file__).resolve().parent


class ExportApp:
    def __init__(self, window: tk.Tk):
        self.window = window
        self.events = SimpleQueue()
        self.job = None
        self.controls = []
        try:
            self.settings = load_settings()
            setup_error = None
        except ValueError as error:
            self.settings = Settings()
            setup_error = str(error)

        window.title(APP_NAME)
        window.geometry("990x700")
        window.minsize(870, 640)
        window.configure(background=BACKGROUND)
        window.protocol("WM_DELETE_WINDOW", self.close)
        if (ASSETS / "report.ico").exists():
            window.iconbitmap(default=str(ASSETS / "report.ico"))
        self.style()

        start, end = completed_period("daily")
        self.output = tk.StringVar(value=self.settings.output_dir)
        self.deduct = tk.BooleanVar(value=self.settings.deduct)
        self.complaints = tk.BooleanVar(value=self.settings.complaints)
        self.start_date = tk.StringVar(value=start.isoformat())
        self.end_date = tk.StringVar(value=end.isoformat())
        self.frequency = tk.StringVar(value="每周" if self.settings.frequency == "weekly" else "每天")
        self.weekday = tk.StringVar(value=WEEKDAYS[self.settings.weekday])
        self.run_at = tk.StringVar(value=self.settings.time_hhmm)
        self.schedule_status = tk.StringVar(value="正在读取任务状态…")
        self.schedule_range = tk.StringVar()
        self.status = tk.StringVar(value="就绪")
        self.build()
        self.update_frequency()
        self.log("先设置站点和登录，再按日期导出，或保存自动任务。")
        if setup_error:
            self.log(setup_error)
        self.window.after(80, self.check_events)
        Thread(target=self.query_schedule, daemon=True).start()

    def style(self):
        style = ttk.Style(self.window)
        style.theme_use("clam")
        base_font = ("Microsoft YaHei UI", 10)
        style.configure(".", font=base_font, foreground=INK)
        style.configure("Root.TFrame", background=BACKGROUND)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 24, "bold"), background=BACKGROUND)
        style.configure("Subtitle.TLabel", foreground=SECONDARY, background=BACKGROUND)
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 13, "bold"), background=PANEL)
        style.configure("Panel.TLabel", background=PANEL)
        style.configure("Note.TLabel", foreground=SECONDARY, background=PANEL, font=("Microsoft YaHei UI", 9))
        style.configure("Panel.TCheckbutton", background=PANEL, padding=(0, 4))
        style.map("Panel.TCheckbutton", background=[("active", PANEL)])
        style.configure("TEntry", padding=(7, 6), fieldbackground=PANEL, bordercolor=LINE)
        style.configure("TCombobox", padding=(7, 5), fieldbackground=PANEL, bordercolor=LINE)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", INK)])
        style.configure("TButton", padding=(10, 6), background="#f3f7f6", bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, relief="flat")
        style.map("TButton", background=[("active", "#e3edeb"), ("disabled", "#f2f5f5")])
        style.configure("Primary.TButton", background=ACCENT, foreground=PANEL,
                        font=("Microsoft YaHei UI", 10, "bold"), bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Primary.TButton", background=[("disabled", "#87a6a2"), ("active", ACTIVE)],
                  foreground=[("disabled", PANEL)])

    def panel(self, parent, title):
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=(17, 12))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        return frame

    def button(self, parent, label, command, *, primary=False, locked=True):
        widget = ttk.Button(parent, text=label, command=command, style="Primary.TButton" if primary else "TButton")
        if locked:
            self.controls.append(widget)
        return widget

    def build(self):
        root = ttk.Frame(self.window, style="Root.TFrame", padding=(20, 15, 20, 15))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="扣款与客诉导出", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="从 SRM 按日期导出 Excel", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w")
        self.button(header, "站点设置", self.site_settings).grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 8))
        self.button(header, "登录设置", self.login_settings).grid(row=0, column=2, rowspan=2, sticky="e")

        settings = self.panel(root, "报表与保存位置")
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        kinds = ttk.Frame(settings, style="Panel.TFrame")
        kinds.grid(row=1, column=0, sticky="w", pady=(0, 5))
        for label, variable in (("扣款明细（包含客诉扣款）", self.deduct), ("客诉账单", self.complaints)):
            check = ttk.Checkbutton(kinds, text=label, variable=variable, style="Panel.TCheckbutton")
            check.pack(side="left", padx=(0, 17))
            self.controls.append(check)
        folder = ttk.Frame(settings, style="Panel.TFrame")
        folder.grid(row=2, column=0, sticky="ew")
        folder.columnconfigure(0, weight=1)
        input_folder = ttk.Entry(folder, textvariable=self.output)
        input_folder.grid(row=0, column=0, sticky="ew")
        self.controls.append(input_folder)
        self.button(folder, "选择目录", self.choose_folder).grid(row=0, column=1, padx=(8, 6))
        self.button(folder, "打开目录", self.open_output, locked=False).grid(row=0, column=2)

        sections = ttk.Frame(root, style="Root.TFrame")
        sections.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        sections.columnconfigure((0, 1), weight=1, uniform="section")
        self.build_manual(sections)
        self.build_schedule(sections)

        activity = self.panel(root, "运行记录")
        activity.grid(row=3, column=0, sticky="nsew")
        activity.rowconfigure(1, weight=1)
        self.button(activity, "打开日志目录", self.open_logs, locked=False).grid(row=0, column=0, sticky="e", pady=(0, 8))
        self.status_label = ttk.Label(activity, textvariable=self.status, style="Note.TLabel")
        self.status_label.grid(row=2, column=0, sticky="w", pady=(7, 0))
        self.progress = ttk.Progressbar(activity, mode="indeterminate", length=115)
        self.progress.grid(row=2, column=0, sticky="e", pady=(7, 0))
        self.progress.grid_remove()
        log_area = ttk.Frame(activity, style="Panel.TFrame")
        log_area.grid(row=1, column=0, sticky="nsew")
        log_area.columnconfigure(0, weight=1)
        log_area.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_area, height=3, wrap="word", state="disabled",
                                font=("Microsoft YaHei UI", 9), background="#f5f8f8",
                                foreground=INK, borderwidth=0, padx=9, pady=6)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_area, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def build_manual(self, parent):
        manual = self.panel(parent, "手动导出")
        manual.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        dates = ttk.Frame(manual, style="Panel.TFrame")
        dates.grid(row=1, column=0, sticky="ew")
        dates.columnconfigure((0, 1), weight=1)
        for index, (label, variable) in enumerate((("开始日期", self.start_date), ("结束日期", self.end_date))):
            padding = (0, 6) if index == 0 else (6, 0)
            ttk.Label(dates, text=label, style="Panel.TLabel").grid(row=0, column=index, sticky="w", padx=padding)
            entry = ttk.Entry(dates, textvariable=variable, width=13)
            entry.grid(row=1, column=index, sticky="ew", padx=padding, pady=(4, 6))
            self.controls.append(entry)
        ttk.Label(manual, text="日期格式 YYYY-MM-DD，包含起止当天", style="Note.TLabel").grid(row=2, column=0, sticky="w")
        actions = ttk.Frame(manual, style="Panel.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.button(actions, "昨天", lambda: self.set_period("daily")).pack(side="left", padx=(0, 5))
        self.button(actions, "近 7 天", lambda: self.set_period("weekly")).pack(side="left")
        self.button(actions, "开始导出", self.manual_run, primary=True).pack(side="right")

    def build_schedule(self, parent):
        schedule = self.panel(parent, "自动导出")
        schedule.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ttk.Label(schedule, textvariable=self.schedule_status, style="Note.TLabel").grid(row=0, column=0, sticky="e", pady=(0, 8))
        timing = ttk.Frame(schedule, style="Panel.TFrame")
        timing.grid(row=1, column=0, sticky="ew")
        timing.columnconfigure((0, 1, 2), weight=1)
        for index, label in enumerate(("频率", "星期", "时间")):
            ttk.Label(timing, text=label, style="Panel.TLabel").grid(row=0, column=index, sticky="w", padx=(0, 6))
        frequency = ttk.Combobox(timing, textvariable=self.frequency, values=tuple(FREQUENCY), state="readonly", width=6)
        frequency.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(4, 6))
        frequency.bind("<<ComboboxSelected>>", self.update_frequency)
        self.weekday_control = ttk.Combobox(timing, textvariable=self.weekday, values=WEEKDAYS, state="readonly", width=6)
        self.weekday_control.grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(4, 6))
        time_entry = ttk.Entry(timing, textvariable=self.run_at, width=6)
        time_entry.grid(row=1, column=2, sticky="ew", pady=(4, 6))
        self.controls.extend((frequency, time_entry))
        ttk.Label(schedule, textvariable=self.schedule_range, style="Note.TLabel").grid(row=2, column=0, sticky="w")
        actions = ttk.Frame(schedule, style="Panel.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.button(actions, "停用", self.disable_schedule).pack(side="left")
        self.button(actions, "保存并启用", self.enable_schedule, primary=True).pack(side="right")

    def update_frequency(self, _event=None):
        weekly = self.frequency.get() == "每周"
        self.weekday_control.state(("!disabled",) if weekly and self.job is None else ("disabled",))
        self.schedule_range.set("导出运行日前连续 7 天，需保持 Windows 登录" if weekly else "导出昨天的数据，需保持 Windows 登录")

    def set_period(self, frequency):
        start, end = completed_period(frequency)
        self.start_date.set(start.isoformat())
        self.end_date.set(end.isoformat())

    def choose_folder(self):
        selected = filedialog.askdirectory(parent=self.window, initialdir=self.output.get(), mustexist=True)
        if selected:
            self.output.set(selected)

    def reveal(self, path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except (OSError, ValueError) as error:
            messagebox.showerror(APP_NAME, public_error(error), parent=self.window)

    def open_output(self):
        folder = Path(self.output.get().strip())
        if folder.is_absolute():
            self.reveal(folder)
        else:
            messagebox.showwarning(APP_NAME, "请先选择报表保存位置。", parent=self.window)

    def open_logs(self):
        self.reveal(APP_DATA / "logs")

    def selected_reports(self):
        return replace(self.settings, output_dir=self.output.get().strip(),
                       deduct=self.deduct.get(), complaints=self.complaints.get())

    def manual_run(self):
        settings = self.selected_reports()
        try:
            settings.validate()
            load_site_profile(APP_DATA)
            date_texts = self.start_date.get().strip(), self.end_date.get().strip()
            start, end = (date.fromisoformat(value) for value in date_texts)
            if (start.isoformat(), end.isoformat()) != date_texts:
                raise ValueError
        except ValueError as error:
            description = str(error)
            if not description or "isoformat" in description:
                description = "请输入有效日期，格式为 YYYY-MM-DD。"
            messagebox.showwarning(APP_NAME, description, parent=self.window)
            return
        if start > end:
            messagebox.showwarning(APP_NAME, "开始日期不能晚于结束日期。", parent=self.window)
            return

        def run():
            logger = open_run_log()

            def report(line):
                logger.info(line)
                self.events.put(("log", line))

            try:
                result = run_export(settings, start, end, report)
                for warning in result.warnings:
                    report(warning)
                for path in result.files:
                    report(f"已保存 {path.name}")
                return f"导出完成，已生成 {len(result.files)} 份报表。"
            except Exception as error:
                logger.error("手动导出失败。%s", public_error(error))
                raise
            finally:
                for handler in logger.handlers:
                    handler.close()

        self.start_job("正在导出", run)

    def query_schedule(self):
        try:
            schedule = get_schedule()
        except Exception:
            self.events.put(("schedule", "任务状态读取失败"))
            return
        if schedule and schedule.enabled and not self.settings.schedule_enabled:
            status = "需重新保存设置"
        elif schedule and schedule.enabled and schedule.executable != Path(sys.executable):
            status = "需更新 EXE 路径"
        elif schedule and schedule.enabled:
            status = (f"已启用 · 每天 {schedule.time_hhmm}" if schedule.frequency == "daily"
                      else f"已启用 · {WEEKDAYS[schedule.weekday]} {schedule.time_hhmm}")
        else:
            status = "未启用"
        self.events.put(("schedule", status))

    def enable_schedule(self):
        settings = replace(self.selected_reports(), schedule_enabled=True,
                           frequency=FREQUENCY[self.frequency.get()],
                           time_hhmm=self.run_at.get().strip(), weekday=WEEKDAYS.index(self.weekday.get()))
        try:
            settings.validate()
            load_site_profile(APP_DATA)
            if not getattr(sys, "frozen", False):
                raise ValueError("请在打包的 EXE 中启用自动任务。")
            if not has_credentials(APP_DATA):
                raise ValueError("请先在登录设置保存 SRM 凭据，定时任务才能在会话过期后重新登录。")
        except Exception as error:
            messagebox.showwarning(APP_NAME, public_error(error), parent=self.window)
            return

        def enable():
            with run_lock():
                save_settings(settings)
                try:
                    set_schedule(Path(sys.executable), settings.frequency, settings.time_hhmm, settings.weekday)
                except Exception:
                    save_settings(self.settings)
                    raise
            return "自动任务已启用。"

        self.start_job("正在保存自动任务", enable, lambda: self.refresh_schedule(settings))

    def disable_schedule(self):
        settings = replace(self.settings, schedule_enabled=False)

        def disable():
            with run_lock():
                remove_schedule()
                save_settings(settings)
            return "自动任务已停用。"

        self.start_job("正在停用自动任务", disable, lambda: self.refresh_schedule(settings))

    def refresh_schedule(self, settings):
        self.settings = settings
        self.schedule_status.set("正在读取任务状态…")
        Thread(target=self.query_schedule, daemon=True).start()

    def site_settings(self):
        try:
            current = load_site_profile(APP_DATA)
        except ProfileError:
            current = SiteProfile("")

        dialog = tk.Toplevel(self.window)
        dialog.title("站点设置")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        dialog.grab_set()
        form = ttk.Frame(dialog, style="Panel.TFrame", padding=18)
        form.pack(fill="both", expand=True)
        srm = tk.StringVar(value=current.srm_origin)
        complaints = tk.StringVar(value=current.complaint_origin or "")
        templates = tk.StringVar(value=", ".join(current.complaint_template_ids))
        ttk.Label(form, text="业务站点", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(form, text="使用公司提供的 HTTPS 站点地址。站点设置保存在本机。",
                  style="Note.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        fields = (("SRM 地址", srm), ("客诉地址（可选）", complaints), ("客诉模板编号（可选）", templates))
        for row, (label, variable) in enumerate(fields, start=2):
            ttk.Label(form, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=(0, 7))
            entry = ttk.Entry(form, textvariable=variable, width=39)
            entry.grid(row=row, column=1, sticky="ew", pady=(0, 7))
            if row == 2:
                entry.focus_set()

        def save():
            candidate = SiteProfile(srm.get().strip(), complaints.get().strip() or None,
                                    tuple(item.strip() for item in templates.get().replace("，", ",").split(",") if item.strip()))
            try:
                candidate = candidate.normalized()
            except ProfileError as error:
                messagebox.showwarning(APP_NAME, str(error), parent=dialog)
                return
            dialog.destroy()

            def store():
                with run_lock():
                    save_site_profile(APP_DATA, candidate)
                return ("站点已保存。请在登录设置完成 SRM 登录。" if current.srm_origin != candidate.srm_origin
                        else "站点已保存。")

            self.start_job("正在保存站点设置", store)

        self.button(form, "保存站点", save, primary=True, locked=False).grid(row=5, column=1, sticky="e", pady=(5, 0))

    def login_settings(self):
        try:
            load_site_profile(APP_DATA)
        except ProfileError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self.window)
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("SRM 登录设置")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        dialog.grab_set()
        form = ttk.Frame(dialog, style="Panel.TFrame", padding=18)
        form.pack(fill="both", expand=True)
        account = tk.StringVar()
        sub = tk.StringVar()
        password = tk.StringVar()
        try:
            stored = has_credentials(APP_DATA)
        except Exception:
            stored = False
        ttk.Label(form, text="定时登录凭据", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(form, style="Note.TLabel", text="已保存到当前 Windows 用户" if stored else "尚未保存。仅需手动导出时，也可以直接用浏览器登录。"
                  ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        fields = (("企业账号", account, ""), ("子账号（如有）", sub, ""), ("密码", password, "●"))
        for row, (label, variable, masking) in enumerate(fields, start=2):
            ttk.Label(form, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=(0, 7))
            entry = ttk.Entry(form, textvariable=variable, show=masking, width=37)
            entry.grid(row=row, column=1, sticky="ew", pady=(0, 7))
            if row == 2:
                entry.focus_set()

        def save():
            values = account.get().strip(), sub.get().strip(), password.get()
            if not values[0] or not values[2]:
                messagebox.showwarning(APP_NAME, "请输入企业账号和密码。", parent=dialog)
                return
            dialog.destroy()

            def store():
                with run_lock():
                    save_credentials(APP_DATA, *values)
                return "登录凭据已加密保存。"

            self.start_job("正在保存登录凭据", store)

        def browser_login():
            dialog.destroy()

            def login():
                with run_lock():
                    session = launch_login(APP_DATA, manual=True)
                    session.close()
                return "浏览器登录成功，可以手动导出。"

            self.start_job("请在 Edge 中完成登录", login)

        def forget():
            dialog.destroy()

            def remove():
                with run_lock():
                    forget_credentials(APP_DATA)
                    clear_session(APP_DATA)
                return "已清除登录凭据和本地会话。"

            self.start_job("正在清除登录凭据", remove)

        actions = ttk.Frame(form, style="Panel.TFrame")
        actions.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.button(actions, "浏览器登录", browser_login, locked=False).pack(side="left")
        self.button(actions, "清除登录", forget, locked=False).pack(side="left", padx=6)
        self.button(actions, "保存凭据", save, primary=True, locked=False).pack(side="right")

    def start_job(self, label, work, success=None):
        if self.job is not None:
            return
        self.job = label
        self.status.set(label)
        self.update_frequency()
        self.log(label)
        for control in self.controls:
            control.state(("disabled",))
        self.progress.grid()
        self.progress.start(12)

        def execute():
            try:
                result = work()
            except Exception as error:
                self.events.put(("failure", public_error(error)))
            else:
                self.events.put(("done", (result, success)))

        Thread(target=execute, daemon=True).start()

    def check_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "schedule":
                    self.schedule_status.set(payload)
                else:
                    self.job = None
                    self.progress.stop()
                    self.progress.grid_remove()
                    for control in self.controls:
                        control.state(("!disabled",))
                    self.update_frequency()
                    if kind == "failure":
                        self.status.set("操作失败")
                        self.log(payload)
                        messagebox.showerror(APP_NAME, payload, parent=self.window)
                    else:
                        message, callback = payload
                        self.status.set(message)
                        self.log(message)
                        if callback:
                            callback()
        except Empty:
            pass
        self.window.after(80, self.check_events)

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(message) + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def close(self):
        if self.job:
            messagebox.showinfo(APP_NAME, "请等本次操作完成后再关闭窗口。", parent=self.window)
        else:
            self.window.destroy()


def main() -> int:
    if sys.argv[1:] == ["--scheduled"]:
        return run_scheduled()
    window = tk.Tk()
    ExportApp(window)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
