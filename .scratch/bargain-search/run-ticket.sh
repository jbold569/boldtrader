#!/usr/bin/env bash
# Run one bargain-search ticket through a fresh headless omp session.
# Usage: ./run-ticket.sh issues/01-sqlite-schema.md
set -euo pipefail
cd "$(dirname "$0")"

TICKET="$1"
[ -f "$TICKET" ] || { echo "ticket not found: $TICKET" >&2; exit 1; }
mkdir -p logs

PROMPT=$(cat <<EOF
You are implementing one ticket of the BoldTrader Bargain Search feature.

Read these first, in order:
1. .scratch/bargain-search/spec.md   (the feature spec — source of truth)
2. GLOSSARY.md                      (canonical domain terms)
3. $TICKET                          (your ticket)

Rules:
- Implement exactly what the ticket says. No extra features, no speculative abstraction.
- NEVER use the task tool or spawn subagents. Do all work yourself, directly.
- Follow the existing code style in src/ (stdlib-first, no new dependencies unless the ticket demands it).
- Run the ticket's Verify section. If it fails, fix and re-run until it passes.
- When done and verified: run \`git add -A && git commit -m "<ticket>: <summary>"\`.
- Append a short results section to $TICKET under a \`## Comments\` heading: what you built, what you ran, what passed.
EOF
)

echo "=== $(date '+%H:%M:%S') starting $TICKET ==="
omp -p --mode json --yolo --no-title \
    --model qwen3.8-flash-next-w4b-q8-halogen-pair \
    --max-time 3600 \
    <<<"$PROMPT" > "logs/$(basename "$TICKET" .md).jsonl" 2>"logs/$(basename "$TICKET" .md).err"
rc=$?
echo "=== $(date '+%H:%M:%S') finished $TICKET rc=$rc ==="
exit $rc
