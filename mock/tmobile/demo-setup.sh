#!/usr/bin/env bash
# Set up the T-Mobile demo on a scratch vault (SPEC M17, T19 step 7).
#
# Usage, from the repo root:
#   mock/tmobile/demo-setup.sh                 # pam on PATH (e.g. PAM="uv run --frozen --project backend pam")
#   PAM_DOCKER=1 mock/tmobile/demo-setup.sh    # pam inside the running backend container
#
# Stages the export and connector.yaml in ./demo/tmobile/ (mounted at /demo/tmobile in the
# backend container), creates the vault ./demo/tmobile/vault, imports Maya's 10 conversations,
# runs derive and index, creates the "Phones and money" project from the 4 phone-and-money
# conversations, clusters the rest, creates the agent `tmobile-advisor` scoped to that project,
# adds the connector (needs T17), and writes the agent's persona.
# It never deletes anything: if the vault already exists it stops.
#
# Why the project comes before clustering (CHG-0031): with the default assign_threshold (0.70)
# the apartment-search chat (cosine 0.72 to the phone conversations) and then the resume chat
# join the phone project. The four phone conversations score 0.82-0.91, so this demo vault uses
# assign_threshold 0.80, and the project is created from the conversations' own topic labels.
#
# In Docker mode the backend container runs as root and writes vault files with mode 0600, so
# everything that reads or writes the vault or ./demo goes through the container.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STAGE="$REPO/demo/tmobile"
VAULT_HOST="$STAGE/vault"
DEMO_ASSIGN_THRESHOLD="0.80"
if [ "${PAM_DOCKER:-0}" = "1" ]; then
    COMPOSE=(docker compose -f "$REPO/docker-compose.yml")
    PAM=("${COMPOSE[@]}" exec -T backend pam)
    VAULT_SH=("${COMPOSE[@]}" exec -T backend sh -c)
    STAGE_PAM="/demo/tmobile"
else
    read -r -a PAM <<< "${PAM:-pam}"
    VAULT_SH=(sh -c)
    STAGE_PAM="$STAGE"
fi
VAULT_PAM="$STAGE_PAM/vault"
AGENT="tmobile-advisor"
PERSONA="You help with phones and plans. Use the user's memory and the carrier tools together. Prefer the cheapest option that meets their needs, say when waiting is better, and show the numbers."

pam() { "${PAM[@]}" --vault "$VAULT_PAM" "$@"; }
step() { printf '\n== %s\n' "$*"; }
# Run a shell snippet where pam runs (host or container); extra arguments become $1, $2, ...
vault_sh() { "${VAULT_SH[@]}" "$1" sh "${@:2}"; }

if [ -e "$VAULT_HOST" ]; then
    echo "error: $VAULT_HOST already exists. Move it away (nothing is deleted by this script) and re-run." >&2
    exit 1
fi

step "Stage the export and the connector in $STAGE"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 -I "$HERE/tools/make_export.py" --out "$TMP/claude-export.zip"
cp "$HERE/connector.yaml" "$TMP/connector.yaml"
if [ "${PAM_DOCKER:-0}" = "1" ]; then
    vault_sh 'mkdir -p "$1"' "$STAGE_PAM"
    "${COMPOSE[@]}" cp "$TMP/." "backend:$STAGE_PAM/"
else
    if ! mkdir -p "$STAGE" 2>/dev/null || [ ! -w "$STAGE" ]; then
        echo "error: cannot write $STAGE (owned by $(stat -c %U "$REPO/demo" 2>/dev/null || echo another user))." >&2
        echo "Run with PAM_DOCKER=1, or make ./demo yours: docker compose exec backend chown -R $(id -u):$(id -g) /demo" >&2
        exit 1
    fi
    cp "$TMP/claude-export.zip" "$TMP/connector.yaml" "$STAGE/"
fi

step "Create the scratch vault"
pam init

step "Import Maya's 10 conversations"
pam import run "$STAGE_PAM/claude-export.zip"

step "Derive and index"
pam derive
pam index

step "Create the phone-and-money project from its 4 conversations"
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
args=()
for id in "${PHONE[@]}"; do args+=(--episode "$id"); done
PROJECT="$(pam --json project create --name "Phones and money" "${args[@]}" \
    | python3 -I -c 'import json, sys; r = json.load(sys.stdin); print(r["doc_id"] if r["ok"] else "")')"
if [ -z "$PROJECT" ]; then
    echo "error: could not create the Phones and money project" >&2
    exit 1
fi
echo "project: $PROJECT"

step "Cluster the other conversations (assign_threshold $DEMO_ASSIGN_THRESHOLD in this demo vault)"
vault_sh 'sed -i "s/^assign_threshold = .*/assign_threshold = $2/" "$1/pam.toml"' "$VAULT_PAM" "$DEMO_ASSIGN_THRESHOLD"
pam cluster
members="$(vault_sh 'cat "$1"' "$VAULT_PAM/memory/default/projects/$PROJECT.md" \
    | grep -Eo '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | sort -u | grep -cv "^$PROJECT$" || true)"
if [ "$members" -ne 4 ]; then
    echo "error: the Phones and money project has $members episodes after clustering, expected 4" >&2
    exit 1
fi
echo "Phones and money still has exactly the 4 phone conversations"

step "Create the agent $AGENT"
pam agent create "$AGENT" --display-name "T-Mobile advisor" \
    --description "Phones and plans, using memory and the synthetic carrier tools." \
    --projects "$PROJECT" --tools get_context,search_memory,add_fact,update_working_memory

step "Add the T-Mobile connector (needs T17)"
pam connector add "$STAGE_PAM/connector.yaml"

step "Write the agent's custom persona"
vault_sh 'printf "\n%s\n" "$2" >> "$1/agent/tmobile-advisor/identity.md"' "$VAULT_PAM" "$PERSONA"
pam sync

step "Done"
echo "Vault: $VAULT_HOST"
echo "Start the mock with: docker compose up -d --build tmobile-mock"
echo "Then chat as $AGENT (see mock/tmobile/DEMO.md)."
