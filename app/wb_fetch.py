"""按供应商模板生成扣款汇总和各类型明细。"""
import math
import pathlib
import re

from openpyxl import Workbook
from openpyxl.cell.cell import Cell, ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# 汇总页的列：候选标签按优先级取，不同模板叫法不一样
SUMMARY_SPEC = [
    ("扣款单号", ["扣款单号"]),
    ("模板名称", ["模板名称"]),
    ("供应商名称", ["供应商名称"]),
    ("采购组织", ["采购组织"]),
    ("门店编码", ["门店编码"]),
    ("门店名称", ["门店名称"]),
    ("客诉单号", ["客诉单号"]),
    ("物料", ["物料", "物料名称", "物料编码"]),
    ("应扣款金额", ["应扣款金额"]),
    ("实际扣款金额", ["实际扣款金额"]),
    ("要求扣款日期", ["要求扣款日期", "发现问题日期"]),
    ("要求确认日期", ["要求确认日期"]),
    ("索赔时间", ["索赔时间", "发现事件日期"]),
    ("单据状态", ["单据状态"]),
    ("审批状态", ["审批状态"]),
    ("是否对账", ["是否对账"]),
    ("扣款原因", ["扣款原因"]),
    ("创建时间", ["创建时间"]),
    ("最后修改时间", ["最后修改时间"]),
]

MONEY_FIELDS = {"应扣款金额", "实际扣款金额", "礼品金额"}


def value_of(r: dict, field: str):
    """优先取字典翻译值，其次原值。"""
    txt = r.get(f"{field}_dictText")
    raw = r.get(field)
    if txt not in (None, "", "null"):
        if str(txt) != str(raw):
            return txt
    return raw


def fmt_cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s in ("null", "None"):
        return ""
    return s


def money(v):
    """金额转数值，源数据里有的字段是字符串。"""
    v = fmt_cell(v)
    try:
        number = float(str(v).replace(",", ""))
        return number if math.isfinite(number) else str(v)
    except ValueError:
        return v


def append_text_safe(ws, values):
    """Treat server-provided text as text even when it looks like a formula."""
    row = []
    for value in values:
        if isinstance(value, str):
            value = Cell(ws, value=ILLEGAL_CHARACTERS_RE.sub("", value))
            value.data_type = "s"
        row.append(value)
    ws.append(row)


def style_header(ws, ncol):
    fill = PatternFill("solid", fgColor="2F5597")
    font = Font(bold=True, color="FFFFFF", size=10)
    thin = Side(style="thin", color="D9D9D9")
    for c in range(1, ncol + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=thin)
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 26


def autofit(ws, max_width=42):
    for col in range(1, ws.max_column + 1):
        width = 8
        for row in range(1, min(ws.max_row, 200) + 1):
            v = ws.cell(row=row, column=col).value
            if v is None:
                continue
            s = str(v)
            w = sum(2 if ord(ch) > 127 else 1 for ch in s)
            width = max(width, min(w + 2, max_width))
        ws.column_dimensions[get_column_letter(col)].width = width


def build_excel(records: list[dict], tpl_map: dict, out_path: pathlib.Path, meta: dict):
    wb = Workbook()

    # ---------- 汇总页 ----------
    ws = wb.active
    ws.title = "扣款汇总"

    # 每个模板建立 标签->字段 的索引
    tpl_index = {}
    for key, tpl in tpl_map.items():
        tpl_index[key] = {f["label"]: f["field"] for f in tpl["fields"]}

    headers = [c[0] for c in SUMMARY_SPEC] + ["记录ID"]
    ws.append(headers)

    for r in records:
        key = (r.get("templateNumber"), r.get("templateVersion"), r.get("busAccount"))
        idx = tpl_index.get(key, {})
        row = []
        for label, aliases in SUMMARY_SPEC:
            field = None
            for a in aliases:
                if a in idx:
                    field = idx[a]
                    break
            if field is None:
                row.append("")
            elif label in MONEY_FIELDS:
                row.append(money(value_of(r, field)))
            else:
                row.append(fmt_cell(value_of(r, field)))
        row.append(r.get("id"))
        append_text_safe(ws, row)

    style_header(ws, len(headers))
    autofit(ws)
    for col, (label, _) in enumerate(SUMMARY_SPEC, start=1):
        if label in MONEY_FIELDS:
            for row in range(2, ws.max_row + 1):
                ws.cell(row=row, column=col).number_format = "#,##0.00"

    # ---------- 按模板分页：完整详情字段 ----------
    by_tpl: dict[tuple, list[dict]] = {}
    for r in records:
        key = (r.get("templateNumber"), r.get("templateVersion"), r.get("busAccount"))
        by_tpl.setdefault(key, []).append(r)

    used_names = {"扣款汇总", "抓取说明"}
    for key, recs in sorted(by_tpl.items(), key=lambda kv: -len(kv[1])):
        tpl = tpl_map.get(key)
        if not tpl:
            continue
        name = re.sub(r"[\\/*?:\[\]]", "_", str(tpl.get("templateNameHint") or key[0]))
        name = ILLEGAL_CHARACTERS_RE.sub("", name).strip("'")[:28] or "扣款明细"
        base_name, i = name, 1
        while name in used_names:
            i += 1
            name = f"{base_name[:28 - len(str(i))]}{i}"
        used_names.add(name)

        sh = wb.create_sheet(name)
        cols = tpl["fields"]
        append_text_safe(sh, [f["label"] for f in cols])
        for r in recs:
            append_text_safe(sh,
                [
                    money(value_of(r, f["field"])) if f["label"] in MONEY_FIELDS
                    else fmt_cell(value_of(r, f["field"]))
                    for f in cols
                ]
            )
        style_header(sh, len(cols))
        autofit(sh)
        for c, f in enumerate(cols, start=1):
            if f["label"] in MONEY_FIELDS:
                for row in range(2, sh.max_row + 1):
                    sh.cell(row=row, column=c).number_format = "#,##0.00"

    # ---------- 抓取说明 ----------
    info = wb.create_sheet("抓取说明")
    rows = [
        ("项目", "内容"),
        ("数据来源", "SRM 扣款管理（销售协同）"),
        ("抓取时间", meta["fetched_at"]),
        ("日期区间", f'{meta["start"]} ~ {meta["end"]}'),
        ("归集日期字段", meta["date_field"]),
        ("扫描记录数", meta["scanned"]),
        ("命中记录数", meta["matched"]),
        ("模板数量", len(by_tpl)),
        ("接口", "/els/finance/saleDeductCost/list  ·  /els/finance/saleDeductCost/queryById"),
        ("备注", "各模板页的列名取自该模板的字段定义，扩展字段(fbk*)已还原为业务字段名"),
    ]
    for row in rows:
        append_text_safe(info, row)
    style_header(info, 2)
    autofit(info, 60)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
