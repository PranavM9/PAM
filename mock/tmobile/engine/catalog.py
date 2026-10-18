"""Catalog, trade-in and household lookups: the read-only endpoints of the mock."""

from __future__ import annotations

import re
from datetime import date

from . import cards
from .common import (Catalog, NotFound, add_months, customer_and_line, device, gb, image_url, money, month_index,
                     month_label, months_between, parse_date, per_month, reason, say, usage_summary)

FORM_FACTORS = ("budget", "mid", "flagship", "foldable")
NEED_WORDS = {"camera": "camera", "photo": "camera", "photos": "camera", "battery": "battery",
              "storage": "storage", "small": "size", "compact": "size", "size": "size"}
MAX_CARDS = 6


def tradein_value(cat: Catalog, device_id: str, when: date) -> int:
    """Trade-in value of a device in the month of `when`.

    Behavior:
        Reads the device's 36-month curve. Months before the curve use its first value and months
        after it use its last value.
    Exceptions:
        NotFound: The device has no curve.
    Returns:
        Whole dollars.
    Parameters:
        cat: Loaded catalog.
        device_id: Device id.
        when: Any day in the wanted month.
    """
    curve = cat.curves.get(device_id)
    if curve is None:
        raise NotFound(f"no trade-in curve for {device_id}")
    start = month_index(parse_date(curve["start_month"] + "-01"))
    k = min(max(month_index(when) - start, 0), len(curve["values"]) - 1)
    return curve["values"][k]


def tradein_points(cat: Catalog, device_id: str, today: date, months_ahead: int) -> list[list[float]]:
    """Chart points `[months_from_today, value]` from up to 12 months back to `months_ahead`."""
    curve = cat.curves[device_id]
    start = month_index(parse_date(curve["start_month"] + "-01"))
    now = month_index(today)
    first = max(start - now, -12)
    last = min(start + len(curve["values"]) - 1 - now, months_ahead)
    return [[float(x), float(curve["values"][now + x - start])] for x in range(first, last + 1)]


def best_promotion(cat: Catalog, target_id: str, traded: dict | None, traded_age: int, when: date) -> dict | None:
    """The largest promotion for `target_id` that is active on `when` for this trade-in, ties by id."""
    if traded is None:
        return None
    found = [p for p in cat.promotions
             if target_id in p["device_ids"] and traded_age >= p["min_tradein_age_months"]
             and parse_date(p["start_date"]) <= when <= parse_date(p["end_date"])]
    found.sort(key=lambda p: (-p["credit"], p["id"]))
    return found[0] if found else None


