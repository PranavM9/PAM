"""Household Mix Optimizer: the cheapest valid plan per line, bundles and home internet."""

from __future__ import annotations

from datetime import date
from itertools import product

from . import cards
from .common import Catalog, customer_and_line, gb, image_url, money, per_month, reason, say, usage_summary

KEEP_THRESHOLD = 5.0     # dollars per month: below this the verdict is "Keep your plan"


def covers(plan: dict, line: dict) -> bool:
    """Whether a plan covers a line's 6-month peak data, peak hotspot and travel, and allows the person.

    Behavior:
        `premium_data_gb: null` is unlimited. Any international day in 6 months needs a plan with
        international included. A student-only plan needs `person.student`.
    Returns:
        `True` when the plan is valid for the line.
    Parameters:
        plan: A plan record.
        line: A customer line.
    """
    use = usage_summary(line)
    if plan["student_only"] and not line["person"]["student"]:
        return False
    if plan["premium_data_gb"] is not None and use["data_gb_peak"] > plan["premium_data_gb"]:
        return False
    if use["hotspot_gb_peak"] > plan["hotspot_gb"]:
        return False
    return not (use["intl_days_total"] > 0 and not plan["international"])


def config_cost(cat: Catalog, customer: dict, plan_ids: tuple[str, ...], bundles: tuple[str, ...],
                carrier_internet: bool | None, paying_now: bool = False) -> dict:
    """Monthly cost of one configuration, itemized.

    Behavior:
        Each line pays its plan's price for the account's line count, minus autopay when the
        account has autopay. Streaming services the household pays for elsewhere are added unless
        a plan perk on any line or a chosen bundle covers them. Home internet is counted only when
        `carrier_internet` is not `None`: `True` prices the carrier's ($35 with a Plus or Max line,
        else $50), `False` keeps what the household pays today. With `paying_now`, every service
        paid elsewhere is counted, because the household pays it today even when a perk covers it.
    Returns:
        `{"lines", "autopay", "bundles", "services", "home_internet", "total"}` in dollars.
    Parameters:
        cat: Loaded catalog.
        customer: The household.
        plan_ids: One plan id per line, in line order.
        bundles: Chosen streaming bundle ids.
        carrier_internet: Carrier home internet on (`True`), current provider (`False`), or not counted.
        paying_now: Price the household's current bill rather than a proposed configuration.
    """
    n = len(plan_ids)
    lines = sum(cat.plans[p]["price_per_line"][n - 1] for p in plan_ids)
    autopay = sum(cat.plans[p]["autopay_discount"] for p in plan_ids) if customer["autopay"] else 0
    covered = {s for p in plan_ids for s in cat.plans[p]["streaming_perks"]}
    covered |= {s for b in bundles for s in cat.addons[b]["covers"]}
    services = sum(cat.streaming[s]["monthly"] for s in customer["services_elsewhere"]
                   if paying_now or s not in covered)
    bundle_cost = sum(cat.addons[b]["price"]["amount"] for b in bundles)
    internet = 0.0
    if carrier_internet is not None and customer.get("home_internet"):
        if carrier_internet:
            hi = cat.addons["home-internet"]
            discounted = any(p in ("plus", "max") for p in plan_ids)
            internet = float(hi["discounted_price"] if discounted else hi["price"]["amount"])
        else:
            internet = float(customer["home_internet"]["monthly"])
    total = lines - autopay + services + bundle_cost + internet
    return {"lines": float(lines), "autopay": float(autopay), "bundles": float(bundle_cost),
            "services": round(services, 2), "home_internet": internet, "total": round(total, 2)}


def _current_bundles(cat: Catalog, customer: dict) -> tuple[str, ...]:
    return tuple(a for a in customer["account_addons"] if cat.addons[a]["kind"] == "bundle")


