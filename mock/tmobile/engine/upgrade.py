"""Timekeeper: should this line upgrade now, wait, replace the battery, or change nothing."""

from __future__ import annotations

from datetime import date

from . import cards
from .catalog import best_promotion, tradein_points, tradein_value
from .common import (Catalog, add_months, customer_and_line, money, month_index, month_label, months_between,
                     parse_date, per_month, reason, say)

NEEDS = ("camera", "battery", "storage", "size")
PENALTY = 150.0          # dollars per unmet need, on the 24-month cost scale
BATTERY_THRESHOLD = 80   # percent
WAIT_MONTHS = (3, 6)


def parse_needs(needs: str | list[str] | None) -> list[str]:
    """Parse a comma list such as `battery,camera` into known needs in a fixed order.

    Exceptions:
        ValueError: A need is not one of `camera`, `battery`, `storage`, `size`.
    Returns:
        The needs, deduplicated, in `NEEDS` order.
    Parameters:
        needs: A comma-separated string, a list, or `None`.
    """
    if needs is None:
        return []
    items = needs.split(",") if isinstance(needs, str) else list(needs)
    wanted = {str(n).strip().lower() for n in items if str(n).strip()}
    unknown = sorted(wanted - set(NEEDS))
    if unknown:
        raise ValueError(f"unknown needs: {', '.join(unknown)} (use {', '.join(NEEDS)})")
    return [n for n in NEEDS if n in wanted]