def run_tradein(cat: Catalog, today: date, public_base: str, device_id: str, months_ahead: int = 12):
    """Trade-in value now, at `months_ahead`, and the curve as a chart card.

    Exceptions:
        NotFound: Unknown device.
        ValueError: `months_ahead` is outside 0 to 24.
    Returns:
        `(data, reasons, cards)`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        device_id: Device to value.
        months_ahead: Months of future curve to show.
    """
    if not 0 <= months_ahead <= 24:
        raise ValueError("months_ahead must be between 0 and 24")
    dev = device(cat, device_id)
    now = tradein_value(cat, device_id, today)
    later = tradein_value(cat, device_id, add_months(today, months_ahead))
    points = tradein_points(cat, device_id, today, months_ahead)
    promos = [{"id": p["id"], "title": p["title"], "credit": p["credit"], "device_ids": p["device_ids"],
               "start_date": p["start_date"], "end_date": p["end_date"], "notice": say(cat, "promo." + p["id"])}
              for p in cat.promotions if parse_date(p["end_date"]) >= today]
    data = {"device_id": device_id, "device": dev["name"], "value_now": now, "months_ahead": months_ahead,
            "value_later": later, "curve": points, "promotions": promos}
    text = say(cat, "tradein.summary", device=dev["name"], now=money(now), months=months_ahead, later=money(later))
    reasons = [reason(text, "tradein.curve", {"now": now, "later": later, "months_ahead": months_ahead})]
    if dev.get("successor_launch") and parse_date(dev["successor_launch"]) > today:
        reasons.append(reason(say(cat, "tradein.successor", date=month_label(dev["successor_launch"])),
                              "device.successor_launch", dev["successor_launch"]))
    chart = cards.chart_card(f"{dev['name']} trade-in value", dev["name"], points,
                             subtitle=f"{money(now)} today, {money(later)} in {months_ahead} months",
                             reasons=[text])
    return data, reasons, [chart]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def run_search(cat: Catalog, today: date, public_base: str, query: str | None = None,
               max_monthly: float | None = None, form_factor: str | None = None, limit: int = 3):
    """Rank current devices for a free-text query, within an optional price and form factor.

    Behavior:
        Only devices on sale are searched. Score = query words found in the device text, plus the
        device's 1-5 score for each need word in the query (camera, battery, storage, small).
        Ranked by score, then rating, then id. `limit` is clamped to 1-6 (PAM keeps 6 cards).
    Exceptions:
        ValueError: `form_factor` is not a known form factor.
    Returns:
        `(data, reasons, cards)`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        query: Free text such as "camera" or "aurora fold".
        max_monthly: Highest 24-month monthly price for the base storage.
        form_factor: `budget`, `mid`, `flagship` or `foldable`.
        limit: Number of devices to return.
    """
    if form_factor is not None and form_factor not in FORM_FACTORS:
        raise ValueError(f"form_factor must be one of {', '.join(FORM_FACTORS)}")
    limit = min(max(int(limit), 1), MAX_CARDS)
    words = _tokens(query or "")
    ranked = []
    for dev in cat.devices.values():
        if dev["status"] != "current":
            continue
        monthly = dev["storage"][0]["monthly_24"]
        if max_monthly is not None and monthly > max_monthly:
            continue
        if form_factor is not None and dev["form_factor"] != form_factor:
            continue
        haystack = set(_tokens(" ".join([dev["name"], dev["form_factor"], dev["camera"], dev["screen"],
                                         *dev["highlights"], *(c["name"] for c in dev["colours"])])))
        score = sum(1 for w in words if w in haystack)
        score += sum(dev["scores"][NEED_WORDS[w]] for w in words if w in NEED_WORDS)
        if words and score == 0:
            continue
        ranked.append((-score, -dev["rating"], dev["id"], dev))
    ranked.sort(key=lambda r: r[:3])
    found = [r[3] for r in ranked[:limit]]
    data = {"query": query, "count": len(found), "devices": [
        {"id": d["id"], "name": d["name"], "form_factor": d["form_factor"],
         "monthly_24": d["storage"][0]["monthly_24"], "full_price": d["storage"][0]["full_price"],
         "battery_mah": d["battery_mah"], "camera": d["camera"], "rating": d["rating"],
         "colours": [c["name"] for c in d["colours"]], "highlights": d["highlights"]} for d in found]}
    reasons = []
    if words:
        reasons.append(reason(say(cat, "search.ranked", query=query.strip()), "request.query", query))
    if max_monthly is not None:
        reasons.append(reason(say(cat, "search.budget", budget=per_month(max_monthly)),
                              "request.max_monthly", max_monthly))
    if form_factor is not None:
        reasons.append(reason(say(cat, "search.form_factor", form_factor=form_factor),
                              "request.form_factor", form_factor))
    if not found:
        reasons.append(reason(say(cat, "search.none"), "catalog.devices", 0))
        return data, reasons, [cards.notice_card("No matching phones", say(cat, "search.none"), tone="neutral")]
    return data, reasons, [cards.device_card(d, public_base) for d in found]


def run_plans(cat: Catalog, today: date, public_base: str, lines: int = 1):
    """Price every plan for a line count, with autopay applied.

    Exceptions:
        ValueError: `lines` is outside 1 to 5.
    Returns:
        `(data, reasons, cards)`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        lines: Number of lines on the account.
    """
    if not 1 <= lines <= 5:
        raise ValueError("lines must be between 1 and 5")
    rows = []
    for plan in cat.plans.values():
        each = plan["price_per_line"][lines - 1] - plan["autopay_discount"]
        rows.append({"id": plan["id"], "name": plan["name"], "per_line": each, "total": each * lines,
                     "premium_data_gb": plan["premium_data_gb"], "hotspot_gb": plan["hotspot_gb"],
                     "streaming_perks": plan["streaming_perks"], "international": plan["international"],
                     "student_only": plan["student_only"]})
    reasons = [reason(say(cat, "plans.priced", lines=lines), "request.lines", lines)]
    return {"lines": lines, "plans": rows}, reasons, [cards.plan_card(p, lines, public_base) for p in cat.plans.values()]


