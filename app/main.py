from __future__ import annotations

import os
import sys
import tkinter as tk
from calendar import monthrange
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
from tkinter import filedialog, messagebox

import ui_kit as ui
from app_auth import clear_session, forget_credentials, has_credentials, launch_login, save_credentials
from app_runtime import (
    APP_DATA, APP_NAME, PICKED_REPORT_NAME, Settings, completed_period, load_settings, open_run_log,
    public_error, run_export, run_lock, run_scheduled, run_summary, save_settings,
)
from site_profile import ProfileError, SiteProfile, load_site_profile, save_site_profile
from summary_report import REPORT_NAME, find_sources
from win_schedule import get_schedule, remove_schedule, set_schedule


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
WEEKDAY_SHORT = ("一", "二", "三", "四", "五", "六", "日")
FREQUENCY = {"每天": "daily", "每周": "weekly"}
PRESETS = ("昨天", "近 7 天", "本月", "上月")
ASSETS = Path(__file__).resolve().parent


def preset_period(name: str, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    if name == "昨天":
        return completed_period("daily", today)
    if name == "近 7 天":
        return completed_period("weekly", today)
    if name == "本月":
        first = today.replace(day=1)
        return first, max(first, today - timedelta(days=1))
    last_month_end = today.replace(day=1) - timedelta(days=1)
    return last_month_end.replace(day=1), last_month_end.replace(day=monthrange(last_month_end.year,
                                                                               last_month_end.month)[1])


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

        ui.init(window)
        px = ui.px
        window.title(APP_NAME)
        window.geometry(f"{px(1080)}x{px(780)}")
        window.minsize(px(980), px(700))
        window.configure(background=ui.BG)
        window.protocol("WM_DELETE_WINDOW", self.close)
        if sys.platform == "win32" and (ASSETS / "report.ico").exists():
            window.iconbitmap(default=str(ASSETS / "report.ico"))

        start, end = completed_period("daily")
        self.output = tk.StringVar(value=self.settings.output_dir)
        self.deduct = tk.BooleanVar(value=self.settings.deduct)
        self.complaints = tk.BooleanVar(value=self.settings.complaints)
        self.summary_auto = tk.BooleanVar(value=self.settings.summary_after_export)
        self.preset = tk.StringVar(value="昨天")
        self.start_date = tk.StringVar(value=start.isoformat())
        self.end_date = tk.StringVar(value=end.isoformat())
        self.frequency = tk.StringVar(value="每周" if self.settings.frequency == "weekly" else "每天")
        self.weekday = tk.StringVar(value=WEEKDAY_SHORT[self.settings.weekday])
        self.run_at = tk.StringVar(value=self.settings.time_hhmm)
        self.schedule_range = tk.StringVar()
        self.status = tk.StringVar(value="就绪")
        self.summary_files = tk.StringVar()
        self.summary_last = tk.StringVar()
        self.build()
        self.update_frequency()
        self.refresh_status()
        self.refresh_summary_info()
        for variable in (self.start_date, self.end_date):
            variable.trace_add("write", lambda *_: self.match_preset())
        self.output.trace_add("write", lambda *_: self.window.after_idle(self.refresh_summary_info))
        try:
            load_site_profile(APP_DATA)
            self.log("可以按日期导出，或生成汇总分析。")
        except ProfileError:
            self.log("先点右上角「设置站点」填写 SRM 地址，再设置登录。")
        if setup_error:
            self.log(setup_error)
        self.window.after(80, self.check_events)
        Thread(target=self.query_schedule, daemon=True).start()

    # ------------------------------------------------------------ 布局
    def button(self, parent, label, command, *, kind="secondary", locked=True, **options):
        widget = ui.Button(parent, label, command, kind=kind, **options)
        if locked:
            self.controls.append(widget)
        return widget

    def build(self):
        px = ui.px
        root = ui.frame(self.window)
        root.pack(fill="both", expand=True, padx=px(22), pady=(px(18), px(20)))
        root.columnconfigure((0, 1, 2), weight=1, uniform="column")
        root.rowconfigure(3, weight=1)

        header = ui.frame(root)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, px(14)))
        header.columnconfigure(1, weight=1)
        logo = tk.Canvas(header, width=px(44), height=px(44), highlightthickness=0, bd=0, background=ui.BG)
        logo.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, px(12)))
        ui.round_rect(logo, 0, 0, px(44), px(44), px(10), fill=ui.BRAND)
        for index, height in enumerate((12, 20, 28)):
            x = px(11 + index * 8.5)
            logo.create_rectangle(x, px(34 - height), x + px(5), px(34), fill="#ffffff", width=0)
        ui.label(header, "扣款与客诉导出", font="title").grid(row=0, column=1, sticky="sw")
        ui.label(header, "从 SRM 按日期导出 Excel，合并去重后生成汇总分析", font="small", fg=ui.MUTED).grid(
            row=1, column=1, sticky="nw")
        pills = ui.frame(header)
        pills.grid(row=0, column=2, rowspan=2, sticky="e")
        self.site_pill = ui.Pill(pills, "站点", command=self.site_settings)
        self.site_pill.pack(side="left", padx=(0, px(8)))
        self.login_pill = ui.Pill(pills, "登录", command=self.login_settings)
        self.login_pill.pack(side="left")

        self.build_reports(root)
        self.build_manual(root)
        self.build_schedule(root)
        self.build_summary(root)
        self.build_activity(root)

    def build_reports(self, root):
        px = ui.px
        card = ui.Card(root, pad=16)
        card.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, px(12)))
        body = card.body
        body.columnconfigure(5, weight=1)
        ui.label(body, "导出报表", font="strong").grid(row=0, column=0, sticky="w", padx=(0, px(12)))
        for column, (text, variable) in enumerate((("扣款明细（含客诉扣款）", self.deduct),
                                                   ("客诉账单", self.complaints)), start=1):
            check = ui.Check(body, text, variable)
            check.grid(row=0, column=column, sticky="w", padx=(0, px(8)))
            self.controls.append(check)
        ui.label(body, "保存到", font="strong").grid(row=0, column=4, sticky="e", padx=(px(16), px(10)))
        field = ui.Field(body, self.output, width=330)
        field.grid(row=0, column=5, sticky="ew")
        self.controls.append(field)
        self.button(body, "更改…", self.choose_folder).grid(row=0, column=6, padx=(px(8), 0))
        self.button(body, "打开", self.open_output, locked=False).grid(row=0, column=7, padx=(px(6), 0))

    def footer(self, body, row):
        body.rowconfigure(row, weight=1)
        actions = ui.frame(body)
        actions.grid(row=row + 1, column=0, sticky="sew", pady=(ui.px(14), 0))
        return actions

    def build_manual(self, root):
        px = ui.px
        card = ui.Card(root, title="手动导出", note="按要求扣款日期筛选，含起止当天。")
        card.grid(row=2, column=0, sticky="nsew", padx=(0, px(6)), pady=(0, px(12)))
        body = card.body
        presets = ui.Segmented(body, PRESETS, self.preset, command=self.apply_preset, small=True)
        presets.grid(row=2, column=0, sticky="ew", pady=(px(12), px(10)))
        self.controls.append(presets)
        dates = ui.frame(body)
        dates.grid(row=3, column=0, sticky="ew")
        dates.columnconfigure((0, 2), weight=1)
        for column, (text, variable) in ((0, ("开始日期", self.start_date)), (2, ("结束日期", self.end_date))):
            ui.label(dates, text, font="small", fg=ui.INK2).grid(row=0, column=column, sticky="w", pady=(0, px(4)))
            field = ui.Field(dates, variable, width=118)
            field.grid(row=1, column=column, sticky="ew")
            self.controls.append(field)
        ui.label(dates, "→", fg=ui.MUTED).grid(row=1, column=1, padx=px(8))
        actions = self.footer(body, 4)
        self.button(actions, "开始导出", self.manual_run, kind="primary").pack(side="right")

    def build_schedule(self, root):
        px = ui.px
        card = ui.Card(root, title="自动导出", note="电脑需开机联网，并保持登录。")
        card.grid(row=2, column=1, sticky="nsew", padx=px(6), pady=(0, px(12)))
        self.schedule_pill = card.header_right(ui.Pill(card.header, "读取中", small=True))
        body = card.body
        row = ui.frame(body)
        row.grid(row=2, column=0, sticky="ew", pady=(px(12), px(10)))
        frequency = ui.Segmented(row, tuple(FREQUENCY), self.frequency, command=self.update_frequency, small=True)
        frequency.pack(side="left")
        self.controls.append(frequency)
        ui.label(row, "时间", font="small", fg=ui.INK2).pack(side="left", padx=(px(14), px(6)))
        time_field = ui.Field(row, self.run_at, width=70)
        time_field.pack(side="left")
        self.controls.append(time_field)
        self.weekday_row = days = ui.frame(body)
        days.grid(row=3, column=0, sticky="ew")
        ui.label(days, "星期", font="small", fg=ui.INK2).pack(side="left", padx=(0, px(8)))
        self.weekday_control = ui.Segmented(days, WEEKDAY_SHORT, self.weekday, small=True)
        self.weekday_control.pack(side="left", fill="x", expand=True)
        ui.label(body, textvariable=self.schedule_range, font="small", fg=ui.MUTED).grid(
            row=4, column=0, sticky="w", pady=(px(8), 0))
        actions = self.footer(body, 5)
        self.button(actions, "保存并启用", self.enable_schedule, kind="primary").pack(side="right")
        self.button(actions, "停用", self.disable_schedule).pack(side="right", padx=(0, px(8)))

    def build_summary(self, root):
        px = ui.px
        card = ui.Card(root, title="汇总分析",
                       note="合并保存目录里的扣款明细并去重，\n生成网页报告，含罚款预警和待确认清单。")
        card.grid(row=2, column=2, sticky="nsew", padx=(px(6), 0), pady=(0, px(12)))
        body = card.body
        info = ui.frame(body)
        info.grid(row=2, column=0, sticky="ew", pady=(px(12), px(8)))
        info.columnconfigure(0, weight=1)
        self.summary_files_label = ui.label(info, textvariable=self.summary_files, fg=ui.INK)
        self.summary_files_label.grid(row=0, column=0, sticky="ew")
        ui.label(info, textvariable=self.summary_last, font="small", fg=ui.MUTED).grid(row=1, column=0, sticky="ew")
        info.bind("<Configure>", lambda event: self.summary_files_label.configure(wraplength=max(px(120), event.width)))
        auto = ui.Check(body, "导出后自动更新汇总", self.summary_auto, command=self.save_summary_choice)
        auto.grid(row=3, column=0, sticky="w")
        self.controls.append(auto)
        actions = self.footer(body, 4)
        self.button(actions, "生成汇总", self.generate_summary, kind="primary").pack(side="right")
        self.open_report_button = self.button(actions, "打开报告", self.open_report, locked=False)
        self.open_report_button.pack(side="right", padx=(0, px(8)))
        self.button(actions, "选文件…", self.pick_summary_files, kind="ghost").pack(side="left")

    def build_activity(self, root):
        px = ui.px
        card = ui.Card(root, title="运行记录", pad=16)
        card.grid(row=3, column=0, columnspan=3, sticky="nsew")
        body = card.body
        body.rowconfigure(3, weight=1)
        right = ui.frame(card.header)
        card.header_right(right)
        self.status_label = ui.label(right, textvariable=self.status, font="small", fg=ui.MUTED)
        self.status_label.pack(side="left", padx=(0, px(10)))
        self.button(right, "日志目录", self.open_logs, kind="ghost", locked=False, small=True).pack(side="left")
        self.busy = ui.Busy(body)
        self.busy.grid(row=2, column=0, sticky="ew", pady=(px(8), px(6)))
        self.log_view = ui.LogView(body)
        self.log_view.grid(row=3, column=0, sticky="nsew")

    # ------------------------------------------------------------ 状态
    def refresh_status(self):
        try:
            load_site_profile(APP_DATA)
            self.site_pill.set("站点已设置", "ok")
        except ProfileError:
            self.site_pill.set("设置站点", "warn")
        try:
            stored = has_credentials(APP_DATA)
        except Exception:
            stored = False
        self.login_pill.set("登录凭据已保存" if stored else "登录设置", "ok" if stored else "idle")

    def refresh_summary_info(self):
        folder = Path(self.output.get().strip())
        if not self.output.get().strip() or not folder.is_absolute():
            self.summary_files.set("请先选择保存目录。")
            self.summary_last.set("")
            self.open_report_button.state(("disabled",))
            return
        try:
            files = find_sources(folder)
            report = folder / REPORT_NAME
            report_time = datetime.fromtimestamp(report.stat().st_mtime) if report.is_file() else None
        except OSError:
            files, report_time = [], None
        self.summary_files.set(f"保存目录里有 {len(files)} 份扣款明细" if files else "保存目录里还没有扣款明细")
        self.summary_last.set(f"上次生成 {report_time:%m-%d %H:%M}" if report_time else "还没有生成过汇总报告")
        self.open_report_button.state(("!disabled",) if report_time else ("disabled",))

    def update_frequency(self, _event=None):
        weekly = self.frequency.get() == "每周"
        if weekly:
            self.weekday_row.grid()
        else:
            self.weekday_row.grid_remove()
        self.weekday_control.state(("!disabled",) if weekly and self.job is None else ("disabled",))
        self.schedule_range.set("每次导出运行日前连续 7 天的数据" if weekly else "每次导出昨天的数据")

    def apply_preset(self):
        start, end = preset_period(self.preset.get())
        self.start_date.set(start.isoformat())
        self.end_date.set(end.isoformat())

    def match_preset(self):
        current = (self.start_date.get().strip(), self.end_date.get().strip())
        for name in PRESETS:
            start, end = preset_period(name)
            if current == (start.isoformat(), end.isoformat()):
                if self.preset.get() != name:
                    self.preset.set(name)
                return
        if self.preset.get():
            self.preset.set("")

    # ------------------------------------------------------------ 文件与目录
    def choose_folder(self):
        selected = filedialog.askdirectory(parent=self.window, initialdir=self.output.get(), mustexist=True)
        if selected:
            self.output.set(selected)

    def reveal(self, path):
        try:
            if path.suffix:
                os.startfile(path)
            else:
                path.mkdir(parents=True, exist_ok=True)
                os.startfile(path)
        except (OSError, ValueError, AttributeError) as error:
            messagebox.showerror(APP_NAME, public_error(error), parent=self.window)

    def open_output(self):
        folder = Path(self.output.get().strip())
        if folder.is_absolute():
            self.reveal(folder)
        else:
            messagebox.showwarning(APP_NAME, "请先选择报表保存位置。", parent=self.window)

    def open_logs(self):
        self.reveal(APP_DATA / "logs")

    def open_report(self):
        report = Path(self.output.get().strip()) / REPORT_NAME
        if report.is_file():
            self.reveal(report)
        else:
            self.refresh_summary_info()

    def selected_reports(self):
        return replace(self.settings, output_dir=self.output.get().strip(),
                       deduct=self.deduct.get(), complaints=self.complaints.get(),
                       summary_after_export=self.summary_auto.get())

    # ------------------------------------------------------------ 导出
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

        self.start_job("正在导出", run, self.refresh_summary_info)

    # ------------------------------------------------------------ 汇总
    def generate_summary(self, files=None):
        settings = self.selected_reports()

        def run():
            logger = open_run_log()

            def report(line):
                logger.info(line)
                self.events.put(("log", line))

            try:
                result = run_summary(settings, report, files=files)
                for warning in result.warnings:
                    report(warning)
                self.events.put(("open", str(result.path)))
                return (f"已生成汇总：{result.files} 份文件、{result.documents:,} 张单据，"
                        f"{result.first_day} 至 {result.last_day}。")
            except Exception as error:
                logger.error("汇总失败。%s", public_error(error))
                raise
            finally:
                for handler in logger.handlers:
                    handler.close()

        self.start_job("正在生成汇总", run, self.refresh_summary_info)

    def pick_summary_files(self):
        selected = filedialog.askopenfilenames(
            parent=self.window, title="选择要汇总的扣款明细", initialdir=self.output.get(),
            filetypes=(("Excel 工作簿", "*.xlsx"),),
        )
        if selected:
            self.log(f"将汇总所选的 {len(selected)} 份文件，报告保存为 {PICKED_REPORT_NAME}")
            self.generate_summary(list(selected))

    def save_summary_choice(self):
        settings = replace(self.settings, summary_after_export=self.summary_auto.get())

        def store():
            with run_lock():
                save_settings(settings)
            self.settings = settings
            return "导出后会自动更新汇总。" if settings.summary_after_export else "导出后不再自动更新汇总。"

        self.start_job("正在保存汇总设置", store)

    # ------------------------------------------------------------ 自动任务
    def query_schedule(self):
        try:
            schedule = get_schedule()
        except Exception:
            self.events.put(("schedule", ("任务状态读取失败", "warn")))
            return
        if schedule and schedule.enabled and not self.settings.schedule_enabled:
            status = ("需重新保存设置", "warn")
        elif schedule and schedule.enabled and schedule.executable != Path(sys.executable):
            status = ("需更新 EXE 路径", "warn")
        elif schedule and schedule.enabled:
            status = ((f"已启用 · 每天 {schedule.time_hhmm}" if schedule.frequency == "daily"
                       else f"已启用 · {WEEKDAYS[schedule.weekday]} {schedule.time_hhmm}"), "ok")
        else:
            status = ("未启用", "idle")
        self.events.put(("schedule", status))

    def enable_schedule(self):
        settings = replace(self.selected_reports(), schedule_enabled=True,
                           frequency=FREQUENCY[self.frequency.get()],
                           time_hhmm=self.run_at.get().strip(), weekday=WEEKDAY_SHORT.index(self.weekday.get()))
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
        self.schedule_pill.set("读取中", "idle")
        Thread(target=self.query_schedule, daemon=True).start()

    # ------------------------------------------------------------ 对话框
    def dialog(self, title, heading, note):
        px = ui.px
        dialog = tk.Toplevel(self.window)
        dialog.title(title)
        dialog.transient(self.window)
        dialog.resizable(False, False)
        dialog.configure(background=ui.PANEL)
        form = tk.Frame(dialog, background=ui.PANEL, padx=px(24), pady=px(20))
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ui.label(form, heading, font="h2").grid(row=0, column=0, columnspan=2, sticky="w")
        ui.label(form, note, font="small", fg=ui.MUTED, wraplength=px(420)).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(px(2), px(14)))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        return dialog, form

    def dialog_fields(self, form, fields):
        px = ui.px
        entries = []
        for row, (text, variable, masking) in enumerate(fields, start=2):
            ui.label(form, text, fg=ui.INK2).grid(row=row, column=0, sticky="w", padx=(0, px(14)), pady=(0, px(8)))
            field = ui.Field(form, variable, width=320, show=masking)
            field.grid(row=row, column=1, sticky="ew", pady=(0, px(8)))
            entries.append(field)
        return entries

    def busy_now(self):
        if self.job:
            messagebox.showinfo(APP_NAME, "请等当前操作完成后再修改设置。", parent=self.window)
        return bool(self.job)

    def site_settings(self):
        if self.busy_now():
            return
        try:
            current = load_site_profile(APP_DATA)
        except ProfileError:
            current = SiteProfile("")

        dialog, form = self.dialog("站点设置", "业务站点", "填写管理员提供的 HTTPS 地址。站点设置只保存在这台电脑上。")
        srm = tk.StringVar(value=current.srm_origin)
        complaints = tk.StringVar(value=current.complaint_origin or "")
        templates = tk.StringVar(value=", ".join(current.complaint_template_ids))
        fields = self.dialog_fields(form, (("SRM 地址", srm, ""), ("客诉地址（可选）", complaints, ""),
                                           ("客诉模板编号（可选）", templates, "")))
        ui.label(form, "客诉模板编号可留空，程序会识别名称以「消费者索赔」开头的模板。", font="small", fg=ui.MUTED).grid(
            row=5, column=1, sticky="w")

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

        actions = ui.frame(form)
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(ui.px(16), 0))
        ui.Button(actions, "保存站点", save, kind="primary").pack(side="right")
        ui.Button(actions, "取消", dialog.destroy).pack(side="right", padx=(0, ui.px(8)))
        ui.center_over(dialog, self.window)
        dialog.grab_set()
        fields[0].focus_set()

    def login_settings(self):
        if self.busy_now():
            return
        try:
            load_site_profile(APP_DATA)
        except ProfileError as error:
            messagebox.showwarning(APP_NAME, str(error), parent=self.window)
            return
        try:
            stored = has_credentials(APP_DATA)
        except Exception:
            stored = False
        dialog, form = self.dialog(
            "SRM 登录设置", "登录",
            "手动导出可以直接用浏览器登录。定时任务需要保存凭据，凭据用当前 Windows 用户加密保存在这台电脑上。"
            + ("\n已保存凭据。" if stored else ""))
        account = tk.StringVar()
        sub = tk.StringVar()
        password = tk.StringVar()
        fields = self.dialog_fields(form, (("企业账号", account, ""), ("子账号（如有）", sub, ""), ("密码", password, "●")))

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

        actions = ui.frame(form)
        actions.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(ui.px(16), 0))
        ui.Button(actions, "保存凭据", save, kind="primary").pack(side="right")
        ui.Button(actions, "用浏览器登录", browser_login).pack(side="left")
        ui.Button(actions, "清除登录", forget, kind="ghost").pack(side="left", padx=(ui.px(6), 0))
        ui.center_over(dialog, self.window)
        dialog.grab_set()
        fields[0].focus_set()

    # ------------------------------------------------------------ 后台任务
    def start_job(self, label, work, success=None):
        if self.job is not None:
            return
        self.job = label
        self.status.set(label + "…")
        self.status_label.configure(fg=ui.BRAND)
        self.update_frequency()
        self.log(label)
        for control in self.controls:
            control.state(("disabled",))
        self.busy.start()

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
                    self.schedule_pill.set(*payload)
                elif kind == "open":
                    self.reveal(Path(payload))
                else:
                    self.job = None
                    self.busy.stop()
                    self.status_label.configure(fg=ui.MUTED)
                    for control in self.controls:
                        control.state(("!disabled",))
                    self.update_frequency()
                    self.refresh_status()
                    if kind == "failure":
                        self.status.set("操作失败")
                        self.log(payload, "error")
                        messagebox.showerror(APP_NAME, payload, parent=self.window)
                    else:
                        message, callback = payload
                        self.status.set("就绪")
                        self.log(message, "ok")
                        if callback:
                            callback()
                    self.refresh_summary_info()
        except Empty:
            pass
        self.window.after(80, self.check_events)

    def log(self, message, tone=None):
        self.log_view.add(message, tone)

    def close(self):
        if self.job:
            messagebox.showinfo(APP_NAME, "请等本次操作完成后再关闭窗口。", parent=self.window)
        else:
            self.window.destroy()


def main() -> int:
    if sys.argv[1:] == ["--scheduled"]:
        return run_scheduled()
    ui.enable_dpi_awareness()
    window = tk.Tk()
    ExportApp(window)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
