"""Shared data loading, dates, money formatting and copy for the mock's engines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BADGE = "Synthetic demo data"


@dataclass(frozen=True)
class Catalog:
    """All synthetic data, keyed by id in file order.

    Behavior:
        Built once per data directory by `load_catalog`. Engines read it and never mutate it.
    """

    devices: dict[str, dict]
    plans: dict[str, dict]
    addons: dict[str, dict]
    streaming: dict[str, dict]
    curves: dict[str, dict]
    promotions: list[dict]
    customers: dict[str, dict]
    messages: dict[str, str] = field(default_factory=dict)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_catalog(data_dir: Path = DATA_DIR) -> Catalog:
    """Load every `data/*.json` file into a `Catalog`.

    Behavior:
        Reads devices, plans, add-ons, trade-in curves, promotions, customers and messages.
        Results are cached per directory.
    Exceptions:
        OSError: A data file cannot be read.
        json.JSONDecodeError: A data file is not valid JSON.
    Returns:
        The loaded catalog.
    Parameters:
        data_dir: Directory holding the JSON files.
    """
    addons = _read(data_dir / "addons.json")
    tradein = _read(data_dir / "tradein.json")
    return Catalog(
        devices={d["id"]: d for d in _read(data_dir / "devices.json")["devices"]},
        plans={p["id"]: p for p in _read(data_dir / "plans.json")["plans"]},
        addons={a["id"]: a for a in addons["addons"]},
        streaming={s["id"]: s for s in addons["streaming_services"]},
        curves={c["device_id"]: c for c in tradein["curves"]},
        promotions=tradein["promotions"],
        customers={c["id"]: c for c in _read(data_dir / "customers.json")["customers"]},
        messages=_read(data_dir / "messages.json"),
    )


class NotFound(LookupError):
    """An id in the request does not exist in the synthetic data."""


def customer_and_line(cat: Catalog, customer_id: str, line_id: str | None = None) -> tuple[dict, dict | None]:
    """Look up a customer and, optionally, one of its lines.

    Exceptions:
        NotFound: The customer or the line does not exist.
    Returns:
        The customer and the line (`None` when `line_id` is not given).
    Parameters:
        cat: Loaded catalog.
        customer_id: Customer id such as `cust-chen`.
        line_id: Line id such as `chen-maya`.
    """
    customer = cat.customers.get(customer_id)
    if customer is None:
        raise NotFound(f"unknown customer {customer_id}")
    if line_id is None:
        return customer, None
    for line in customer["lines"]:
        if line["id"] == line_id:
            return customer, line
    raise NotFound(f"unknown line {line_id} for {customer_id}")


def device(cat: Catalog, device_id: str) -> dict:
    """Look up a device by id.

    Exceptions:
        NotFound: The device does not exist.
    Returns:
        The device record.
    Parameters:
        cat: Loaded catalog.
        device_id: Device id such as `kestrel-5`.
    """
    found = cat.devices.get(device_id)
    if found is None:
        raise NotFound(f"unknown device {device_id}")
    return found


def parse_date(text: str) -> date:
    return date.fromisoformat(text)


def month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def months_between(start: date, end: date) -> int:
    """Count whole months from `start` to `end` (negative when `end` is earlier)."""
    months = month_index(end) - month_index(start)
    return months - 1 if end.day < start.day else months


def add_months(day: date, months: int) -> date:
    index = month_index(day) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, 28))


MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")


def month_label(text: str) -> str:
    """Format `2028-09` or `2028-09-14` as `September 2028`."""
    return f"{MONTH_NAMES[int(text[5:7]) - 1]} {text[:4]}"


def money(amount: float) -> str:
    """Format dollars as `$350`, `$29.17` or `$1,099`."""
    cents = round(amount * 100)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    if cents % 100 == 0:
        return f"{sign}${cents // 100:,}"
    return f"{sign}${cents / 100:,.2f}"


def per_month(amount: float) -> str:
    return f"{money(amount)}/mo"


def gb(value: float) -> str:
    return f"{value:g} GB"


def say(cat: Catalog, key: str, **values: object) -> str:
    """Fill a `messages.json` template.

    Exceptions:
        KeyError: The key or one of its placeholders is missing.
    Returns:
        The formatted copy.
    Parameters:
        cat: Loaded catalog.
        key: Template key, e.g. `upgrade.verdict.replace_battery`.
        values: Placeholder values, already formatted.
    """
    return cat.messages[key].format(**values)


def reason(text: str, signal: str, value: object) -> dict:
    """Build one explained reason: the copy, the field it used, and that field's value."""
    return {"text": text, "signal": signal, "value": value}


def image_url(public_base: str, relative: str) -> str:
    """Prefix a data-relative image path with the browser-visible base, e.g. `/connectors/tmobile`."""
    return f"{public_base.rstrip('/')}/{relative.lstrip('/')}"


def usage_summary(line: dict) -> dict:
    """Average and peak data, hotspot and international days over the line's 6 months."""
    rows = line["usage"]
    data = [r["data_gb"] for r in rows]
    hotspot = [r["hotspot_gb"] for r in rows]
    intl = [r["intl_days"] for r in rows]
    return {
        "data_gb_avg": round(sum(data) / len(data), 1),
        "data_gb_peak": max(data),
        "hotspot_gb_avg": round(sum(hotspot) / len(hotspot), 1),
        "hotspot_gb_peak": max(hotspot),
        "intl_days_total": sum(intl),
    }
