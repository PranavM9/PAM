#!/usr/bin/env bash
# Set up the T-Mobile demo on a scratch vault (SPEC M17, T19 step 7).
#
# Usage, from the repo root:
#   mock/tmobile/demo-setup.sh                 # pam on PATH (e.g. `cd backend && uv run ...`)
#   PAM_DOCKER=1 mock/tmobile/demo-setup.sh    # pam inside the running backend container
#
# Stages the export and connector.yaml in ./demo/tmobile/ (mounted at /demo/tmobile in the
# backend container), creates the vault ./demo/tmobile/vault, imports Maya's 10 conversations,
# runs derive, index and cluster, creates the agent `tmobile-advisor` scoped to the
# phone-and-money project, adds the connector (needs T17), and writes the agent's persona.
# It never deletes anything: if the vault already exists it stops.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STAGE="$REPO/demo/tmobile"
VAULT_HOST="$STAGE/vault"
if [ "${PAM_DOCKER:-0}" = "1" ]; then
    PAM=(docker compose -f "$REPO/docker-compose.yml" exec -T backend pam)
    STAGE_PAM="/demo/tmobile"
else
    read -r -a PAM <<< "${PAM:-pam}"
    STAGE_PAM="$STAGE"
fi
VAULT_PAM="$STAGE_PAM/vault"
AGENT="tmobile-advisor"
PERSONA="You help with phones and plans. Use the user's memory and the carrier tools together. Prefer the cheapest option that meets their needs, say when waiting is better, and show the numbers."

pam() { "${PAM[@]}" --vault "$VAULT_PAM" "$@"; }
step() { printf '\n== %s\n' "$*"; }

if [ -e "$VAULT_HOST" ]; then
    echo "error: $VAULT_HOST already exists. Move it away (nothing is deleted by this script) and re-run." >&2
    exit 1
fi

step "Stage the export and the connector in $STAGE"
mkdir -p "$STAGE"
python3 -I "$HERE/tools/make_export.py" --out "$STAGE/claude-export.zip"
cp "$HERE/connector.yaml" "$STAGE/connector.yaml"

step "Create the scratch vault"
pam init

step "Import Maya's 10 conversations"
pam import run "$STAGE_PAM/claude-export.zip"

step "Derive, index and cluster"
pam derive
pam index
pam cluster

step "Find the phone-and-money project"
EPISODES_JSON="$(pam --json episode list --limit 100)"
PHONE_IDS="$(EPISODES_JSON="$EPISODES_JSON" python3 -I -c '
import json, os, sys
source = json.load(open(sys.argv[1], encoding="utf-8"))
titles = {c["title"] for c in source if c["topic"] == "phones-and-money"}
episodes = json.loads(os.environ["EPISODES_JSON"])
print(" ".join(sorted(e["id"] for e in episodes if e["title"] in titles)))
' "$HERE/demo-export/conversations.json")"
read -r -a PHONE <<< "$PHONE_IDS"
if [ "${#PHONE[@]}" -ne 4 ]; then
    echo "error: expected 4 phone-and-money episodes, found ${#PHONE[@]}" >&2
    exit 1
fi
PROJECT=""
for file in "$VAULT_HOST"/memory/default/projects/*.md; do
    [ -e "$file" ] || continue
    hits=0
    for id in "${PHONE[@]}"; do grep -q "$id" "$file" && hits=$((hits + 1)); done
    members="$(grep -Eo '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' "$file" | sort -u | wc -l | tr -d ' ')"
    # The project id appears in its own file, so a clean match has 4 episode ids + 1 project id.
    if [ "$hits" -eq 4 ] && [ "$members" -le 5 ]; then
        PROJECT="$(basename "$file" .md)"
        echo "clustering found it: $PROJECT"
    fi
done
if [ -z "$PROJECT" ]; then
    echo "clustering mixed topics; creating the project from the 4 episodes"
    args=()
    for id in "${PHONE[@]}"; do args+=(--episode "$id"); done
    PROJECT="$(pam --json project create --name "Phones and money" "${args[@]}" \
        | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["doc_id"])')"
fi
echo "project: $PROJECT"

step "Create the agent $AGENT"
pam agent create "$AGENT" --display-name "T-Mobile advisor" \
    --description "Phones and plans, using memory and the synthetic carrier tools." \
    --projects "$PROJECT" --tools get_context,search_memory,add_fact,update_working_memory

step "Add the T-Mobile connector (needs T17)"
pam connector add "$STAGE_PAM/connector.yaml"

step "Write the agent's custom persona"
printf '\n%s\n' "$PERSONA" >> "$VAULT_HOST/agent/$AGENT/identity.md"
pam sync

step "Done"
echo "Vault: $VAULT_HOST"
echo "Start the mock with: docker compose up -d --build tmobile-mock"
echo "Then chat as $AGENT (see mock/tmobile/DEMO.md)."
