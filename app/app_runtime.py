from __future__ import annotations

import json
import logging
import msvcrt
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from app_auth import AuthError, SessionExpired, get_session
from export_engine import ExportError, export_reports
from site_profile import load_site_profile
from summary_options import load_summary_options
from summary_report import REPORT_NAME, SummaryError, build_summary, find_sources


APP_NAME = "SRM 扣款与客诉导出"
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SrmReportExporterPortable"
DEFAULT_OUTPUT = Path.home() / "Documents" / "SRM报表"
PICKED_REPORT_NAME = "扣款汇总分析_所选文件.html"


@dataclass(frozen=True)
class Settings:
    output_dir: str = str(DEFAULT_OUTPUT)
    deduct: bool = True
    complaints: bool = True
    schedule_enabled: bool = False
    frequency: str = "daily"
    time_hhmm: str = "08:30"
    weekday: int = 0
    summary_after_export: bool = True

    def validate(self) -> None:
        if not isinstance(self.output_dir, str) or not self.output_dir.strip():
            raise ValueError("请选择报表保存位置。")
        if not Path(self.output_dir).is_absolute():
            raise ValueError("请选择完整的报表保存路径。")
        if not all(type(value) is bool for value in (self.deduct, self.complaints, self.schedule_enabled,
                                                       self.summary_after_export)):
            raise ValueError("报表或定时设置格式有误。")
        if not (self.deduct or self.complaints):
            raise ValueError("请至少勾选一种报表。")
        if self.frequency not in ("daily", "weekly") or type(self.weekday) is not int or not 0 <= self.weekday <= 6:
            raise ValueError("请选择有效的运行频率和星期。")
        if not isinstance(self.time_hhmm, str):
            raise ValueError("请输入 24 小时制时间，例如 08:30。")
        hours, separator, minutes = self.time_hhmm.partition(":")
        if not (separator and len(hours) == len(minutes) == 2 and hours.isascii() and minutes.isascii()
                and hours.isdecimal() and minutes.isdecimal() and int(hours) < 24 and int(minutes) < 60):
            raise ValueError("请输入 24 小时制时间，例如 08:30。")


def load_settings() -> Settings:
    path = APP_DATA / "settings.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("读取设置失败。请检查设置文件或在界面重新保存。") from error
    if not isinstance(values, dict):
        raise ValueError("设置文件格式有误，请在界面重新保存。")
    settings = Settings(**{key: values[key] for key in Settings.__dataclass_fields__ if key in values})
    settings.validate()
    return settings


def save_settings(settings: Settings) -> None:
    settings.validate()
    APP_DATA.mkdir(exist_ok=True, parents=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=APP_DATA, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(APP_DATA / "settings.json")
    finally:
        temporary.unlink(missing_ok=True)


def completed_period(frequency: str, today: date | None = None) -> tuple[date, date]:
    days = 7 if frequency == "weekly" else 1
    today = today or date.today()
    return today - timedelta(days=days), today - timedelta(days=1)


class RunBusy(RuntimeError):
    pass


@contextmanager
def run_lock():
    APP_DATA.mkdir(exist_ok=True, parents=True)
    with (APP_DATA / "run.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RunBusy("已有导出或登录操作正在进行，请稍后再试。") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def open_run_log() -> logging.Logger:
    log_dir = APP_DATA / "logs"
    log_dir.mkdir(exist_ok=True, parents=True)
    logger = logging.Logger("srm-export")
    handler = logging.FileHandler(log_dir / f"{date.today():%Y-%m-%d}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    return logger


def public_error(error: Exception) -> str:
    if isinstance(error, (AuthError, ExportError, RunBusy, SummaryError, ValueError)) or type(error) is RuntimeError:
        return str(error)
    if isinstance(error, PermissionError):
        return "无法写入文件。请确认目录可写，并关闭可能占用报表的 Excel 窗口。"
    if isinstance(error, OSError):
        return "文件或网络操作失败。请检查网络、保存目录和磁盘空间后重试。"
    return f"操作失败（{type(error).__name__}）。请检查网络与系统状态后重试。"


def run_export(settings: Settings, start: date, end: date, report: Callable[[str], None], *, scheduled=False):
    settings.validate()
    if start > end:
        raise ValueError("开始日期不能晚于结束日期。")
    with run_lock():
        profile = load_site_profile(APP_DATA)
        report(f"本次区间 {start:%Y-%m-%d} 至 {end:%Y-%m-%d}")
        output = Path(settings.output_dir)
        output.mkdir(exist_ok=True, parents=True)
        report("正在连接 SRM…")
        for refresh in (False, True):
            session = get_session(APP_DATA, refresh=refresh, scheduled=scheduled, profile=profile)
            try:
                result = export_reports(
                    session, start, end, output, APP_DATA,
                    deduct=settings.deduct, complaints=settings.complaints, progress=report,
                )
                break
            except SessionExpired:
                if refresh:
                    raise
                report("SRM 会话已过期，正在重新登录后重试。")
            finally:
                session.close()
        if settings.summary_after_export and settings.deduct:
            try:
                summary = _summarize(output, None, report)
                report(f"已更新汇总报告 {summary.path.name}")
            except Exception as error:  # 汇总失败不影响已经导出的 Excel
                report(f"汇总报告没有更新：{public_error(error)}")
        return result


def _summarize(folder: Path, files, report: Callable[[str], None]):
    if files:
        sources, target = [Path(path) for path in files], folder / PICKED_REPORT_NAME
    else:
        sources, target = find_sources(folder), folder / REPORT_NAME
        if not sources:
            raise SummaryError("保存目录里还没有扣款明细。请先导出扣款明细，或选择要汇总的文件。")
    try:
        options = load_summary_options(APP_DATA)
    except ValueError as error:
        raise SummaryError(str(error)) from None
    return build_summary(sources, target, cache_dir=APP_DATA / "summary_cache", progress=report, options=options)


def run_summary(settings: Settings, report: Callable[[str], None], files=None):
    """合并保存目录里的扣款明细（或所选文件），生成汇总网页。"""
    folder = Path(settings.output_dir)
    if not settings.output_dir.strip() or not folder.is_absolute():
        raise ValueError("请先选择报表保存位置。")
    with run_lock():
        folder.mkdir(exist_ok=True, parents=True)
        return _summarize(folder, files, report)


def run_scheduled() -> int:
    logger = open_run_log()
    try:
        settings = load_settings()
        if not settings.schedule_enabled:
            logger.info("自动导出未启用。")
            return 0
        result = run_export(settings, *completed_period(settings.frequency), logger.info, scheduled=True)
        for warning in result.warnings:
            logger.warning(warning)
        for path in result.files:
            logger.info("已保存 %s", path)
        logger.info("自动导出完成。")
        return 0
    except Exception as error:
        logger.error("自动导出失败。%s", public_error(error))
        return 1
    finally:
        for handler in logger.handlers:
            handler.close()
