# AGENTS.md

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (`jbold569/boldtrader`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Workflow skills

Four repo skills teach the hunting workflow from the agent's side, under
`.omp/skills/` (symlinked to `.claude/skills`, one source of truth):
`hunting-a-product`, `correcting-data`, `tuning-thresholds`, `daily-sweep`.
Each names when to use it, the MCP tools it chains, and a worked example
sequence. `tests/test_skills.py` checks them against the live tool table —
when you add or rename an MCP tool, the skills need the same edit.
