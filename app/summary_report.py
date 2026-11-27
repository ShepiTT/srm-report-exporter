"""合并扣款明细 Excel，按扣款单号去重，生成一份离线的汇总分析网页。

只依赖标准库和 openpyxl（打包时排除了 pandas 和 numpy）。口径：
- 同一扣款单号出现多次，优先保留「已确认」的版本，其次保留最后修改时间最晚的版本；
- 作废单据不计入金额和张数；按创建时间归月；
- 门店按门店名称匹配；罚款的门店从扣款说明里提取，按门店名后 6 个字对上。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile
from typing import Callable, Iterable

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

import store_geo
from summary_options import SummaryOptions
from summary_template import render_html

REPORT_NAME = "扣款汇总分析.html"
SOURCE_PREFIX = "扣款明细"
SUMMARY_SHEET = "扣款汇总"
INFO_SHEET = "抓取说明"
CACHE_VERSION = 1
CACHE_KEEP_DAYS = 30

# 扣款汇总页的列 → 内部字段名
BASE_FIELDS = (
    ("扣款单号", "id"), ("模板名称", "template"), ("采购组织", "org"), ("门店名称", "store"),
    ("物料", "item"), ("应扣款金额", "due"), ("实际扣款金额", "amount"), ("要求确认日期", "confirm_by"),
    ("单据状态", "status"), ("创建时间", "created"), ("最后修改时间", "modified"),
)
# 各模板页里补充的字段
DETAIL_FIELDS = (
    ("扣款单号", "id"), ("单据状态", "status"), ("最后修改时间", "modified"), ("索赔类型", "claim"),
    ("最后修改用户", "modifier"), ("发现事件日期", "found"), ("扣款说明", "note"), ("客诉品牌", "brand"),
    ("卸货费备注", "unload_note"), ("物料名称", "material"),
)
MONEY_KEYS = {"due", "amount"}

CATEGORIES = ("卸货费", "违规罚款", "门店报损", "消费者客诉", "质检单", "少称", "退货扣款", "调整单", "其他")
GROUPS = ("卸货费", "违规罚款", "门店报损", "消费者客诉", "质检单", "其他")
STORE_CATEGORIES = ("门店报损", "质检单", "消费者客诉")
_NON_CONSUMER = {"门店报损": "门店报损", "质检单": "质检单", "少称": "少称", "非消费者索赔": "违规罚款", "卸货费用": "卸货费"}
_TEMPLATES = {"供应商违规处理": "违规罚款", "卸货费用": "卸货费", "退货扣款单": "退货扣款", "调整单": "调整单"}
_PREFIXES = (("ZBS", "门店报损"), ("Z", "质检单"), ("S", "少称"))

# 质检单与罚款的分析参数
BAND_LOW, BAND_HIGH = 110.0, 130.0
WATCH_DAYS = 54
MATCH_DAYS = 3
AUTO_USER = "system_系统"
PENDING_STATUS = "待供应商确认"
PENDING_LIMIT = 2000

_PENALTY_STORE = re.compile(r"情况为(?:\d{4}年\d+月\d+日)?(?:顾客在)?(.+?店)")
_FOREIGN = re.compile(r"中有(.{1,6}?)异物")
_SERVICE_MONTH = re.compile(r"(\d{1,2})月")
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")


class SummaryError(RuntimeError):
    """汇总无法完成，信息可以直接展示给用户。"""


@dataclass(frozen=True)
class SummaryResult:
    path: Path
    files: int
    documents: int
    first_day: str
    last_day: str
    warnings: tuple[str, ...]


# ---------------------------------------------------------------- 读取

def find_sources(folder) -> list[Path]:
    """保存目录里本工具导出的扣款明细（不含子目录和 Excel 临时文件）。"""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        (path for path in folder.glob(f"{SOURCE_PREFIX}*.xlsx")
         if path.is_file() and not path.name.startswith("~$")),
        key=lambda path: path.name,
    )


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return "" if text in ("null", "None") else text


def _number(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else 0.0
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0
    return number if math.isfinite(number) else 0.0


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _sheet_rows(sheet, fields) -> Iterable[list]:
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        return
    position = {}
    for index, label in enumerate(header):
        label = _text(label)
        if label and label not in position:
            position[label] = index
    if "扣款单号" not in position:
        return
    columns = [(position.get(label), key) for label, key in fields]
    for row in rows:
        if not row:
            continue
        values = []
        for index, key in columns:
            raw = row[index] if index is not None and index < len(row) else None
            values.append(_number(raw) if key in MONEY_KEYS else _text(raw))
        if values[0]:
            yield values


def _read_workbook(path: Path) -> dict:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except (OSError, InvalidFileException, zipfile.BadZipFile, KeyError, ValueError):
        raise SummaryError(f"无法打开「{path.name}」，文件可能已损坏或正被占用。") from None
    try:
        names = workbook.sheetnames
        if SUMMARY_SHEET not in names:
            raise SummaryError(f"「{path.name}」里没有「扣款汇总」页，不是本工具导出的扣款明细。")
        base = list(_sheet_rows(workbook[SUMMARY_SHEET], BASE_FIELDS))
        details = []
        for name in names:
            if name not in (SUMMARY_SHEET, INFO_SHEET):
                details.extend(_sheet_rows(workbook[name], DETAIL_FIELDS))
        info = {}
        if INFO_SHEET in names:
            for row in workbook[INFO_SHEET].iter_rows(min_row=2, values_only=True):
                if row and len(row) >= 2 and row[0]:
                    info[_text(row[0])] = _text(row[1])
    finally:
        workbook.close()
    return {"base": base, "details": details, "info": info}


def _cache_name(path: Path) -> str:
    stat = path.stat()
    raw = f"{CACHE_VERSION}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".json.gz"


def load_source(path: Path, cache_dir: Path | None = None) -> tuple[dict, str | None]:
    """读取一份扣款明细；有缓存时直接用缓存。返回 (数据, 缓存文件名)。"""
    cache_name = None
    if cache_dir is not None:
        try:
            cache_name = _cache_name(path)
            with gzip.open(cache_dir / cache_name, "rt", encoding="utf-8") as stream:
                data = json.load(stream)
            if isinstance(data, dict) and {"base", "details", "info"} <= data.keys():
                return data, cache_name
        except (OSError, ValueError, EOFError):
            pass
    data = _read_workbook(path)
    if cache_name:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            staged = cache_dir / (cache_name + ".tmp")
            with gzip.open(staged, "wt", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
            staged.replace(cache_dir / cache_name)
        except OSError:
            pass
    return data, cache_name


def _prune_cache(cache_dir: Path, keep: set[str]) -> None:
    cutoff = time.time() - CACHE_KEEP_DAYS * 86400
    try:
        for item in cache_dir.glob("*.json.gz*"):
            if item.name not in keep and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- 合并

def _better(candidate: dict, current: dict) -> bool:
    return ((candidate["status"] == "已确认", candidate["modified"])
            > (current["status"] == "已确认", current["modified"]))


def _merge(sources: list[dict]):
    base_keys = [key for _label, key in BASE_FIELDS]
    detail_keys = [key for _label, key in DETAIL_FIELDS]
    records, details = {}, {}
    rows = duplicates = 0
    for source in sources:
        for values in source["base"]:
            rows += 1
            record = dict(zip(base_keys, values))
            current = records.get(record["id"])
            if current is None:
                records[record["id"]] = record
            else:
                duplicates += 1
                if _better(record, current):
                    records[record["id"]] = record
        for values in source["details"]:
            detail = dict(zip(detail_keys, values))
            current = details.get(detail["id"])
            if current is None or _better(detail, current):
                details[detail["id"]] = detail
    return records, details, rows, duplicates


def _category(record: dict, detail: dict) -> str:
    template = record["template"]
    if template.startswith("消费者索赔"):
        return "消费者客诉"
    if template == "非消费者索赔":
        kind = _NON_CONSUMER.get(detail.get("claim", ""))
        if kind:
            return kind
        for prefix, kind in _PREFIXES:
            if record["id"].startswith(prefix):
                return kind
        return "其他"
    return _TEMPLATES.get(template, "其他")


def _group(category: str) -> str:
    return category if category in GROUPS else "其他"


def _penalty_kind(text: str) -> str:
    if "召回" in text:
        return "批次召回"
    if "缺货" in text or "到货" in text or "混装" in text:
        return "缺货/送货不规范"
    if "月台" in text or "司机" in text or "园区" in text or "三角木" in text:
        return "司机/园区违规"
    if "入仓" in text:
        return "入仓质检不合格"
    if "逾期" in text or "报告" in text:
        return "报告逾期"
    if "异物" in text:
        return "门店/顾客发现异物"
    return "其他"


def _service_month(note: str, created: date | None) -> str | None:
    match = _SERVICE_MONTH.search(note or "")
    if not match or created is None:
        return None
    month = int(match.group(1))
    if not 1 <= month <= 12:
        return None
    year = created.year if month <= created.month else created.year - 1
    return f"{year}-{month:02d}"


def _months(first: date, last: date) -> list[str]:
    result, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        result.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return result


def _round(value, digits=2):
    return round(float(value), digits)


# ---------------------------------------------------------------- 分析

def _coverage(sources_meta: list[dict], first: date, last: date):
    """返回 (数据截至日, 导出区间之间缺的日期段)。"""
    intervals, ends = [], [last]
    for item in sources_meta:
        match = _RANGE.search(item.get("range", ""))
        if match:
            start, end = date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))
        else:  # 全部历史等不按日期筛选的导出：从最早一直覆盖到抓取当天
            end = _day(item.get("fetched", "")) or last
            start = min(first, end)
        intervals.append((start, end))
        ends.append(end)
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    gaps = [((previous[1] + timedelta(days=1)).isoformat(), (following[0] - timedelta(days=1)).isoformat(),
             (following[0] - previous[1]).days - 1)
            for previous, following in zip(merged, merged[1:])]
    return max(ends), gaps


def analyze(records: dict, details: dict, sources_meta: list[dict], *, today: date | None = None,
            options: SummaryOptions | None = None) -> dict:
    today = today or date.today()
    options = options or SummaryOptions()
    brand_prefixes = {brand: brand for detail in details.values() if (brand := _text(detail.get("brand")))}
    brand_prefixes.update(options.brand_prefixes)
    warehouse_locations = options.warehouse_org_locations
    piece_rate = options.yuan_per_piece
    all_records = list(records.values())
    valid, void = [], []
    for record in all_records:
        detail = details.get(record["id"], {})
        record["cat"] = _category(record, detail)
        record["group"] = _group(record["cat"])
        record["day"] = _day(record["created"])
        (void if record["status"] == "作废" else valid).append(record)
    valid = [record for record in valid if record["day"] is not None]
    if not valid:
        raise SummaryError("所选扣款明细里没有有效单据，无法生成汇总。")
    days = [record["day"] for record in valid]
    first, last = min(days), max(days)
    as_of, coverage_gaps = _coverage(sources_meta, first, last)
    total_amount = sum(record["amount"] for record in valid)

    # ---- 构成
    by_cat = defaultdict(list)
    for record in valid:
        by_cat[record["cat"]].append(record["amount"])
    composition = [
        {"cat": cat, "group": _group(cat), "n": len(by_cat[cat]), "amt": _round(sum(by_cat[cat])),
         "med": _round(median(by_cat[cat])), "max": _round(max(by_cat[cat]))}
        for cat in CATEGORIES if by_cat.get(cat)
    ]
    amounts = sorted((record["amount"] for record in valid), reverse=True)
    positive_total = sum(value for value in amounts if value > 0) or 1.0
    top_count = max(1, len(amounts) // 100)
    pareto = {"top1": _round(sum(amounts[:top_count]) / positive_total, 4), "top1_n": top_count}

    # ---- 趋势
    span = (last - first).days
    if span > 120:
        unit, periods = "month", _months(first, last)
        period_of = lambda day: f"{day.year}-{day.month:02d}"  # noqa: E731
    elif span > 31:
        unit = "week"
        start = first - timedelta(days=first.weekday())
        periods, day = [], start
        while day <= last:
            periods.append(day.isoformat())
            day += timedelta(days=7)
        period_of = lambda day: (day - timedelta(days=day.weekday())).isoformat()  # noqa: E731
    else:
        unit = "day"
        periods = [(first + timedelta(days=offset)).isoformat() for offset in range(span + 1)]
        period_of = lambda day: day.isoformat()  # noqa: E731
    index = {period: position for position, period in enumerate(periods)}
    trend_amount = {group: [0.0] * len(periods) for group in GROUPS}
    trend_count = {group: [0] * len(periods) for group in GROUPS}
    for record in valid:
        position = index[period_of(record["day"])]
        trend_amount[record["group"]][position] += record["amount"]
        trend_count[record["group"]][position] += 1
    trend = {
        "unit": unit, "periods": periods,
        "amt": {group: [_round(value) for value in values] for group, values in trend_amount.items()},
        "cnt": trend_count,
    }

    # ---- 门店索引
    store_names = sorted({record["store"] for record in valid
                          if record["cat"] in STORE_CATEGORIES and record["store"]})
    by_store = defaultdict(lambda: defaultdict(list))
    for record in valid:
        if record["cat"] in STORE_CATEGORIES and record["store"]:
            by_store[record["store"]][record["cat"]].append(record)
    store_labels = {name: store_geo.clean_store(name, brand_prefixes) for name in store_names}
    suffix_cache = {}

    def stores_for(name: str) -> list[str]:
        if not name:
            return []
        key = name[-6:]
        if key not in suffix_cache:
            suffix_cache[key] = [store for store, label in store_labels.items() if label.endswith(key)]
        return suffix_cache[key]

    # ---- 罚款与质检单的关联
    qc_records = [record for record in valid if record["cat"] == "质检单"]
    qc_start = min((record["day"] for record in qc_records), default=None)
    penalties = []
    for record in valid:
        if record["cat"] != "违规罚款":
            continue
        detail = details.get(record["id"], {})
        text = re.sub(r"\s+", "", detail.get("note", ""))
        match = _PENALTY_STORE.search(text)
        store = match.group(1) if match else ""
        key = store_geo.clean_store(store, brand_prefixes)
        if key in ("门店", "店"):
            store = key = ""
        found = _day(detail.get("found", ""))
        foreign = _FOREIGN.search(text)
        item = {
            "id": record["id"], "created": record["day"].isoformat(), "found": found.isoformat() if found else "",
            "kind": _penalty_kind(text), "store": store, "prov": store_geo.locate(store, brand_prefixes)[0] if store else "",
            "material": detail.get("material", "") or record["item"], "amt": _round(record["amount"]),
            "foreign": foreign.group(1) if foreign else "", "status": record["status"], "qc": None, "kc": 0,
            "_matched": [],
        }
        if key and found:
            matched = stores_for(key)
            item["_matched"] = matched
            near, complaints = [], 0
            for name in matched:
                for qc in by_store[name]["质检单"]:
                    if abs((qc["day"] - found).days) <= MATCH_DAYS:
                        near.append(qc)
                for complaint in by_store[name]["消费者客诉"]:
                    if abs((complaint["day"] - found).days) <= 30:
                        complaints += 1
            item["kc"] = complaints
            if near:
                item["qc"] = {
                    "n": len(near), "amt": _round(sum(qc["amount"] for qc in near)),
                    "d": min(abs((qc["day"] - found).days) for qc in near),
                    "gap": (record["day"] - min(qc["day"] for qc in near)).days,
                }
        penalties.append(item)
    penalties.sort(key=lambda item: item["created"], reverse=True)

    foreign_all = [item for item in penalties if item["kind"] == "门店/顾客发现异物"]
    chain_start = max(options.chain_start, qc_start) if options.chain_start and qc_start else qc_start
    eligible = [item for item in foreign_all if item["store"] and item["found"] and chain_start
                and date.fromisoformat(item["found"]) >= chain_start]
    hits = [item for item in eligible if item["qc"]]
    chain = {
        "foreign": len(foreign_all), "foreign_amt": _round(sum(item["amt"] for item in foreign_all)),
        "eligible": len(eligible), "hit": len(hits),
        "same_day": sum(1 for item in hits if item["qc"]["d"] == 0),
        "with_complaint": sum(1 for item in eligible if item["kc"]),
        "start": chain_start.isoformat() if chain_start else "",
        "eligible_amt": _round(sum(item["amt"] for item in eligible)),
        "hit_amt": _round(sum(item["amt"] for item in hits)),
    }
    if hits:
        gaps = [item["qc"]["gap"] for item in hits]
        unit_amounts = [item["qc"]["amt"] / item["qc"]["n"] for item in hits]
        chain.update(
            gap_med=_round(median(gaps), 1), gap_min=min(gaps), gap_max=max(gaps),
            qc_med=_round(median(unit_amounts)),
            ratio_med=_round(median(item["amt"] / (item["qc"]["amt"] / item["qc"]["n"]) for item in hits), 1),
        )

    # 110～130 元质检单后来有没有升级
    escalated_keys = set()
    for item in hits:
        found = date.fromisoformat(item["found"])
        for name in item["_matched"]:
            escalated_keys.add((name, found))

    def escalated(qc: dict) -> bool:
        return any((qc["store"], qc["day"] + timedelta(days=offset)) in escalated_keys
                   for offset in range(-MATCH_DAYS, MATCH_DAYS + 1))

    in_band = [qc for qc in qc_records if BAND_LOW < qc["amount"] <= BAND_HIGH]
    band_escalated = sum(1 for qc in in_band if escalated(qc))
    # 观察期只看已有升级口径之后、截至日前 WATCH_DAYS 天内的质检单
    band_history = [qc for qc in in_band if as_of and (as_of - qc["day"]).days > WATCH_DAYS]
    chain["band"] = {
        "low": BAND_LOW, "high": BAND_HIGH, "n": len(in_band), "escalated": band_escalated,
        "settled_n": len(band_history), "settled_escalated": sum(1 for qc in band_history if escalated(qc)),
    }
    # 各金额档质检单的升级率：说明为什么盯 110～130 元这一档
    rates = []
    for low, high, label in ((None, 100, "≤100"), (100, 110, "100-110"), (110, 130, "110-130"),
                             (130, 160, "130-160"), (160, 200, "160-200"), (200, None, ">200")):
        items = [qc for qc in qc_records
                 if (low is None or qc["amount"] > low) and (high is None or qc["amount"] <= high)]
        rates.append({"label": label, "n": len(items), "esc": sum(1 for qc in items if escalated(qc)),
                      "band": label == f"{BAND_LOW:g}-{BAND_HIGH:g}"})
    chain["rates"] = rates

    watch = []
    if as_of:
        for qc in in_band:
            age = (as_of - qc["day"]).days
            if 0 <= age <= WATCH_DAYS and not escalated(qc):
                watch.append({"id": qc["id"], "day": qc["day"].isoformat(), "store": qc["store"],
                              "prov": store_geo.locate(qc["store"], brand_prefixes)[0], "amt": _round(qc["amount"]),
                              "age": age, "status": qc["status"]})
    watch.sort(key=lambda item: item["day"])
    for item in penalties:
        item.pop("_matched", None)

    # ---- 确认环节
    auto_by_cat, auto_total = {}, [0, 0]
    window_by_cat = defaultdict(list)
    for cat in CATEGORIES:
        auto_by_cat[cat] = [0, 0]
    covered = 0
    for record in valid:
        if record["status"] != "已确认":
            continue
        detail = details.get(record["id"])
        due, modified = _day(record["confirm_by"]), _day(record["modified"])
        if due and record["day"]:
            window_by_cat[record["cat"]].append((due - record["day"]).days)
        if not detail or not due or not modified:
            continue
        covered += 1
        automatic = detail.get("modifier") == AUTO_USER and (modified - due).days == 1
        auto_by_cat[record["cat"]][0] += automatic
        auto_by_cat[record["cat"]][1] += 1
        auto_total[0] += automatic
        auto_total[1] += 1
    confirm = {
        "auto": _round(auto_total[0] / auto_total[1], 4) if auto_total[1] else None,
        "covered": covered,
        "by_cat": [
            {"cat": cat, "n": auto_by_cat[cat][1], "auto": _round(auto_by_cat[cat][0] / auto_by_cat[cat][1], 4),
             "window": median(window_by_cat[cat]) if window_by_cat[cat] else None}
            for cat in CATEGORIES if auto_by_cat[cat][1]
        ],
    }
    pending = []
    for record in valid:
        if record["status"] != PENDING_STATUS:
            continue
        due = _day(record["confirm_by"])
        key = (record["cat"] == "违规罚款"
               or (record["cat"] == "质检单" and BAND_LOW < record["amount"] <= BAND_HIGH)
               or (record["cat"] == "消费者客诉" and record["amount"] >= 100))
        pending.append({
            "id": record["id"], "cat": record["cat"], "store": record["store"], "amt": _round(record["amount"]),
            "day": record["day"].isoformat(), "due": due.isoformat() if due else "",
            "left": (due - today).days if due else None, "key": key,
        })
    pending.sort(key=lambda item: (item["due"] or "9999", -item["amt"]))
    # 网页里最多列 PENDING_LIMIT 张：关键单据全部保留，其余按要求确认日期从早到晚取
    shown = [item for item in pending if item["key"]]
    shown += [item for item in pending if not item["key"]][:max(0, PENDING_LIMIT - len(shown))]
    shown.sort(key=lambda item: (item["due"] or "9999", -item["amt"]))
    confirm["pending_n"] = len(pending)
    confirm["pending_amt"] = _round(sum(item["amt"] for item in pending))
    # 计数用完整名单；网页里的清单最多列 800 张
    confirm["key_n"] = sum(1 for item in pending if item["key"])
    confirm["due_today"] = sum(1 for item in pending if item["left"] == 0)
    confirm["overdue"] = sum(1 for item in pending if item["left"] is not None and item["left"] < 0)

    # ---- 门店、品牌、省份
    stores = {}
    brand_aliases = sorted(brand_prefixes, key=len, reverse=True)
    for name, groups in by_store.items():
        brands = Counter(details.get(record["id"], {}).get("brand", "")
                         for items in groups.values() for record in items)
        brands.pop("", None)
        brand = (brands.most_common(1)[0][0] if brands
                 else next((prefix for prefix in brand_aliases if name.startswith(prefix)), ""))
        row = {"store": name, "brand": brand_prefixes.get(brand, brand),
               "prov": store_geo.locate(name, brand_prefixes)[0], "pen": 0, "pen_amt": 0.0}
        for cat, short in (("门店报损", "ls"), ("质检单", "qc"), ("消费者客诉", "kc")):
            row[short] = len(groups[cat])
            row[short + "_amt"] = _round(sum(record["amount"] for record in groups[cat]))
        row["amt"] = _round(row["ls_amt"] + row["qc_amt"] + row["kc_amt"])
        stores[name] = row
    for item in penalties:
        if item["store"]:
            key = store_geo.clean_store(item["store"], brand_prefixes)
            matched = stores_for(key)
            if len(matched) == 1:
                stores[matched[0]]["pen"] += 1
                stores[matched[0]]["pen_amt"] = _round(stores[matched[0]]["pen_amt"] + item["amt"])
    top_stores = sorted(stores.values(), key=lambda row: row["amt"] + row["pen_amt"], reverse=True)[:15]
    top_counts = sorted(stores.values(), key=lambda row: row["ls"] + row["qc"] + row["kc"], reverse=True)[:15]

    brand_rows = defaultdict(list)
    for row in stores.values():
        brand_rows[row["brand"] or "未标品牌"].append(row)
    brands = []
    for brand, rows in brand_rows.items():
        if len(rows) < 30:
            continue
        brands.append({
            "brand": brand, "stores": len(rows),
            "ls": _round(sum(row["ls"] for row in rows) / len(rows) * 100, 1),
            "qc": _round(sum(row["qc"] for row in rows) / len(rows) * 100, 1),
            "kc": _round(sum(row["kc"] for row in rows) / len(rows) * 100, 1),
            "has_qc": _round(sum(1 for row in rows if row["qc"]) / len(rows), 4),
            "has_kc": _round(sum(1 for row in rows if row["kc"]) / len(rows), 4),
        })
    brands.sort(key=lambda row: row["stores"], reverse=True)

    # 门店类单据按门店名、卸货费按仓库、罚款按说明里的门店归省；其余记为未识别
    provinces = defaultdict(lambda: {"amt": 0.0, "n": 0, **{group: 0.0 for group in GROUPS}})
    located_amt = 0.0
    placed = [(item["prov"], item["amt"], "违规罚款") for item in penalties]
    for record in valid:
        if record["cat"] == "违规罚款":
            continue
        if record["cat"] in STORE_CATEGORIES:
            province = store_geo.locate(record["store"], brand_prefixes)[0]
        elif record["cat"] == "卸货费":
            province = store_geo.locate_warehouse(record["org"], warehouse_locations)[1]
        else:
            province = ""
        placed.append((province, record["amount"], record["group"]))
    for province, amount, group in placed:
        row = provinces[province or "未识别"]
        row["amt"] += amount
        row["n"] += 1
        row[group] += amount
        if province:
            located_amt += amount
    province_rows = sorted(
        ({"prov": name, **{key: (_round(value) if isinstance(value, float) else value) for key, value in row.items()}}
         for name, row in provinces.items()),
        key=lambda row: (row["prov"] == "未识别", -row["amt"]),
    )

    # ---- 卸货费：按仓库，以及折算出货件数
    unload = [record for record in valid if record["cat"] == "卸货费"]
    by_warehouse = defaultdict(lambda: [0.0, 0, ""])
    pieces_by_month = defaultdict(float)
    for record in unload:
        name, province = store_geo.locate_warehouse(record["org"], warehouse_locations)
        entry = by_warehouse[name]
        entry[0] += record["amount"]
        entry[1] += 1
        entry[2] = province
        if piece_rate is not None:
            month = _service_month(details.get(record["id"], {}).get("unload_note", ""), record["day"])
            if month:
                pieces_by_month[month] += record["amount"] / piece_rate
    warehouses = sorted(
        ({"wh": name, "amt": _round(values[0]), "n": values[1], "prov": values[2],
          "pcs": round(values[0] / piece_rate) if piece_rate is not None else None} for name, values in by_warehouse.items()),
        key=lambda row: row["amt"], reverse=True,
    )
    volume = None
    months_with_pieces = sorted(month for month, pieces in pieces_by_month.items() if pieces > 0)
    if len(months_with_pieces) >= 3:
        monthly_counts = defaultdict(Counter)
        for record in valid:
            if record["cat"] in STORE_CATEGORIES:
                monthly_counts[f"{record['day'].year}-{record['day'].month:02d}"][record["cat"]] += 1
        rates = {"ls": [], "qc": [], "kc": []}
        for month in months_with_pieces:
            pieces = pieces_by_month[month]
            for cat, short in (("门店报损", "ls"), ("质检单", "qc"), ("消费者客诉", "kc")):
                rates[short].append(_round(monthly_counts[month][cat] / pieces * 10000, 2))
        volume = {"months": months_with_pieces, "pcs": [round(pieces_by_month[m]) for m in months_with_pieces],
                  "rate": rates}

    sources = [{key: item[key] for key in ("name", "rows", "range", "fetched")} for item in sources_meta]
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "today": today.isoformat(),
        "as_of": as_of.isoformat() if as_of else "",
        "first": first.isoformat(), "last": last.isoformat(),
        "gaps": coverage_gaps[:20], "gap_days": sum(gap[2] for gap in coverage_gaps),
        "sources": sources,
        "totals": {"n": len(valid), "amt": _round(total_amount), "void_n": len(void),
                   "void_amt": _round(sum(record["amount"] for record in void)),
                   "rows": sum(item["rows"] for item in sources_meta),
                   "unique": len(all_records)},
        "groups": GROUPS, "comp": composition, "pareto": pareto, "trend": trend,
        "chain": chain, "watch": watch, "penalties": penalties,
        "confirm": confirm, "pending": shown,
        "stores": {"top_amt": top_stores, "top_n": top_counts, "count": len(stores)},
        "brands": brands, "provinces": province_rows, "located_share": _round(located_amt / (total_amount or 1), 4),
        "warehouses": warehouses[:15], "warehouse_n": len(warehouses), "volume": volume,
        "params": {"band_low": BAND_LOW, "band_high": BAND_HIGH, "watch_days": WATCH_DAYS,
                   "match_days": MATCH_DAYS, "yuan_per_piece": piece_rate},
    }


# ---------------------------------------------------------------- 入口

def build_summary(paths: Iterable[Path], out_path: Path, *, cache_dir: Path | None = None,
                  progress: Callable[[str], None] = lambda _message: None,
                  today: date | None = None, options: SummaryOptions | None = None) -> SummaryResult:
    paths = list(dict.fromkeys(Path(path) for path in paths))
    if not paths:
        raise SummaryError("没有找到扣款明细。请先导出扣款明细，或选择要汇总的文件。")
    warnings, loaded, meta, used_cache = [], [], [], set()
    for number, path in enumerate(paths, start=1):
        progress(f"正在读取 {path.name}（{number}/{len(paths)}）")
        try:
            data, cache_name = load_source(path, cache_dir)
        except SummaryError as error:
            warnings.append(str(error))
            continue
        except OSError:
            warnings.append(f"无法读取「{path.name}」，已跳过。")
            continue
        if cache_name:
            used_cache.add(cache_name)
        loaded.append(data)
        meta.append({"name": path.name, "rows": len(data["base"]), "range": data["info"].get("日期区间", ""),
                     "fetched": data["info"].get("抓取时间", "")})
    if not loaded:
        raise SummaryError("；".join(warnings) or "没有可用的扣款明细。")
    if cache_dir is not None:
        _prune_cache(cache_dir, used_cache)

    progress("正在合并去重并计算汇总。")
    records, details, _rows, duplicates = _merge(loaded)
    data = analyze(records, details, meta, today=today, options=options)
    data["totals"]["duplicates"] = duplicates
    data["warnings"] = warnings

    out_path = Path(out_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=out_path.parent, suffix=".tmp", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(render_html(data))
        staged.replace(out_path)
    except OSError:
        raise SummaryError("无法写入汇总报告，请检查保存目录是否可写，并关闭已打开的同名文件。") from None
    return SummaryResult(out_path, len(loaded), data["totals"]["n"], data["first"], data["last"], tuple(warnings))
