"""Read the authenticated SRM list and export the selected Excel reports."""
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import requests

import wb_fetch
import wb_fetch_bill
from site_profile import load_site_profile
from wb_template_fields import get_template

LIST_PATH = "/els/finance/saleDeductCost/list"
DETAIL_API_PATH = "/gateway/qualitywarning/api/open/customerComplaintForm/queryDetail/"
PAGE_SIZE = 500
PAGE_PAUSE = 1.2
DETAIL_PAUSE = 0.5
DETAIL_CACHE_LIFETIME = 60 * 60 * 24


class ExportError(RuntimeError):
    """An issue that prevents a reliable export."""


class InconsistentPagination(ExportError):
    """The source list changed or repeated while being scanned."""


@dataclass(frozen=True)
class ExportResult:
    files: tuple[Path, ...]
    warnings: tuple[str, ...]
    deduct_count: int
    complaint_count: int


def _scan_once(session, start, end, progress):
    matched = []
    seen_ids = set()
    unknown_dates = 0
    total = None
    for page in range(1, 10_001):
        try:
            payload = session.get(
                LIST_PATH, keyWord="", pageSize=PAGE_SIZE, pageNo=page,
                filter="{}", column="id", order="desc",
            )
        except requests.RequestException:
            raise ExportError(f"读取 SRM 第 {page} 页失败，请检查网络后重试。") from None
        result = payload.get("result") if isinstance(payload, dict) else None
        if (not isinstance(result, dict) or payload.get("success") is False
                or not isinstance(result.get("records"), list)):
            raise ExportError(f"SRM 第 {page} 页未返回有效的扣款列表，请核对账号权限或系统状态。")

        records = result["records"]
        page_total = result.get("total")
        if page_total is not None:
            try:
                page_total = int(page_total)
            except (TypeError, ValueError):
                raise ExportError("SRM 返回的扣款总条数格式异常。") from None
            if page_total < 0:
                raise ExportError("SRM 返回的扣款总条数格式异常。")
            if total is not None and page_total != total:
                raise InconsistentPagination("扫描期间 SRM 扣款总条数发生变化。")
            total = page_total

        for record in records:
            if not isinstance(record, dict) or not record.get("id"):
                raise ExportError(f"SRM 第 {page} 页存在缺少标识的记录，无法核对完整性。")
            record_id = str(record["id"])
            if record_id in seen_ids:
                raise InconsistentPagination("SRM 返回了重复扣款记录，无法核对完整性。")
            seen_ids.add(record_id)
            record_date = _deduction_date(record)
            if record_date is None:
                unknown_dates += 1
            elif start <= record_date <= end:
                matched.append(record)

        if page == 1 or page % 5 == 0:
            count = f"{len(seen_ids)}/{total}" if total is not None else str(len(seen_ids))
            progress(f"正在读取 SRM 第 {page} 页，已核对 {count} 条，区间命中 {len(matched)} 条。")
        if total is not None and len(seen_ids) > total:
            raise InconsistentPagination("扫描条数超过 SRM 返回的总条数。")
        if not records and total is not None and len(seen_ids) != total:
            raise InconsistentPagination("SRM 列表已结束，扫描条数与总条数不一致。")
        if not records or (total is not None and len(seen_ids) == total):
            return matched, len(seen_ids), unknown_dates
        time.sleep(PAGE_PAUSE)

    raise ExportError("扫描超过 10,000 页，当前无法核对整个 SRM 列表。")


def _deduction_date(record):
    for field in ("deductTime", "createTime"):
        value = record.get(field)
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _complaint_params(link, complaint_origin):
    if not isinstance(link, str) or not link:
        return None
    try:
        url = urlsplit(link)
        portal = urlsplit(complaint_origin)
        if (url.scheme != "https" or url.hostname != portal.hostname
                or url.port not in (None, 443, 7084, portal.port)
                or url.username is not None or url.password is not None
                or url.path != "/customerComplaintDetails"):
            return None
        query = parse_qs(url.query, max_num_fields=16)
    except ValueError:
        return None
    ids, codes = query.get("id", []), query.get("code", [])
    if query.get("type") != ["supplier"] or len(ids) != 1 or len(codes) != 1:
        return None
    return {"id": ids[0], "code": codes[0]}


def _get_complaint_details(records, data_dir, complaint_origin, progress):
    pending = []
    for record in records:
        params = _complaint_params(record.get("exchangeRate"), complaint_origin)
        if params:
            pending.append((str(record["id"]), params))
    if not pending:
        return {}, False

    details = {}
    service_unavailable = False
    now = time.time()
    import contextlib

    detail_url = complaint_origin + DETAIL_API_PATH
    data_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(data_dir / "complaint_details.sqlite3")) as cache:
        cache.execute("CREATE TABLE IF NOT EXISTS details ("
                      "cache_key TEXT PRIMARY KEY, saved REAL NOT NULL, value TEXT NOT NULL)")
        recent_cutoff = now - DETAIL_CACHE_LIFETIME
        consecutive_failures = 0
        with requests.Session() as http:
            for index, (record_id, params) in enumerate(pending, start=1):
                encoded_key = json.dumps([params["id"], params["code"]], ensure_ascii=False)
                cache_key = hashlib.sha256(encoded_key.encode("utf-8")).hexdigest()
                saved = cache.execute(
                    "SELECT value FROM details WHERE cache_key = ? AND saved >= ?",
                    (cache_key, recent_cutoff),
                ).fetchone()
                if saved:
                    details[record_id] = json.loads(saved[0])
                elif not service_unavailable:
                    data, stop, transient_failure = _fetch_complaint_detail(http, detail_url, params)
                    consecutive_failures = consecutive_failures + 1 if transient_failure else 0
                    service_unavailable = stop or consecutive_failures >= 3
                    if data:
                        details[record_id] = data
                        with cache:
                            cache.execute(
                                "INSERT OR REPLACE INTO details(cache_key, saved, value) VALUES (?, ?, ?)",
                                (cache_key, time.time(), json.dumps(data, ensure_ascii=False)),
                            )
                    if not service_unavailable and index < len(pending):
                        time.sleep(DETAIL_PAUSE)
                if index == len(pending) or index % 10 == 0:
                    progress(f"正在核对客诉详情，已核对 {index}/{len(pending)} 条链接。")
    return details, service_unavailable


