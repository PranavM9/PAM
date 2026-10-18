"""Cart Whisperer: up to 3 add-ons for a line and a device, or "Nothing else needed"."""

from __future__ import annotations

from datetime import date

from . import cards
from .common import Catalog, customer_and_line, device, money, parse_date, per_month, reason, say, usage_summary

MAX_SUGGESTIONS = 3
CASE_WINDOW_DAYS = 90


def _owned(line: dict, addon_id: str) -> list[date]:
    return sorted(parse_date(a["date"]) for a in line["accessories"] if a["addon_id"] == addon_id)


def suggest(cat: Catalog, today: date, customer: dict, line: dict, dev: dict) -> list[dict]:
    """Run every add-on rule in a fixed order and keep the first `MAX_SUGGESTIONS` that pass.

    Behavior:
        Rules, in order: protection (a foldable, a phone of $900 or more, or a past screen repair,
        and no protection yet); case (none bought in the last 90 days); charger (the phone has no
        charger in the box and the line owns none); earbuds (the household streams music and the
        line owns none); watch line (the household has more watches than watch lines); home
        internet (paid elsewhere and the carrier's price is lower); streaming bundles (cheaper than
        the services they replace); travel pass (international days on a plan without travel).
    Returns:
        Suggestions `{"addon_id", "reason"}` where `reason` has `text`, `signal`, `value`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        customer: The household.
        line: The line the cart is for.
        dev: The device in the cart (new or current).
    """
    out: list[dict] = []
    plan = cat.plans[line["plan_id"]]
    lines = customer["lines"]

    def add(addon_id: str, text: str, signal: str, value: object) -> None:
        out.append({"addon_id": addon_id, "reason": reason(text, signal, value)})

    if "protection" not in line["addons"]:
        repairs = [c for c in line["support_contacts"] if c["message"] == "contact.screen_repair"]
        price = dev["storage"][0]["full_price"]
        if dev["form_factor"] == "foldable":
            add("protection", say(cat, "addons.protection_foldable", device=dev["name"]), "device.form_factor",
                dev["form_factor"])
        elif repairs:
            add("protection", say(cat, "addons.protection_repair", date=repairs[-1]["date"]),
                "customer.support_contacts", len(repairs))
        elif price >= 900:
            add("protection", say(cat, "addons.protection_price", device=dev["name"], price=money(price)),
                "device.full_price", price)
    cases = _owned(line, "case")
    if not cases or (today - cases[-1]).days > CASE_WINDOW_DAYS:
        last = cases[-1].isoformat() if cases else None
        add("case", say(cat, "addons.case_old" if cases else "addons.case_none"), "line.accessories.case", last)
    if not dev["charger_in_box"] and not _owned(line, "charger"):
        add("charger", say(cat, "addons.charger", device=dev["name"]), "device.charger_in_box", False)
    music = "tunewave" in customer["services_elsewhere"] or any(
        "tunewave" in cat.plans[l["plan_id"]]["streaming_perks"] for l in lines)
    if music and not _owned(line, "earbuds"):
        add("earbuds", say(cat, "addons.earbuds"), "household.services_elsewhere", "tunewave")
    watch_lines = sum("watch-line" in l["addons"] for l in lines)
    if customer["watches"] > watch_lines:
        add("watch-line", say(cat, "addons.watch", watches=customer["watches"]), "household.watches",
            customer["watches"])
    home = customer.get("home_internet")
    if home and home["provider"] == "elsewhere":
        hi = cat.addons["home-internet"]
        carrier = hi["discounted_price"] if any(l["plan_id"] in ("plus", "max") for l in lines) else hi["price"]["amount"]
        if carrier < home["monthly"]:
            add("home-internet", say(cat, "addons.home_internet", old=per_month(home["monthly"]), new=per_month(carrier)),
                "household.home_internet", home["monthly"])
    perks = {s for l in lines for s in cat.plans[l["plan_id"]]["streaming_perks"]}
    for bundle in sorted((a for a in cat.addons.values() if a["kind"] == "bundle"), key=lambda a: a["id"]):
        if bundle["id"] in customer["account_addons"]:
            continue
        replaced = [s for s in customer["services_elsewhere"] if s in bundle["covers"] and s not in perks]
        paid = sum(cat.streaming[s]["monthly"] for s in replaced)
        if replaced and bundle["price"]["amount"] < paid:
            add(bundle["id"], say(cat, "addons.bundle", bundle=bundle["name"],
                                  services=" and ".join(cat.streaming[s]["name"] for s in replaced),
                                  saving=per_month(paid - bundle["price"]["amount"])),
                "household.services_elsewhere", replaced)
    use = usage_summary(line)
    if use["intl_days_total"] > 0 and not plan["international"]:
        add("travel-pass", say(cat, "addons.travel", days=use["intl_days_total"]), "line.usage.intl_days",
            use["intl_days_total"])
    return out[:MAX_SUGGESTIONS]


def run_addons(cat: Catalog, today: date, public_base: str, customer_id: str, line_id: str, device_id: str):
    """Add-ons endpoint: up to 3 `product` cards, or one `notice` card saying nothing else is needed.

    Exceptions:
        NotFound: Unknown customer, line or device.
    Returns:
        `(data, reasons, cards)`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        customer_id: Customer id.
        line_id: Line id.
        device_id: Device in the cart.
    """
    customer, line = customer_and_line(cat, customer_id, line_id)
    dev = device(cat, device_id)
    found = suggest(cat, today, customer, line, dev)
    reasons = [s["reason"] for s in found]
    data = {"customer_id": customer_id, "line_id": line_id, "device_id": device_id,
            "suggestions": [{"addon_id": s["addon_id"], "name": cat.addons[s["addon_id"]]["name"],
                             "price": cat.addons[s["addon_id"]]["price"], "reason": s["reason"]["text"]}
                            for s in found],
            "verdict": "suggest" if found else "nothing_else_needed"}
    if not found:
        text = say(cat, "addons.nothing", name=line["person"]["first_name"])
        reasons.append(reason(text, "option.no_change", 0))
        return data, reasons, [cards.notice_card(say(cat, "addons.title.nothing"), text)]
    return data, reasons, [cards.addon_card(cat.addons[s["addon_id"]], public_base, s["reason"]["text"])
                           for s in found]
