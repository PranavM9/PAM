# T-Mobile mock API (synthetic)

A standalone FastAPI service for the T-Mobile side track (SPEC §8 M17). It stands in for a carrier's commerce and customer layers with fully synthetic data, and returns deterministic, explained recommendations. PAM reaches it only through the M16 connector in [connector.yaml](connector.yaml).

Everything here is fictional: the brands (Aurora, Lumen, Kestrel, Nimbus), the plans (Starter, Plus, Max, Student), the households and the prices. No LLM, no network calls, no real customer data.

## Run

```bash
docker compose up -d --build tmobile-mock          # http://localhost:8100/health
# or, without Docker (from mock/tmobile):
uv run --frozen uvicorn app:app --port 8100
```

Environment: `MOCK_TODAY` (default `2026-10-18`) fixes "now", so every run is identical. `PUBLIC_BASE` (default `/connectors/tmobile`) prefixes image URLs.

## Tools

| Tool | Method and path | Parameters | Cards |
|---|---|---|---|
| `get_household` | `GET /customers/{customer_id}` | `customer_id` | 1 `comparison` |
| `search_devices` | `GET /catalog/devices` | `query?`, `max_monthly?`, `form_factor?`, `limit?` (1-6, default 3) | `product` |
| `list_plans` | `GET /catalog/plans` | `lines?` (1-5, default 1) | 4 `plan` |
| `tradein_value` | `GET /tradein/{device_id}` | `device_id`, `months_ahead?` (0-24, default 12) | 1 `chart` (marker at today) |
| `recommend_upgrade` | `POST /recommend/upgrade` | `customer_id`, `line_id`, `monthly_budget?`, `needs?` | `verdict`, `chart`, up to 2 `product` |
| `optimize_household` | `POST /recommend/household` | `customer_id`, `include_home_internet?` | `verdict`, `comparison` |
| `suggest_addons` | `POST /recommend/addons` | `customer_id`, `line_id`, `device_id` | up to 3 `product`, or 1 `notice` |

Plus `GET /health` and static `GET /images/...`.

Every tool answers:

```json
{"synthetic": true, "as_of": "2026-10-18", "data": {}, "reasons": [{"text": "", "signal": "", "value": null}], "pam_cards": []}
```

Each reason names the field it used in `signal` (for example `line.device.battery_health`, `tradein.curve`, `request.monthly_budget`). Every card validates as the CHG-0027 `ConnectorCard`, carries the badge `Synthetic demo data`, and leaves `connector_id` for PAM to set.

## How it fits T17 (the M16 executor)

- **Arguments.** GET tools read the query string; POST tools read a JSON object body (query parameters also work, for `curl`). Numbers may arrive as `40` or `40.0`, and booleans as `true`/`false`.
- **Image URLs** are root-relative and already include `PUBLIC_BASE`, for example `/connectors/tmobile/images/devices/kestrel-5-slate.svg`. Resolving them against `public_base_url` with URL-join rules (a path that starts with `/` keeps its path) leaves them unchanged; nginx serves them at that path.
- **Errors** are `{"synthetic": true, "as_of": "...", "error": {"code", "message"}}` with HTTP 404 (`NOT_FOUND`: unknown customer, line or device) or 400 (`BAD_ARGUMENTS`). T17 turns these into `HTTP_404` and `HTTP_400`.
- **At most 6 cards** per answer (`search_devices` clamps `limit` to 6), matching PAM's cap.

## Engines

- **Timekeeper** (`engine/upgrade.py`). Options: `no_change` (always scored), `replace_battery` (battery under 80% and the phone still gets updates; $89 from `addons.json`), `upgrade_now`, `wait_3_months` and `wait_6_months`. Score = 24-month net cost (price - trade-in from the curve - an active promotion) + $150 for each need left unmet. Waiting adds $150 x months / 12 for each current issue. Lowest score wins and ties break by id. A battery under 80% and a phone past its update date count as issues even when you don't name them.
- **Household optimizer** (`engine/household.py`). Tries every plan per line (4^lines, at most 1,024), every subset of the 2 streaming bundles, and the home internet choice. Each line's plan must cover its 6-month peak data and hotspot (and travel, if any); the Student plan needs a student. The current bill counts the services the household pays for elsewhere; a proposed mix drops those a plan perk or bundle covers. Savings under $5/mo give "Keep your plan".
- **Cart Whisperer** (`engine/addons.py`). Ordered rules (protection, case, charger, earbuds, watch line, home internet, bundles, travel pass), each with its reason; at most 3, else "Nothing else needed".

## Data

`data/devices.json` (12 on sale, 8 older), `plans.json`, `addons.json` (add-ons and the streaming services they replace), `tradein.json` (a 36-month non-increasing curve per device and 3 promotions), `customers.json` (5 households: `cust-chen`, `cust-rivera`, `cust-okafor`, `cust-northwind`, `cust-hale`), and `messages.json` (all user-facing copy: second person, at most 2 sentences, no exclamation marks).

## Regenerate

```bash
python3 tools/make_images.py                 # rewrites images/ (byte-identical on re-run)
python3 tools/make_export.py                 # writes demo-export/claude-export.zip (gitignored)
```

## Tests

```bash
uv run --frozen pytest -q
```

The tests cover the envelope and card schema, byte-identical answers, the M17 acceptance verdicts, coverage and enumeration in the optimizer, the add-on rules, catalog filters and curves, data integrity and copy rules, image determinism and size, the export layout, and `connector.yaml` against the CHG-0027 `Connector` model, called the way T17 calls it.

The demo story and setup are in [DEMO.md](DEMO.md).