def _join(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _issue_words(issues: list[str]) -> str:
    return _join(["security updates" if i == "updates" else f"a better {i}" if i != "battery" else "battery life"
                  for i in issues])


def current_issues(line: dict, dev: dict, needs: list[str], today: date) -> list[str]:
    """Needs the current phone does not meet, plus implicit ones from the line's signals.

    Behavior:
        A stated need is unmet when the phone scores under 4 of 5 for it (battery also needs
        health of at least 80%). A battery under 80% is an issue even if not stated, and so is a
        phone whose updates have ended (`updates`).
    Returns:
        Issue names in `NEEDS` order, then `updates`.
    Parameters:
        line: The customer line.
        dev: The line's current device.
        needs: Parsed needs from the request.
        today: `MOCK_TODAY`.
    """
    issues = []
    for need in NEEDS:
        if need == "battery":
            weak = line["battery_health"] < BATTERY_THRESHOLD or (need in needs and dev["scores"]["battery"] < 4)
            if weak:
                issues.append(need)
        elif need in needs and dev["scores"][need] < 4:
            issues.append(need)
    if _updates_ended(dev, today):
        issues.append("updates")
    return issues


def _updates_ended(dev: dict, today: date) -> bool:
    return month_index(parse_date(dev["updates_until"] + "-01")) < month_index(today)


def _resolves(dev: dict, issue: str) -> bool:
    return issue == "updates" or dev["scores"][issue] >= 4


def rank_devices(cat: Catalog, line: dict, issues: list[str], when: date, budget: float | None) -> list[dict]:
    """Price every current device for this line on a given day, net of trade-in and promotion.

    Behavior:
        Net cost = base storage full price - trade-in value of the line's phone on `when` - the
        best active promotion. Devices whose net monthly price (net / 24) is over `budget` are left
        out. Score = net cost + `PENALTY` per issue the device does not resolve. Ranked by score,
        then id.
    Returns:
        Candidate dicts (`device_id`, `net`, `monthly`, `tradein`, `promotion`, `unmet`, `score`).
    Parameters:
        cat: Loaded catalog.
        line: The customer line.
        issues: Issues from `current_issues`.
        when: Purchase day.
        budget: Highest net monthly price, or `None`.
    """
    own = cat.devices[line["device_id"]]
    traded = own if line["tradein_eligible"] else None
    tv = tradein_value(cat, own["id"], when) if traded else 0
    age = months_between(parse_date(line["device_purchase_date"]), when)
    out = []
    for dev in sorted(cat.devices.values(), key=lambda d: d["id"]):
        if dev["status"] != "current":
            continue
        promo = best_promotion(cat, dev["id"], traded, age, when)
        credit = promo["credit"] if promo else 0
        net = max(dev["storage"][0]["full_price"] - tv - credit, 0)
        monthly = round(net / 24, 2)
        if budget is not None and monthly > budget:
            continue
        unmet = [i for i in issues if not _resolves(dev, i)]
        out.append({"device_id": dev["id"], "device": dev["name"], "full_price": dev["storage"][0]["full_price"],
                    "tradein": tv, "promotion": promo["id"] if promo else None, "promotion_credit": credit,
                    "net": float(net), "monthly": monthly, "unmet": unmet,
                    "score": round(net + PENALTY * len(unmet), 2)})
    out.sort(key=lambda c: (c["score"], c["device_id"]))
    return out


def _installment(line: dict) -> float:
    fin = line["financing"]
    return round(fin["balance"] / fin["months_left"], 2) if fin["months_left"] else 0.0


def _installment_at(line: dict, months: int) -> float:
    return _installment(line) if line["financing"]["months_left"] > months else 0.0


def _purchase_text(cat: Catalog, key: str, cand: dict, months: int | None = None) -> str:
    promo = next((p for p in cat.promotions if p["id"] == cand["promotion"]), None)
    values = {"device": cand["device"], "net": money(cand["net"]), "monthly": per_month(cand["monthly"]),
              "tradein": money(cand["tradein"]), "months": months}
    if promo:
        return say(cat, key + "_promo", promo=promo["title"], credit=money(promo["credit"]), **values)
    return say(cat, key, **values)


def recommend(cat: Catalog, today: date, customer_id: str, line_id: str, monthly_budget: float | None = None,
              needs: str | list[str] | None = None) -> dict:
    """Score every Timekeeper option for one line and pick the lowest score.

    Behavior:
        Options: `no_change` (always scored), `replace_battery` (battery under 80% and the phone
        still gets updates; price from `addons.json`), `upgrade_now` (best device within budget,
        net of trade-in and promotion) and `wait_3_months` / `wait_6_months` (the same search on
        that future day, using the trade-in curve and promotion dates). Score = 24-month net cost
        + `PENALTY` per issue left unmet; waiting adds `PENALTY` * months / 12 per current issue
        for the months spent waiting. Ties break by option id. Unavailable options are listed
        with `eligible: false` and no score.
    Exceptions:
        NotFound: Unknown customer or line.
        ValueError: Unknown need or a negative budget.
    Returns:
        `{"line", "issues", "options", "winner", "candidates", "reasons"}`.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        customer_id: Customer id.
        line_id: Line id.
        monthly_budget: Highest net monthly price for a new phone.
        needs: Comma list of `camera`, `battery`, `storage`, `size`.
    """
    if monthly_budget is not None and monthly_budget < 0:
        raise ValueError("monthly_budget must not be negative")
    customer, line = customer_and_line(cat, customer_id, line_id)
    wanted = parse_needs(needs)
    own = cat.devices[line["device_id"]]
    issues = current_issues(line, own, wanted, today)
    age = months_between(parse_date(line["device_purchase_date"]), today)
    now_monthly = _installment(line)
    options: list[dict] = []

    def option(oid: str, label: str, eligible: bool, why: list[dict], cost: float = 0.0, unmet: list[str] = (),
               wait_penalty: float = 0.0, monthly_after: float | None = None, once: float = 0.0,
               device_id: str | None = None) -> None:
        score = round(cost + PENALTY * len(unmet) + wait_penalty, 2) if eligible else None
        options.append({
            "id": oid, "label": label, "eligible": eligible, "score": score, "device_id": device_id,
            "unmet": list(unmet), "penalty": round(PENALTY * len(unmet) + wait_penalty, 2) if eligible else None,
            "money": {"monthly_now": now_monthly,
                      "monthly_after": now_monthly if monthly_after is None else round(monthly_after, 2),
                      "once": once, "total_24m": round(cost, 2)} if eligible else None,
            "reasons": why,
        })

    # no_change
    why = [reason(say(cat, "upgrade.option.no_change_unmet", unmet=_issue_words(issues)) if issues
                  else say(cat, "upgrade.option.no_change_met"), "option.no_change", 0)]
    option("no_change", say(cat, "upgrade.title.no_change"), True, why, 0.0, issues)

    # replace_battery
    battery = cat.addons["battery-service"]["price"]["amount"]
    if line["battery_health"] >= BATTERY_THRESHOLD:
        option("replace_battery", say(cat, "upgrade.title.replace_battery"), False,
               [reason(say(cat, "upgrade.option.battery_not_needed", battery=line["battery_health"]),
                       "line.device.battery_health", line["battery_health"])])
    elif _updates_ended(own, today):
        option("replace_battery", say(cat, "upgrade.title.replace_battery"), False,
               [reason(say(cat, "upgrade.option.battery_no_updates", until=month_label(own["updates_until"])),
                       "line.device.updates_until", own["updates_until"])])
    else:
        left = [i for i in issues if i != "battery"]
        why = [reason(say(cat, "upgrade.option.replace_battery", price=money(battery)),
                      "line.device.battery_health", line["battery_health"])]
        if left:
            why.append(reason(say(cat, "upgrade.option.leaves_unmet", unmet=_issue_words(left),
                                  penalty=money(PENALTY * len(left))), "request.needs", left))
        option("replace_battery", say(cat, "upgrade.title.replace_battery"), True, why, float(battery), left,
               once=float(battery))

    # upgrade_now and wait_<n>_months
    candidates_now = rank_devices(cat, line, issues, today, monthly_budget)
    for months in (0, *WAIT_MONTHS):
        when = add_months(today, months)
        ranked = candidates_now if months == 0 else rank_devices(cat, line, issues, when, monthly_budget)
        oid = "upgrade_now" if months == 0 else f"wait_{months}_months"
        if not ranked:
            label = say(cat, "upgrade.title.upgrade_any") if months == 0 else say(cat, "upgrade.title.wait",
                                                                                  months=months)
            option(oid, label, False, [reason(say(cat, "upgrade.option.none_in_budget",
                                                  budget=per_month(monthly_budget or 0)),
                                              "request.monthly_budget", monthly_budget)])
            continue
        best = ranked[0]
        if months == 0:
            label = say(cat, "upgrade.title.upgrade_now", device=best["device"])
            why = [reason(_purchase_text(cat, "upgrade.option.upgrade_now", best), "tradein.curve",
                          {"device_id": own["id"], "value": best["tradein"], "month": 0})]
            wait_penalty = 0.0
        else:
            label = say(cat, "upgrade.title.wait", months=months)
            why = [reason(_purchase_text(cat, "upgrade.option.wait", best, months), "tradein.curve",
                          {"device_id": own["id"], "value": best["tradein"], "month": months})]
            wait_penalty = PENALTY * months / 12 * len(issues)
            if issues:
                why.append(reason(say(cat, "upgrade.option.wait_cost", months=months, unmet=_issue_words(issues),
                                      penalty=money(wait_penalty)), "option.wait_penalty", wait_penalty))
        if best["unmet"]:
            why.append(reason(say(cat, "upgrade.option.leaves_unmet", unmet=_issue_words(best["unmet"]),
                                  penalty=money(PENALTY * len(best["unmet"]))), "request.needs", best["unmet"]))
        option(oid, label, True, why, best["net"], best["unmet"], wait_penalty,
               monthly_after=_installment_at(line, months) + best["monthly"], device_id=best["device_id"])

    scored = sorted((o for o in options if o["eligible"]), key=lambda o: (o["score"], o["id"]))
    winner = scored[0]
    return {"customer": customer, "line": line, "device": own, "age_months": age, "needs": wanted,
            "issues": issues, "options": options, "winner": winner, "candidates": candidates_now[:2],
            "budget": monthly_budget}


def run_upgrade(cat: Catalog, today: date, public_base: str, customer_id: str, line_id: str,
                monthly_budget: float | None = None, needs: str | list[str] | None = None):
    """Timekeeper endpoint: the verdict, the reasons, a trade-in chart and up to 2 phones.

    Exceptions:
        NotFound: Unknown customer or line.
        ValueError: Bad needs or budget.
    Returns:
        `(data, reasons, cards)`: cards are a `verdict`, a `chart`, then up to 2 `product` cards.
    Parameters:
        cat: Loaded catalog.
        today: `MOCK_TODAY`.
        public_base: Image URL prefix.
        customer_id: Customer id.
        line_id: Line id.
        monthly_budget: Highest net monthly price for a new phone.
        needs: Comma list of needs.
    """
    r = recommend(cat, today, customer_id, line_id, monthly_budget, needs)
    line, own, winner = r["line"], r["device"], r["winner"]
    name = line["person"]["first_name"]
    now_value = tradein_value(cat, own["id"], today)
    later_value = tradein_value(cat, own["id"], add_months(today, 3))

    reasons = [
        reason(say(cat, "upgrade.battery_low" if line["battery_health"] < BATTERY_THRESHOLD else "upgrade.battery_ok",
                   battery=line["battery_health"]), "line.device.battery_health", line["battery_health"]),
        reason(say(cat, "upgrade.age", device=own["name"], months=r["age_months"]),
               "line.device.age_months", r["age_months"]),
        reason(say(cat, "upgrade.updates_ended" if "updates" in r["issues"] else "upgrade.updates_ok",
                   until=month_label(own["updates_until"])), "line.device.updates_until", own["updates_until"]),
        reason(say(cat, "upgrade.curve", device=own["name"], now=money(now_value), later=money(later_value),
                   drop=money(now_value - later_value)), "tradein.curve",
               {"device_id": own["id"], "now": now_value, "in_3_months": later_value}),
    ]
    if r["budget"] is not None:
        reasons.append(reason(say(cat, "upgrade.budget", budget=per_month(r["budget"])),
                              "request.monthly_budget", r["budget"]))
    if r["needs"]:
        reasons.append(reason(say(cat, "upgrade.needs", needs=_join(r["needs"])), "request.needs", r["needs"]))
    reasons.append(reason(say(cat, "upgrade.penalty", penalty=money(PENALTY)), "option.penalty", PENALTY))
    reasons.extend(winner["reasons"])
    reasons.append(reason(say(cat, "upgrade.won", label=winner["label"], score=money(winner["score"])),
                          "option.score", {winner["id"]: winner["score"]}))
    for o in r["options"]:
        if o is winner:
            continue
        if o["eligible"]:
            text = say(cat, "upgrade.lost", label=o["label"], score=money(o["score"]),
                       gap=money(o["score"] - winner["score"]), winner=winner["label"])
            reasons.append(reason(text, "option.score", {o["id"]: o["score"]}))
        else:
            reasons.append(reason(o["reasons"][0]["text"], o["reasons"][0]["signal"], o["reasons"][0]["value"]))

    m = winner["money"]
    if winner["id"] == "replace_battery":
        card_price = cards.price(m["once"], "once", note="battery replacement, about an hour in store")
    elif winner["device_id"]:
        card_price = cards.price(m["monthly_after"] - m["monthly_now"], "month",
                                 note=f"{money(m['total_24m'])} over 24 months after trade-in")
    else:
        card_price = cards.price(0, "month", note="no new cost")
    verdict = cards.verdict_card(
        winner["label"], subtitle=say(cat, "upgrade.subtitle", name=name),
        tone="positive", card_price=card_price,
        fields=[{"label": "Battery health", "value": f"{line['battery_health']}%"},
                {"label": "Phone age", "value": f"{r['age_months']} months"},
                {"label": "Trade-in today", "value": money(now_value)},
                {"label": "Trade-in in 3 months", "value": money(later_value)},
                {"label": "Paying now", "value": per_month(m["monthly_now"])},
                {"label": "24-month cost", "value": money(m["total_24m"])}],
        reasons=[x["text"] for x in winner["reasons"]] + [
            say(cat, "upgrade.lost", label=o["label"], score=money(o["score"]),
                gap=money(o["score"] - winner["score"]), winner=winner["label"])
            for o in r["options"] if o["eligible"] and o is not winner],
    )
    chart = cards.chart_card(f"{own['name']} trade-in value", own["name"],
                             tradein_points(cat, own["id"], today, 12),
                             subtitle=f"{money(now_value)} today, {money(later_value)} in 3 months",
                             reasons=[reasons[3]["text"]])
    products = []
    for cand in r["candidates"]:
        dev = cat.devices[cand["device_id"]]
        note = f"{money(cand['net'])} over 24 months after a {money(cand['tradein'])} trade-in"
        if cand["promotion_credit"]:
            note += f" and {money(cand['promotion_credit'])} off"
        products.append(cards.device_card(
            dev, public_base, card_price=cards.price(cand["monthly"], "month", was=dev["storage"][0]["monthly_24"],
                                                     note=note),
            reasons=[_purchase_text(cat, "upgrade.option.upgrade_now", cand)] + dev["highlights"][:2]))

    data = {
        "customer_id": customer_id, "line_id": line_id, "name": name, "device_id": own["id"],
        "device": own["name"], "age_months": r["age_months"], "battery_health": line["battery_health"],
        "needs": r["needs"], "monthly_budget": r["budget"], "issues": r["issues"],
        "penalty_per_unmet_need": PENALTY, "verdict": winner["id"], "verdict_label": winner["label"],
        "monthly_now": _installment(line),
        "options": [{"id": o["id"], "eligible": o["eligible"], "score": o["score"], "device_id": o["device_id"],
                     "unmet": o["unmet"], **({k: o["money"][k] for k in ("monthly_after", "once", "total_24m")}
                                             if o["eligible"] else {}),
                     "why": o["reasons"][0]["text"]} for o in r["options"]],
    }
    return data, reasons, [verdict, chart, *products]
