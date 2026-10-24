# 06 — Enhanced view

Status: ready-for-agent

Per Bargain Search: match-filtered card list. Enriched cards show ✨ + extracted fields (product, condition, bundle contents, confidence). Pending cards show "pending" marker. Failed show "enrichment failed". Show-all toggle. Optional target-price filter (off by default). Reject button on enriched cards → `rejects` row → next triage pass respects exclusions.

Authored description: user can write one on any card; it overrides AI enrichment everywhere downstream.

Verify: browse a completed Bargain Search; toggle filters; reject a card and confirm it disappears from matches and lands in exclusions.
