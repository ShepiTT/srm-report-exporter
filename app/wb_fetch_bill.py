"""按原账单的 35 列和双层表头生成客诉工作簿。"""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from wb_fetch import append_text_safe, fmt_cell, money, style_header

PAY_METHOD = {1: "微信", 3: "支付宝", "1": "微信", "3": "支付宝"}

# 账单 35 列（顺序必须与模板一致）
COLS = [
    "客诉编号", "是否有调整", "门店名称", "所属品牌", "第三方单据编号", "顾客投诉时间",
    "创建时间", "问题类型", "工单附件", "投诉内容及门店处理方案", "报销金额", "购买/发生时间",
    "是否食用", "一级问题类型", "二级问题类型", "三级问题类型", "产品名称", "产品编码",
    "商品类别", "生产日期", "配送仓库", "问题类型一", "问题类型二", "问题类型三", "问题点",
    "付款编号", "支付方式", "支付金额", "支付备注", "支付凭证", "赔偿总金额",
    "当前供应商承担金额", "供应商承担金额", "公司承担金额", "结案时间",
]
WIDTHS = (15, 15, 57, 12, 21, 18, 19, 47, 60, 60, 12, 19, 12, 18, 18, 21, 50,
          12, 12, 12, 30, 15, 15, 19, 60, 15, 12, 12, 12, 12, 15, 27, 21, 18, 19)
GROUPS = (
    ("A1:I1", "工单信息"),
    ("J1:P1", "投诉信息"),
    ("Q1:Y1", "产品问题"),
    ("Z1:AD1", "解决方案"),
    ("AE1:AI1", "结案信息"),
)
MONEY_COLUMNS = {11, 28, 31, 32, 33, 34}


def split_product(fbk7: str):
    """拆开 SRM 物料字段中的编码和品名。"""
    s = str(fbk7 or "").strip()
    if "_" in s:
        code, name = s.split("_", 1)
        if code.strip().isdigit():
            return name.strip(), code.strip()
    return s, ""


def build_row(r: dict, d: dict | None) -> list:
    """把 SRM 记录 + 客诉详情合成账单的一行。"""
    d = d or {}
    p0 = first_item(d.get("productProblemList"))
    pay0 = first_item(d.get("paymentOrderList"))
    duty = first_item(d.get("dutyDivideList"))

    f1 = p0.get("problemTypeFirstName") or ""
    f2 = p0.get("problemTypeSecondName") or ""
    f3 = p0.get("problemTypeThirdName") or ""
    problem = "/".join(str(value) for value in (f1, f2, f3) if value)

    files = [str(v["fileUrl"]) for v in (d.get("relatedVoucherList") or [])
             if isinstance(v, dict) and v.get("fileUrl")]
    pname, pcode = split_product(r.get("fbk7"))
    if not pname:
        pname = p0.get("productName") or ""

    return [
        d.get("complaintCode") or str(r.get("fbk1") or "").split("-")[0],
        "",
        d.get("storeName") or r.get("fbk5") or "",
        r.get("customerComplaintBrand_dictText") or "",
        "",
        "",
        d.get("createTime") or "",
        problem,
        "\n".join(files),
        d.get("complaintContent") or r.get("deductReason") or "",
        0 if d else "",
        "",
        d.get("whetherEatName") or "",
        f1, f2, f3,
        pname,
        pcode,
        "",
        p0.get("productBatchNo") or "",
        "",
        f1, f2, f3,
        p0.get("problemDescription") or "",
        pay0.get("paymentOrderNo") or "",
        PAY_METHOD.get(pay0.get("paymentMethod"), ""),
        pay0.get("approvedAmount"),
        pay0.get("paymentRemarks") or "",
        "",
        d.get("totalMoney"),
        duty.get("amountBorneSupplier", r.get("taxAmount")),
        duty.get("amountBorneSupplier", r.get("taxAmount")),
        duty.get("amountBorneCompany"),
        "",
    ]


def first_item(value):
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def build_excel(records, details, path, start, end, *, portal_configured=True):
    wb = Workbook()
    ws = wb.active
    ws.title = "0"
    header_font = Font(name="宋体", bold=True, size=14)
    header_fill = PatternFill("solid", fgColor="C0C0C0")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cells, group in GROUPS:
        ws[cells.split(":")[0]] = group
    for col, (header, width) in enumerate(zip(COLS, WIDTHS, strict=True), start=1):
        ws.cell(2, col, header)
        ws.column_dimensions[get_column_letter(col)].width = width
    for row in ws.iter_rows(min_row=1, max_row=2, max_col=len(COLS)):
        for cell in row:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border
    for cells, _group in GROUPS:
        ws.merge_cells(cells)

    regular = Font(name="宋体", size=10)
    for row_no, record in enumerate(records, start=3):
        values = build_row(record, details.get(str(record["id"])))
        append_text_safe(ws, [money(value) if col in MONEY_COLUMNS else fmt_cell(value)
                              for col, value in enumerate(values, start=1)])
        for cell in ws[row_no]:
            cell.font = regular
            if cell.column in MONEY_COLUMNS:
                cell.number_format = "#,##0.00"

    info = wb.create_sheet("抓取说明")
    for row in [
        ("项目", "内容"),
        ("日期区间", f"{start.isoformat()} ~ {end.isoformat()}"),
        ("归集日期", "SRM 要求扣款日期，缺失时按 SRM 创建日期"),
        ("客诉扣款条数", len(records)),
        ("可用客诉详情", len(details)),
        ("详情来源", "用户配置的客诉门户" if portal_configured else "未配置客诉门户，仅导出 SRM 可取得的字段。"),
        ("待补字段", "第三方单据编号、顾客投诉时间、购买/发生时间、是否食用、配送仓库、结案时间"),
        ("说明", "详情源未返回的字段留空。无法取得详情时，供应商承担金额使用 SRM 实际扣款金额。"),
    ]:
        append_text_safe(info, list(row))
    style_header(info, 2)
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 75
    wb.save(path)
