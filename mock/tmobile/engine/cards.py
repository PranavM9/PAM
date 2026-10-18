"""Builders for `pam_cards` items in the shape of the CHG-0027 `ConnectorCard` model."""

from __future__ import annotations

from .common import BADGE, image_url, money, per_month


def _card(kind: str, title: str, **fields: object) -> dict:
    """Return a card dict with the synthetic badge first and empty optional fields dropped.

    Behavior:
        `connector_id` is never set: PAM fills it in. Extra badges follow `BADGE`.
    Returns:
        A dict that validates as `ConnectorCard`.
    Parameters:
        kind: Card kind (`product`, `plan`, `verdict`, `comparison`, `chart`, `notice`).
        title: Plain ASCII title.
        fields: Any other `ConnectorCard` field.
    """
    badges = [BADGE, *fields.pop("badges", [])]
    card: dict = {"kind": kind, "title": title, "badges": badges}
    for key, value in fields.items():
        if value is not None and value != []:
            card[key] = value
    return card


def price(amount: float, period: str = "month", was: float | None = None, note: str | None = None) -> dict:
    out: dict = {"amount": round(float(amount), 2), "period": period}
    if was is not None:
        out["was"] = round(float(was), 2)
    if note:
        out["note"] = note
    return out


def device_card(dev: dict, public_base: str, *, subtitle: str | None = None, card_price: dict | None = None,
                reasons: list[str] | None = None, badges: list[str] | None = None) -> dict:
    """A `product` card for a device, priced at its base storage over 24 months by default."""
    base = dev["storage"][0]
    colour = dev["colours"][0]
    return _card(
        "product", dev["name"],
        subtitle=subtitle or f"{dev['brand']} {dev['form_factor']}, {base['gb']} GB",
        image_url=image_url(public_base, colour["image"]),
        image_alt=f"{dev['name']} in {colour['name']}",
        badges=badges or [],
        price=card_price or price(base["monthly_24"], "month",
                                  note=f"{money(base['full_price'])} full price, 24 months"),
        fields=[
            {"label": "Battery", "value": f"{dev['battery_mah']} mAh"},
            {"label": "Camera", "value": dev["camera"]},
            {"label": "Screen", "value": dev["screen"]},
            {"label": "Colours", "value": ", ".join(c["name"] for c in dev["colours"])},
            {"label": "Rating", "value": f"{dev['rating']} of 5"},
        ],
        reasons=reasons if reasons is not None else list(dev["highlights"]),
    )


def plan_card(plan: dict, lines: int, public_base: str) -> dict:
    """A `plan` card priced per line for `lines` lines, with autopay applied."""
    each = plan["price_per_line"][lines - 1] - plan["autopay_discount"]
    data = "Unlimited" if plan["premium_data_gb"] is None else f"{plan['premium_data_gb']} GB"
    perks = ", ".join(p.capitalize() for p in plan["streaming_perks"]) or "None"
    return _card(
        "plan", plan["name"], subtitle=plan["tagline"],
        image_url=image_url(public_base, plan["image"]), image_alt=f"{plan['name']} plan tile",
        price=price(each, "month", note=f"per line with {lines} line{'s' if lines > 1 else ''} and autopay"),
        fields=[
            {"label": "Premium data", "value": data},
            {"label": "Hotspot", "value": f"{plan['hotspot_gb']} GB"},
            {"label": "Streaming", "value": perks},
            {"label": "International", "value": "Included" if plan["international"] else "Travel pass"},
            {"label": "Total", "value": per_month(each * lines)},
            {"label": "Who can get it", "value": plan["eligibility"]},
        ],
    )


def addon_card(addon: dict, public_base: str, why: str) -> dict:
    """A `product` card for an add-on with the rule's reason."""
    p = addon["price"]
    return _card(
        "product", addon["name"],
        image_url=image_url(public_base, addon["image"]), image_alt=f"{addon['name']} icon",
        price=price(p["amount"], p["period"], note=p.get("note")),
        reasons=[why],
    )


def verdict_card(title: str, *, subtitle: str | None = None, tone: str = "positive", card_price: dict | None = None,
                 fields: list[dict] | None = None, reasons: list[str] | None = None) -> dict:
    return _card("verdict", title, subtitle=subtitle, tone=tone, price=card_price, fields=fields or [],
                 reasons=reasons or [])


def comparison_card(title: str, columns: list[str], rows: list[list[str]], *, subtitle: str | None = None,
                    image: str | None = None, image_alt: str | None = None,
                    fields: list[dict] | None = None, reasons: list[str] | None = None) -> dict:
    return _card("comparison", title, subtitle=subtitle, image_url=image, image_alt=image_alt,
                 columns=columns, rows=rows, fields=fields or [], reasons=reasons or [])


def chart_card(title: str, series_label: str, points: list[list[float]], *, subtitle: str | None = None,
               x_label: str = "Months from today", y_label: str = "Trade-in value (USD)",
               marker_x: float | None = 0, reasons: list[str] | None = None) -> dict:
    chart = {"kind": "line", "x_label": x_label, "y_label": y_label,
             "series": [{"label": series_label, "points": points}]}
    if marker_x is not None:
        chart["marker_x"] = marker_x
    return _card("chart", title, subtitle=subtitle, chart=chart, reasons=reasons or [])


def notice_card(title: str, text: str, tone: str = "positive") -> dict:
    return _card("notice", title, tone=tone, reasons=[text])