def _fetch_complaint_detail(http, detail_url, params):
    try:
        response = http.get(detail_url, params=params, timeout=20, allow_redirects=False)
        if response.status_code == 429:
            return None, True, True
        if response.status_code != 200:
            return None, False, response.status_code >= 500
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None, False, True
    if isinstance(payload, dict) and payload.get("success") and isinstance(payload.get("data"), dict):
        return payload["data"], False, False
    return None, False, False


def _build_templates(records, data_dir, srm_origin):
    templates = {}
    for record in records:
        key = (record.get("templateNumber"), record.get("templateVersion"), record.get("busAccount"))
        if key in templates:
            continue
        try:
            template = get_template(key, data_dir / "templates", srm_origin)
        except (OSError, ValueError, requests.RequestException):
            name = record.get("templateName") or "未知模板"
            raise ExportError(f"无法读取「{name}」的字段定义，请检查网络或模板配置后重试。") from None
        template["templateNameHint"] = record.get("templateName") or key[0]
        templates[key] = template
    return templates


def export_reports(session, start: date, end: date, output_dir: Path, data_dir: Path, *,
                   deduct: bool = True, complaints: bool = True, progress=lambda _message: None):
    """Export every authorized record matching the inclusive SRM deduction-date range."""
    if start > end:
        raise ExportError("开始日期不能晚于结束日期。")
    if not (deduct or complaints):
        raise ExportError("请至少选择一份报表。")
    output_dir, data_dir = Path(output_dir), Path(data_dir)
    profile = load_site_profile(data_dir)
    if getattr(session, "origin", None) != profile.srm_origin:
        raise ExportError("当前 SRM 会话与站点配置不一致，请重新登录后重试。")
    cache_key = json.dumps([profile.srm_origin, profile.complaint_origin], ensure_ascii=False)
    site_cache = data_dir / "site_cache" / hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ExportError("无法创建报表目录或程序数据目录，请检查目录权限。") from None

    progress("开始读取 SRM 扣款列表并按日期筛选。")
    try:
        records, scanned, unknown_dates = _scan_once(session, start, end, progress)
    except InconsistentPagination:
        progress("扣款列表在扫描期间发生变化，正在重新核对一次。")
        records, scanned, unknown_dates = _scan_once(session, start, end, progress)

    progress(f"已核对 {scanned} 条 SRM 记录，所选日期命中 {len(records)} 条。")
    warnings = []
    if unknown_dates:
        warnings.append(f"有 {unknown_dates} 条 SRM 记录的扣款和创建日期都无效，未能归入任何日期。")
    complaint_template_ids = set(profile.complaint_template_ids)
    complaint_records = [record for record in records
                         if str(record.get("templateNumber")) in complaint_template_ids
                         or str(record.get("templateName", "")).startswith("消费者索赔")]
    detail_data = {}
    try:
        if complaints and not profile.complaint_origin:
            warnings.append("未配置客诉门户，客诉账单仅包含 SRM 可取得的字段。")
        elif complaints and complaint_records:
            progress(f"正在获取 {len(complaint_records)} 条客诉扣款相应的详情。")
            detail_data, unavailable = _get_complaint_details(
                complaint_records, site_cache, profile.complaint_origin, progress,
            )
            if unavailable:
                warnings.append("客诉详情服务暂不可用或限流，本次保留可用详情。")
            missing_count = len(complaint_records) - len(detail_data)
            if missing_count:
                warnings.append(f"有 {missing_count} 条客诉无法取得详情，已导出其 SRM 扣款字段。")
            warnings.append("客诉详情未提供的字段留空，详见客诉账单的「抓取说明」。")
    except (OSError, sqlite3.Error, ValueError):
        raise ExportError("无法读取客诉详情缓存，请检查程序数据目录及磁盘空间。") from None

    label = f"{start.isoformat()}_{end.isoformat()}"
    files = []
    try:
        with TemporaryDirectory(prefix="报表导出_", dir=output_dir) as temporary:
            staging = Path(temporary)
            reports = []
            if deduct:
                progress("正在生成扣款明细 Excel。")
                name = f"扣款明细_{label}.xlsx"
                templates = _build_templates(records, site_cache, profile.srm_origin)
                wb_fetch.build_excel(records, templates, staging / name, {
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "date_field": "要求扣款日期，缺失时按创建日期",
                    "scanned": scanned,
                    "matched": len(records),
                })
                reports.append(name)
            if complaints:
                progress("正在生成客诉账单 Excel。")
                name = f"客诉账单_{label}.xlsx"
                wb_fetch_bill.build_excel(
                    complaint_records, detail_data, staging / name, start, end,
                    portal_configured=bool(profile.complaint_origin),
                )
                reports.append(name)
            for name in reports:
                target = output_dir / name
                (staging / name).replace(target)
                files.append(target)
    except OSError:
        completed = f"已更新 {len(files)} 份报表。" if files else ""
        raise ExportError(f"{completed}写入报表失败，请关闭已打开的同名 Excel，并检查目录权限与磁盘空间后重试。") from None

    return ExportResult(tuple(files), tuple(warnings), len(records) if deduct else 0,
                        len(complaint_records) if complaints else 0)