def run_household(cat: Catalog, today: date, public_base: str, customer_id: str):
    """Summarize an account: lines, devices, plans, usage, bill trend and support contacts.

    Exceptions:
        NotFound: Unknown customer.
    Returns:
        `(data, reasons, cards)`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        customer_id: Customer id.
    """
    customer, _ = customer_and_line(cat, customer_id)
    lines, rows, reasons = [], [], []
    for line in customer["lines"]:
        dev = cat.devices[line["device_id"]]
        plan = cat.plans[line["plan_id"]]
        use = usage_summary(line)
        age = months_between(parse_date(line["device_purchase_date"]), today)
        lines.append({
            "id": line["id"], "name": line["person"]["first_name"], "age_band": line["person"]["age_band"],
            "student": line["person"]["student"], "device_id": dev["id"], "device": dev["name"],
            "device_age_months": age, "battery_health": line["battery_health"], "plan_id": plan["id"],
            "financing_months_left": line["financing"]["months_left"], "usage": use,
            "support_contacts": [{"date": c["date"], "kind": c["kind"], "summary": say(cat, c["message"])}
                                 for c in line["support_contacts"]],
        })
        rows.append([line["person"]["first_name"], dev["name"], plan["name"],
                     gb(use["data_gb_avg"]), gb(use["hotspot_gb_avg"])])
        if line["battery_health"] < 80:
            reasons.append(reason(say(cat, "household.battery_low", name=line["person"]["first_name"],
                                      battery=line["battery_health"]),
                                  "line.device.battery_health", line["battery_health"]))
    history = customer["bill_history"]
    first, last = history[0]["amount"], history[-1]["amount"]
    if last > first:
        reasons.append(reason(say(cat, "household.bill_up", before=money(first), after=money(last)),
                              "household.bill_history", [h["amount"] for h in history]))
    if customer.get("promo_credit"):
        reasons.append(reason(say(cat, customer["promo_credit"]["message"],
                                  credit=per_month(customer["promo_credit"]["monthly"])),
                              "household.promo_credit", customer["promo_credit"]["ended"]))
    contacts = [c for line in customer["lines"] for c in line["support_contacts"]]
    recent = [c for c in contacts if 0 <= (today - parse_date(c["date"])).days <= 60]
    if recent:
        reasons.append(reason(say(cat, "household.contacts", count=len(recent)),
                              "customer.support_contacts", len(recent)))
    data = {
        "customer_id": customer["id"], "name": customer["name"], "city": customer["city"],
        "tenure_months": customer["tenure_months"], "autopay": customer["autopay"],
        "home_internet": customer["home_internet"],
        "services_elsewhere": {cat.streaming[s]["name"]: cat.streaming[s]["monthly"]
                               for s in customer["services_elsewhere"]},
        "bill_history": {h["month"]: h["amount"] for h in history}, "lines": lines,
    }
    owner = next(l for l in customer["lines"] if l["id"] == customer["owner_line_id"])
    card = cards.comparison_card(
        customer["name"], ["Line", "Phone", "Plan", "Data per month", "Hotspot per month"], rows,
        subtitle=f"{len(lines)} lines, bill {per_month(last)}",
        image=image_url(public_base, owner["person"]["avatar"]),
        image_alt=f"{owner['person']['first_name']}, account owner",
        fields=[{"label": "Bill now", "value": per_month(last)},
                {"label": "Bill in " + history[0]["month"], "value": per_month(first)},
                {"label": "Customer for", "value": f"{customer['tenure_months']} months"}],
        reasons=[r["text"] for r in reasons],
    )
    return data, reasons, [card]