def optimize(cat: Catalog, customer: dict, include_home_internet: bool = False) -> dict:
    """Enumerate every plan per line with every bundle choice and return the cheapest valid one.

    Behavior:
        Tries all `len(plans) ** lines` plan combinations (at most 1 024) times every subset of the
        streaming bundles times the home internet choice (two options when
        `include_home_internet` and the household has home internet, else one). A combination is
        valid when every line's plan `covers` it. Ties break by fewest changed lines, then plan
        ids, then bundle ids. Savings under `KEEP_THRESHOLD` give the verdict `keep`.
    Returns:
        `{"current", "best", "savings_monthly", "savings_yearly", "verdict", "combinations_checked",
        "valid_combinations", "current_valid"}`; `current` and `best` hold `plans`, `bundles`,
        `carrier_internet` and the `config_cost` breakdown.
    Parameters:
        cat: Loaded catalog.
        customer: The household (a `customers.json` record or the same shape).
        include_home_internet: Also consider switching home internet to the carrier.
    """
    lines = customer["lines"]
    plan_ids = sorted(cat.plans)
    bundle_ids = sorted(a["id"] for a in cat.addons.values() if a["kind"] == "bundle")
    bundle_sets = [tuple(b for b, on in zip(bundle_ids, mask) if on)
                   for mask in product((False, True), repeat=len(bundle_ids))]
    has_internet = bool(customer.get("home_internet"))
    on_carrier = "home-internet" in customer["account_addons"]
    internet_options: list[bool | None] = [None]
    if include_home_internet and has_internet:
        internet_options = [on_carrier, not on_carrier]

    current_plans = tuple(l["plan_id"] for l in lines)
    current_bundles = _current_bundles(cat, customer)
    current_internet = on_carrier if include_home_internet and has_internet else None
    current = {"plans": list(current_plans), "bundles": list(current_bundles), "carrier_internet": current_internet,
               "cost": config_cost(cat, customer, current_plans, current_bundles, current_internet,
                                       paying_now=True)}

    valid_per_line = [{p for p in plan_ids if covers(cat.plans[p], l)} for l in lines]
    checked = valid = 0
    best_key, best = None, None
    for combo in product(plan_ids, repeat=len(lines)):
        ok = all(p in valid_per_line[i] for i, p in enumerate(combo))
        for bundles in bundle_sets:
            for internet in internet_options:
                checked += 1
                if not ok:
                    continue
                valid += 1
                cost = config_cost(cat, customer, combo, bundles, internet)
                changes = sum(a != b for a, b in zip(combo, current_plans))
                changes += bundles != current_bundles
                changes += internet != current_internet
                key = (cost["total"], changes, combo, bundles, internet is True)
                if best_key is None or key < best_key:
                    best_key = key
                    best = {"plans": list(combo), "bundles": list(bundles), "carrier_internet": internet,
                            "cost": cost}
    if best is None:
        best = current
    savings = round(current["cost"]["total"] - best["cost"]["total"], 2)
    return {"current": current, "best": best, "savings_monthly": savings, "savings_yearly": round(savings * 12, 2),
            "verdict": "change" if savings >= KEEP_THRESHOLD else "keep", "combinations_checked": checked,
            "valid_combinations": valid,
            "current_valid": all(p in valid_per_line[i] for i, p in enumerate(current_plans))}


