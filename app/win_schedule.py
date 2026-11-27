"""Create and inspect the current user's Windows Task Scheduler entry."""

import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


_TASK_NAME_PREFIX = "SRMReportExportPortable"
_TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_NS = {"task": _TASK_NAMESPACE}
_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
)
_TIME_PATTERN = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $operation = $env:SRM_EXPORT_SCHEDULER_OPERATION
    if ($operation -eq 'sid') {
        [Console]::WriteLine($sid)
        return
    }
    $name = $env:SRM_EXPORT_SCHEDULER_PREFIX + '.' + $sid
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $root = $service.GetFolder('\')
    switch ($operation) {
        { $_ -in 'register', 'validate' } {
            $payload = [Convert]::FromBase64String([Console]::In.ReadToEnd())
            $xml = [Text.Encoding]::UTF8.GetString($payload)
            $flags = if ($_ -eq 'register') { 6 } else { 1 }
            # 6 creates or updates, 1 validates only, and 3 uses the interactive token.
            $root.RegisterTask($name, $xml, $flags, $sid, $null, 3, $null) | Out-Null
        }
        { $_ -in 'query', 'remove' } {
            try {
                if ($_ -eq 'query') {
                    $task = $root.GetTask($name)
                    [Console]::WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$task.Xml)))
                } else {
                    $root.DeleteTask($name, 0)
                }
            } catch {
                $failure = $_.Exception
                while ($null -ne $failure) {
                    if ($failure.HResult -eq -2147024894) {
                        [Console]::WriteLine('MISSING')
                        return
                    }
                    $failure = $failure.InnerException
                }
                throw
            }
        }
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.GetBaseException().Message)
    exit 1
}
"""


@dataclass(frozen=True)
class Schedule:
    frequency: str
    time_hhmm: str
    weekday: int
    executable: Path
    enabled: bool = True


def _run_scheduler(operation: str, xml: str = "") -> str:
    if os.name != "nt":
        raise RuntimeError("定时任务需要在 Windows 上设置。")
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    command = base64.b64encode(_POWERSHELL.encode("utf-16-le")).decode("ascii")
    environment = os.environ.copy()
    environment["SRM_EXPORT_SCHEDULER_OPERATION"] = operation
    environment["SRM_EXPORT_SCHEDULER_PREFIX"] = _TASK_NAME_PREFIX
    try:
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
            env=environment,
            input=base64.b64encode(xml.encode("utf-8")),
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("无法连接 Windows 任务计划程序。") from exc
    if result.returncode:
        error = result.stderr.decode("utf-8-sig", errors="replace").strip()
        message = next((line.strip() for line in error.splitlines() if line.strip()), "")
        if not message or message.startswith("#< CLIXML"):
            raise RuntimeError(f"Windows 任务计划程序操作失败（退出码 {result.returncode}）。")
        raise RuntimeError(f"Windows 任务计划程序操作失败。{message}")
    return result.stdout.decode("utf-8-sig").strip()


def build_task_xml(
    executable: Path,
    frequency: str,
    time_hhmm: str,
    weekday: int = 0,
    *,
    user_sid: str,
    start_date: date | None = None,
) -> str:
    """Build a task definition without reading or changing Windows state."""
    if frequency not in ("daily", "weekly"):
        raise ValueError("频率应为每天或每周。")
    if not _TIME_PATTERN.fullmatch(time_hhmm):
        raise ValueError("运行时间请使用 HH:MM 格式。")
    if not 0 <= weekday < len(_WEEKDAYS):
        raise ValueError("请选择一周中的某一天。")
    if not re.fullmatch(r"S-\d+(?:-\d+)+", user_sid):
        raise ValueError("Windows 用户 SID 格式无效。")

    run_time = time.fromisoformat(time_hhmm)
    if start_date is None:
        now = datetime.now()
        start_date = now.date()
        repeat_days = 1
        if frequency == "weekly":
            start_date += timedelta(days=(weekday - start_date.weekday()) % 7)
            repeat_days = 7
        if datetime.combine(start_date, run_time) <= now:
            start_date += timedelta(days=repeat_days)

    root = ET.Element("Task", {"version": "1.2", "xmlns": _TASK_NAMESPACE})
    registration = ET.SubElement(root, "RegistrationInfo")
    ET.SubElement(registration, "Description").text = "按设定的日期和时间导出 SRM 报表。"
    trigger = ET.SubElement(ET.SubElement(root, "Triggers"), "CalendarTrigger")
    ET.SubElement(trigger, "StartBoundary").text = datetime.combine(start_date, run_time).isoformat()
    if frequency == "daily":
        ET.SubElement(ET.SubElement(trigger, "ScheduleByDay"), "DaysInterval").text = "1"
    else:
        weekly = ET.SubElement(trigger, "ScheduleByWeek")
        ET.SubElement(weekly, "WeeksInterval").text = "1"
        ET.SubElement(ET.SubElement(weekly, "DaysOfWeek"), _WEEKDAYS[weekday])

    principal = ET.SubElement(ET.SubElement(root, "Principals"), "Principal", {"id": "CurrentUser"})
    ET.SubElement(principal, "UserId").text = user_sid
    ET.SubElement(principal, "LogonType").text = "InteractiveToken"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(root, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, "StopIfGoingOnBatteries").text = "false"
    ET.SubElement(settings, "StartWhenAvailable").text = "true"
    restart = ET.SubElement(settings, "RestartOnFailure")
    ET.SubElement(restart, "Interval").text = "PT15M"
    ET.SubElement(restart, "Count").text = "2"
    ET.SubElement(settings, "WakeToRun").text = "false"
    ET.SubElement(settings, "ExecutionTimeLimit").text = "PT2H"

    actions = ET.SubElement(root, "Actions", {"Context": "CurrentUser"})
    action = ET.SubElement(actions, "Exec")
    ET.SubElement(action, "Command").text = str(executable)
    ET.SubElement(action, "Arguments").text = "--scheduled"
    ET.SubElement(action, "WorkingDirectory").text = str(executable.parent)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def validate_task_xml(xml: str) -> None:
    """Have Windows validate this definition without creating a task."""
    _run_scheduler("validate", xml)


def set_schedule(executable: Path, frequency: str, time_hhmm: str, weekday: int = 0) -> None:
    executable = executable.resolve()
    if executable.suffix.casefold() != ".exe" or not executable.is_file():
        raise ValueError("未找到要定时运行的 EXE 文件。")
    xml = build_task_xml(executable, frequency, time_hhmm, weekday, user_sid=_run_scheduler("sid"))
    _run_scheduler("register", xml)


def get_schedule() -> Schedule | None:
    result = _run_scheduler("query")
    if result == "MISSING":
        return None
    try:
        task = ET.fromstring(base64.b64decode(result, validate=True).decode("utf-8"))
        trigger = task.find("task:Triggers/task:CalendarTrigger", _NS)
        if trigger is None:
            raise ValueError("Calendar trigger is missing")
        start = datetime.fromisoformat(trigger.findtext("task:StartBoundary", "", _NS))
        weekdays = trigger.find("task:ScheduleByWeek/task:DaysOfWeek", _NS)
        frequency = "weekly" if weekdays is not None else "daily"
        weekday = _WEEKDAYS.index(weekdays[0].tag.rsplit("}", 1)[-1]) if weekdays is not None else 0
        command = task.findtext("task:Actions/task:Exec/task:Command", "", _NS)
        if not command:
            raise ValueError("Command is missing")
        enabled = task.findtext("task:Settings/task:Enabled", "true", _NS) == "true"
        return Schedule(frequency, start.strftime("%H:%M"), weekday, Path(command), enabled)
    except (ET.ParseError, ValueError, IndexError) as exc:
        raise RuntimeError("无法读取 Windows 中保存的定时任务。") from exc


def remove_schedule() -> None:
    _run_scheduler("remove")
