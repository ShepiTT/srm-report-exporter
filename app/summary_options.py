"""Optional per-user settings for local report calculations."""

import json
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from pathlib import Path


@dataclass(frozen=True)
class SummaryOptions:
    brand_prefixes: dict[str, str] = field(default_factory=dict)
    warehouse_org_locations: dict[str, tuple[str, str]] = field(default_factory=dict)
    yuan_per_piece: float | None = None
    chain_start: date | None = None


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_summary_options(data_dir: Path) -> SummaryOptions:
    path = data_dir / "summary_options.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return SummaryOptions()
    except (OSError, ValueError):
        raise ValueError("无法读取本机的汇总配置 summary_options.json。") from None

    supported = {"brand_prefixes", "warehouse_org_locations", "yuan_per_piece", "chain_start"}
    if not isinstance(config, dict) or config.keys() - supported:
        raise ValueError("汇总配置包含无法识别的项目，格式请参照 README。")

    brands = config.get("brand_prefixes", {})
    if not isinstance(brands, dict) or any(not _text(key) or not _text(value) for key, value in brands.items()):
        raise ValueError("品牌前缀配置应为前缀与显示品牌的文字对照表。")

    warehouses = config.get("warehouse_org_locations", {})
    if not isinstance(warehouses, dict) or any(
        not _text(key) or not isinstance(pair, list) or len(pair) != 2 or not all(map(_text, pair))
        for key, pair in warehouses.items()
    ):
        raise ValueError("仓库配置应将组织前缀对应到地点与省份。")

    rate = config.get("yuan_per_piece")
    if rate is not None:
        try:
            if type(rate) not in (int, float) or not isfinite(rate) or rate <= 0:
                raise ValueError
            rate = float(rate)
        except (ValueError, OverflowError):
            raise ValueError("卸货费换算费率须为每件人民币金额，并且大于零。") from None

    start = config.get("chain_start")
    if start is not None:
        try:
            start_date = date.fromisoformat(start)
            if start_date.isoformat() != start:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("预警分析的开始日期应使用 YYYY-MM-DD 格式。") from None
    else:
        start_date = None

    return SummaryOptions(
        {key.strip(): value.strip() for key, value in brands.items()},
        {key.strip(): (pair[0].strip(), pair[1].strip()) for key, pair in warehouses.items()},
        rate,
        start_date,
    )