def run_optimize(cat: Catalog, today: date, public_base: str, customer_id: str, include_home_internet: bool = False):
    """Household endpoint: a verdict card, then a current-vs-best comparison card.

    Exceptions:
        NotFound: Unknown customer.
    Returns:
        `(data, reasons, cards)`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        customer_id: Customer id.
        include_home_internet: Also consider carrier home internet.
    """
    customer, _ = customer_and_line(cat, customer_id)
    r = optimize(cat, customer, include_home_internet)
    keep = r["verdict"] == "keep"
    shown = r["current"] if keep else r["best"]
    reasons, line_rows, line_data = [], [], []
    for i, line in enumerate(customer["lines"]):
        name = line["person"]["first_name"]
        use = usage_summary(line)
        now, new = cat.plans[r["current"]["plans"][i]], cat.plans[shown["plans"][i]]
        line_rows.append([name, now["name"], new["name"], gb(use["data_gb_peak"]), gb(use["hotspot_gb_peak"])])
        line_data.append({"line_id": line["id"], "name": name, "current_plan": now["id"], "suggested_plan": new["id"],
                          "data_gb_peak": use["data_gb_peak"], "hotspot_gb_peak": use["hotspot_gb_peak"],
                          "intl_days": use["intl_days_total"]})
        if not covers(now, line):
            reasons.append(reason(say(cat, "household.line_short", name=name, plan=now["name"],
                                      peak=gb(use["data_gb_peak"]), hotspot=gb(use["hotspot_gb_peak"])),
                                  "line.usage.data_gb_peak", use["data_gb_peak"]))
        if new["id"] != now["id"]:
            n = len(customer["lines"])
            reasons.append(reason(say(cat, "household.line_change", name=name, old=now["name"], new=new["name"],
                                      peak=gb(use["data_gb_peak"]), hotspot=gb(use["hotspot_gb_peak"]),
                                      old_price=per_month(now["price_per_line"][n - 1]),
                                      new_price=per_month(new["price_per_line"][n - 1])),
                                  "line.usage.data_gb_peak", use["data_gb_peak"]))
    names = {**{s["id"]: s["name"] for s in cat.streaming.values()}}
    paid = customer["services_elsewhere"]
    if paid:
        perks = {s for p in shown["plans"] for s in cat.plans[p]["streaming_perks"]}
        perks |= {s for b in shown["bundles"] for s in cat.addons[b]["covers"]}
        replaced = [names[s] for s in paid if s in perks]
        if replaced and not keep:
            reasons.append(reason(say(cat, "household.services_replaced", services=" and ".join(replaced)),
                                  "household.services_elsewhere", paid))
    for b in shown["bundles"]:
        if b not in r["current"]["bundles"]:
            reasons.append(reason(say(cat, "household.bundle_added", bundle=cat.addons[b]["name"],
                                      price=per_month(cat.addons[b]["price"]["amount"])),
                                  "household.services_elsewhere", paid))
    if include_home_internet and shown["carrier_internet"] and not r["current"]["carrier_internet"]:
        reasons.append(reason(say(cat, "household.internet_switch", old=per_month(customer["home_internet"]["monthly"]),
                                  new=per_month(shown["cost"]["home_internet"])),
                              "household.home_internet", customer["home_internet"]["monthly"]))
    reasons.append(reason(say(cat, "household.checked", count=f"{r['combinations_checked']:,}",
                              valid=f"{r['valid_combinations']:,}"), "household.lines", len(customer["lines"])))
    if keep:
        reasons.append(reason(say(cat, "household.keep", savings=per_month(max(r["savings_monthly"], 0))),
                              "option.no_change", r["savings_monthly"]))
        title = say(cat, "household.title.keep")
    else:
        reasons.append(reason(say(cat, "household.save", savings=per_month(r["savings_monthly"]),
                                  yearly=money(r["savings_yearly"])), "option.score", r["savings_monthly"]))
        title = say(cat, "household.title.save", savings=per_month(r["savings_monthly"]))
    now_total, new_total = r["current"]["cost"]["total"], shown["cost"]["total"]
    verdict = cards.verdict_card(
        title, subtitle=customer["name"], tone="positive" if not keep else "neutral",
        card_price=cards.price(new_total, "month", was=None if keep else now_total,
                               note="plans, bundles and services, autopay on"),
        fields=[{"label": "Monthly now", "value": per_month(now_total)},
                {"label": "Monthly after", "value": per_month(new_total)},
                {"label": "Saved per year", "value": money(0 if keep else r["savings_yearly"])},
                {"label": "Options checked", "value": f"{r['combinations_checked']:,}"}],
        reasons=[x["text"] for x in reasons],
    )
    owner = next(l for l in customer["lines"] if l["id"] == customer["owner_line_id"])
    comparison = cards.comparison_card(
        "Your plans now and suggested", ["Line", "Now", "Suggested", "Peak data", "Peak hotspot"], line_rows,
        subtitle=f"{per_month(now_total)} now, {per_month(new_total)} suggested",
        image=image_url(public_base, owner["person"]["avatar"]), image_alt=f"{owner['person']['first_name']}",
        fields=[{"label": "Streaming bundles", "value": ", ".join(cat.addons[b]["name"] for b in shown["bundles"])
                 or "None"}],
    )
    data = {"customer_id": customer_id, "verdict": r["verdict"], "verdict_label": title,
            "monthly_now": now_total, "monthly_after": new_total,
            "savings_monthly": 0.0 if keep else r["savings_monthly"],
            "savings_yearly": 0.0 if keep else r["savings_yearly"],
            "best_savings_found": r["savings_monthly"],
            "total_24m_now": round(now_total * 24, 2), "total_24m_after": round(new_total * 24, 2),
            "combinations_checked": r["combinations_checked"], "valid_combinations": r["valid_combinations"],
            "include_home_internet": include_home_internet, "lines": line_data,
            "current": {k: r["current"][k] for k in ("plans", "bundles", "carrier_internet")} | {"cost": r["current"]["cost"]["total"]},
            "best": {k: r["best"][k] for k in ("plans", "bundles", "carrier_internet")} | {"cost": r["best"]["cost"]["total"]}}
    return data, reasons, [verdict, comparison]
