# 0006. Local-only model inference via the boldhalo router

**Status:** accepted

BoldTrader needs two kinds of model inference — high-volume triage classification and quality-sensitive structured enrichment — and has decided to run **all of it locally** on the MS-S1 Max through the boldhalo model router. No cloud APIs, ever, for any inference call. This is hard to reverse (every prompt, threshold, and fine-tune gets tuned against local model behavior, and the pipeline's architecture assumes zero per-call cost), surprising to a reader who would default to an API, and a real tradeoff: we accept lower raw model quality in exchange for zero marginal cost, no data egress, offline operation, and full control of the stack. The research grounding is `docs/research/local-models-ms-s1-max.md`; the consumer-side spec is `.scratch/bargain-search/spec.md`.

## What boldtrader requires from the router (the contract)

1. **OpenAI-compatible `/v1/chat/completions`**, model name passed per call. boldtrader never cares which weights answer; boldhalo owns routing, loading, and lifecycle.
2. **Two model slots, always available:**
   - **Enrichment / chat**: `qwen3.8-flash-next-w4b-q8-halogen` (loaded, stays loaded). ~1–3k tokens in, ~300–1,500 tokens of strict structured output out, low/no-thinking mode.
   - **Triage**: `decider-0.8b` on the XDNA 2 NPU, served by halogen (`HALOGEN_NPU_MODELS=decider-0.8b`, `/classify` endpoint). ~200 tokens in, one label out, hundreds of calls per session.
3. **Concurrency 1 for enrichment.** boldtrader will not fan out parallel big-model calls; the router should not need multi-slot scheduling for us.
4. **Errors must be loud.** A dead model, OOM, or timeout must surface as a clean HTTP error, not a hang. boldtrader retries once and marks failed; a silent hang poisons the queue.

## Key decisions needed (boldhalo side)

1. **Halogen memory config.** Halogen's Quickstart 200k config leaves ~12.4 GiB host-free; the n-gram table wants 47.7 GiB of page cache. Decide: shrink KV pool to 2 slots / `HALOGEN_MAX_TOK=16384` (~83 GiB taken, ~45 GiB left). Ground truth is halogen's startup line `host memory left for everything else`, NOT `free`/`MemAvailable` (they understate by ~62–68 GiB because locked weights count as reclaimable cache).
2. **`HALOGEN_WEIGHTS_LOCK=1` + `memlock unlimited`** in `/etc/security/limits.conf` (container `--ulimit` alone is insufficient on Ubuntu's 8 MiB default). Without the lock, memory pressure from any co-tenant triggers the stall mode (halogen #79/#83/#85: both sides stall for minutes at 100% of one core).
3. **NPU enablement on this unit.** XRT + NPU driver present; halogen refuses to start without the fabric-clock hold — that gate passing is the first check. Then smoke `decider-0.8b` via `/classify` on ~20 real listings.
4. **Triage quality gate.** `decider-0.8b` vs a human-labeled sample of ~50 listings: target ≥95% agreement on match/not-match/unsure. If it underperforms, fine-tune the decider on labeled data (halogen supports custom fine-tunes of the four small models) before considering a bigger triage model.
5. **Concurrent-load interference.** Run triage (NPU) at full sweep rate while enrichment (GPU) decodes; measure the Flash decode slowdown vs idle-NPU baseline. Halogen warns "somewhat slower"; if it's material, throttle triage concurrency or fall back to CPU-only triage.
6. **Compute-queue budget.** Total hardware compute queues across all processes must stay ≤8 or the iGPU pins at 100%-busy-at-idle. Any co-tenant GPU process needs `GPU_MAX_HW_QUEUES=1` or `2`.
7. **Fallback lane decision.** If NPU is unavailable/broken: CPU-only `Qwen3-4B-Instruct-2507 Q4_K_M` in a separate llama.cpp Vulkan server (~12–20 t/s, batch-oriented, ~100 listings/10 min). Zero GPU co-residency risk; decide whether this runs always-on or on-demand.
8. **Router restart semantics.** If halogen restarts mid-enrichment, in-flight calls fail; boldtrader's queue (SQLite status columns) resumes them. The router must not silently swallow or replay requests — each call is exactly-once from the router's side.

## Leads

- Halogen docs — host setup (memory behavior, weights lock, watchdog): https://peonist-ai.github.io/halogen-flash-server/host-setup/
- Halogen NPU small models (`decider-0.8b`, fine-tuning): https://peonist-ai.github.io/halogen-flash-server/npu-small-models/
- Halogen classifier guide: https://github.com/peonist-ai/halogen-flash-server/blob/main/docs/CLASSIFY.md
- ROCm Strix Halo system optimization (fabric clock, GTT, queues): https://rocm.docs.amd.com/en/docs-7.2.0/how-to/system-optimization/strixhalo.html
- strix-halo-guide (community benchmark source of truth, Oct 2026): https://github.com/hogeheer499-commits/strix-halo-guide
- Qwen3.8-Flash-Next architecture (125B + 51B n-gram, 6B active): https://qwen.ai/blog?id=qwen3.8-flash-next
- Full measured benchmark tables: `docs/research/local-models-ms-s1-max.md` §3–§5

## Consequences

- Enrichment throughput is ~30–60 s per listing; a 100-listing Bargain Search fills over ~1–2 hours. The product design (kick off, check back) already assumes this.
- If the decider's 0.8B quality ceiling proves too low even after fine-tuning, the whole single-box layout is in question (second machine for triage, or a leaner enrichment model to free GPU memory) — that would be a new ADR, superseding this one's layout.
- All prompts, confidence thresholds, and fine-tunes are tuned to local quality; moving any stage to a cloud model later means re-tuning from scratch.
