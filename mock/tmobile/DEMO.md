# T-Mobile demo: the 3-minute story

**Maya Chen**, 20, a UW student, has a 37-month-old Kestrel 5 whose battery dies by 2pm. Her family's bill just went from $212 to $236. Over the last month she asked Claude about her phone, her budget, her brother's camera and the family plan, alongside six unrelated chats.

PAM imports those chats as memory. The `tmobile-advisor` agent sees only the phone-and-money project, and calls the synthetic carrier through the `tmobile` connector. The answer combines both: what Maya said (battery by 2pm, $40 a month until June) and what the carrier knows (battery health 78%, trade-in curve, plans and usage).

Everything shown is synthetic: fictional brands, plans, people and prices, labelled `Synthetic demo data` on every card.

## Before the demo (once)

Needs T17 (connectors backend) and T18 (connectors UI and chat cards) merged, and a model with `supports_tools`.

```bash
docker compose up -d --build                            # backend, frontend and tmobile-mock
PAM_DOCKER=1 mock/tmobile/demo-setup.sh                 # scratch vault in ./demo/tmobile/vault
```

The backend serves `./vault`. To demo on the new vault, move your own `./vault` aside, then `mv demo/tmobile/vault vault` and `docker compose restart backend`. Open http://localhost:5173.

Check:
- http://localhost:5173/connectors/tmobile/images/devices/kestrel-5-slate.svg opens.
- `pam connector call tmobile get_household --arg customer_id=cust-chen` prints `ok` and card titles.

## The story (under 3 minutes)

1. **Memory, scoped (20 s).** Open the graph or the agent page. `tmobile-advisor` reads one project, "phones and money", with 4 conversations. The pho recipe, the AVL assignment and the rest are outside its scope.

2. **"Should I upgrade my phone?" (60 s).** Chat as `tmobile-advisor`. The agent pulls memory (battery dies by 2pm, about $40 a month until June, cracked corner) and calls `recommend_upgrade` for `cust-chen` / `chen-maya` with `monthly_budget=40`, `needs=battery,camera`.
   - Expected verdict: **Replace the battery** ($89 once). Waiting and the upgrade are scored on the same scale and shown losing, with the numbers.
   - Cards: the verdict, the Kestrel 5 trade-in chart ($63 today, about $57 in 3 months, "Today" marker), and two phones within budget.
   - The point to say out loud: it recommends **not** buying a phone, and shows why.

3. **"Is our family plan too expensive?" (50 s).** The agent remembers that Mom asked, and calls `get_household` then `optimize_household` for `cust-chen`.
   - Expected: **Save $74.48/mo** (about $894 a year). David moves from Max to Starter (he peaks at 2.4 GB), Mei from Max to Plus, Maya and Leo to Student (Leo was being slowed on Starter), and the Reelhouse and Tunewave subscriptions paid separately are covered by Mei's Plus perk and the $8/mo Sound bundle.
   - Cards: the verdict ("Save ... on your plans") and the line-by-line comparison.

4. **Honesty check (30 s, optional).** Ask the same question for another household, `cust-okafor`: the answer is **Keep your plan**. For add-ons on Ada's line (`okafor-ada`), the answer is **Nothing else needed**.

5. **Close (20 s).** The carrier never saw Maya's chats, and PAM never sent them anywhere. The agent combined her own context with the carrier's data on her machine, and every recommendation is explained.

## Direct calls (for rehearsal)

```bash
curl -s localhost:8100/customers/cust-chen | python3 -m json.tool | head -40
curl -s -X POST localhost:8100/recommend/upgrade -H 'content-type: application/json' \
  -d '{"customer_id":"cust-chen","line_id":"chen-maya","monthly_budget":40,"needs":"battery,camera"}'
curl -s -X POST localhost:8100/recommend/household -H 'content-type: application/json' -d '{"customer_id":"cust-chen"}'
curl -s -X POST localhost:8100/recommend/household -H 'content-type: application/json' -d '{"customer_id":"cust-okafor"}'
```

## If something goes wrong

- **No cards in chat:** check the model has `supports_tools`, the connector is enabled and lists `tmobile-advisor`, and the mock is healthy (`docker compose ps`).
- **Images are broken:** the frontend proxies `/connectors/tmobile/` to `tmobile-mock:8100`; start the mock and reload.
- **The agent cites unrelated chats:** rerun `demo-setup.sh` on a fresh folder; the agent must be scoped to the phone-and-money project only.
