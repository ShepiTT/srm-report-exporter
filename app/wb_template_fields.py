"""解析 SRM 模板字段定义并缓存。"""
import json
import re
from pathlib import Path
from typing import Any

import requests

def _parse_js(text: str):
    """从模板定义 JS 中抽取字段对象。

    每个字段形如：
        groupCode: 'baseForm',
        sortOrder: '12',
        fieldType: 'input',
        fieldLabel: '供应商ERP编码',
        fieldName: 'fbk3',
        dictCode: '',
    """
    fields = []
    for m in re.finditer(r"fieldName\s*:\s*'([^']*)'", text):
        name = m.group(1)
        head = text[max(0, m.start() - 900): m.start()]
        tail = text[m.end(): m.end() + 260]

        label_m = list(re.finditer(r"fieldLabel\s*:\s*'([^']*)'", head))
        if not label_m:
            continue
        label = label_m[-1].group(1).strip()

        order_m = list(re.finditer(r"sortOrder\s*:\s*'?(\d+)'?", head))
        order = int(order_m[-1].group(1)) if order_m else 999

        group_m = list(re.finditer(r"groupCode\s*:\s*'([^']*)'", head))
        group = group_m[-1].group(1) if group_m else ""

        type_m = list(re.finditer(r"fieldType\s*:\s*'([^']*)'", head))
        ftype = type_m[-1].group(1) if type_m else ""

        dict_m = re.search(r"dictCode\s*:\s*'([^']*)'", tail)
        dict_code = dict_m.group(1) if dict_m else ""

        fields.append(
            {
                "field": name,
                "label": label,
                "group": group,
                "sort": order,
                "type": ftype,
                "dict": dict_code,
            }
        )

    # 去重（同名取先出现的），按分组+顺序排
    seen, uniq = set(), []
    for f in fields:
        if f["field"] in seen:
            continue
        seen.add(f["field"])
        uniq.append(f)
    uniq.sort(key=lambda x: (x["group"], x["sort"]))
    return uniq


def get_template(key: tuple[Any, Any, Any], cache_dir: Path, srm_origin: str) -> dict:
    """Read or fetch the static field definition named by an authorized record."""
    number, version, account = map(str, key)
    if (not re.fullmatch(r"[A-Za-z0-9_-]+", number)
            or not re.fullmatch(r"[0-9]+", version)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", account)
            or number == "None" or account == "None"):
        raise ValueError("记录中的模板编号、版本或所属租户无效")

    cache_file = cache_dir / f"{number}_{version}_{account}.json"
    if cache_file.is_file():
        try:
            saved = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("fields"):
                return saved
        except (OSError, ValueError):
            pass

    url = f"{srm_origin}//opt/upFiles/js/{account}/sale_deductCost_{number}_{version}.js"
    response = requests.get(url, headers={"Referer": srm_origin}, timeout=20, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("模板字段定义未返回")
    text = response.content.decode("utf-8-sig", errors="replace")
    fields = _parse_js(text)
    if not fields:
        raise ValueError("模板字段定义为空或格式有变化")
    payload = {"fields": fields}
    cache_dir.mkdir(parents=True, exist_ok=True)
    staged = cache_file.with_suffix(".tmp")
    staged.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    staged.replace(cache_file)
    return payload
