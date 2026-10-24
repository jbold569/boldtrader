# Local LLM Inference on the Minisforum MS-S1 Max

Research date: 2026-10-24. Purpose: decide the local model stack (runtime + triage model + enrichment model + quantization) for BoldTrader's two-stage deal-finding pipeline, running entirely on a Minisforum MS-S1 Max. Written to be portable into the "boldhalo" model-router project.

BoldTrader's two AI stages:

1. **Triage** (small model): classify a listing (title + snippet, ~200 tokens in, one label out: match / not-match / unsure) against a product description. High throughput (hundreds of listings per session), low per-call latency, cheap.
2. **Enrichment** (larger reasoning model): read full listing text (~1–3k tokens) and extract structured fields — product identity (manufacturer/model/config), condition from a fixed set, bundle contents as a list — with per-field confidence. Reasoning quality over raw speed.

Constraint: local models only, AMD platform, no cloud APIs.

---

## 1. Hardware facts

The MS-S1 Max is a 3.6 L mini AI workstation built on the **AMD Ryzen AI Max+ 395** ("Strix Halo"). It is the same silicon as the GMKtec EVO-X2, Beelink GTR9 Pro, and Framework Desktop — which matters because virtually all community LLM benchmarks below were produced on those boxes and transfer directly.

| Component | Spec | Source |
|---|---|---|
| CPU | AMD Ryzen AI Max+ 395: 16 cores / 32 threads, Zen 5 + Zen 5c, up to 5.1 GHz | [Minisforum product page](https://www.minisforum.com/products/ms-s1-max), [AMD product page](https://www.amd.com/en/products/processors/laptop/ryzen/ai-300-series/amd-ryzen-ai-max-plus-395.html) |
| iGPU | Radeon 8060S, **40 compute units, RDNA 3.5**, up to 2.9 GHz, gfx1151 | [HotHardware announcement](https://hothardware.com/news/minisforum-ms-s1-max-mini-pc-announced) |
| NPU | XDNA 2, 50 TOPS INT8 (platform total marketed as 126 TOPS CPU+GPU+NPU) | [Minisforum product page](https://www.minisforum.com/products/ms-s1-max) |
| RAM | Up to **128 GB LPDDR5X-8000 MT/s, quad-channel**, soldered, unified (CPU + iGPU + NPU share one pool). 64 GB SKU also sold ("Local AI Pilot Edition") | [Minisforum product page](https://www.minisforum.com/products/ms-s1-max) |
| Memory bandwidth | **256 GB/s theoretical, ~215 GB/s measured** under real load | [DataHardware Strix Halo tok/s article](https://datahardware.ai/blog/strix-halo-tokens-per-second-2026), [compareaihardware](https://compareaihardware.com/ai-mini-pc/minisforum-ms-s1-max-ryzen-ai-max-395) |
| Power | 160 W peak / 130 W sustained PPT, built-in 320 W PSU | [Minisforum product page](https://www.minisforum.com/products/ms-s1-max) |
| I/O | Dual 10GbE, USB4 V2, Wi-Fi 7, PCIe 4.0 x4 (full-length x16 slot) | [Minisforum product page](https://www.minisforum.com/products/ms-s1-max) |

Notes:

- The product is recent; Minisforum's own spec pages are marketing-heavy and thin on low-level detail (no official per-backend numbers). Everything hardware-level above is cross-checked against independent reviews ([HotHardware](https://hothardware.com/news/minisforum-ms-s1-max-mini-pc-announced), [NAS Compares review](https://nascompares.com/2026-01-23/minsforum-ms-s1-max-review-who-is-this-for/)).
- A newer variant, **MS-S1 MAX-P495**, ships the Ryzen AI Max+ **PRO 495** ("Gorgon Halo", 16C/32T, up to 5.2 GHz, 131 TOPS) ([Minisforum](https://store.minisforum.com/products/minisforum-ms-s1-max-p495-ai-workstation)). All conclusions in this doc apply equally; PRO adds ECC support and manageability, not inference speed.
- **The single most important number: ~215 GB/s real memory bandwidth.** Token generation is bandwidth-bound. Dense models read all weights per token; MoE models read only the active experts. This is why model *architecture* (active params/token), not total size, decides speed on this box.

---

## 2. AMD software toolbox

### 2.1 ROCm (HIP)

- gfx1151 (Radeon 8060S) is **officially supported** in ROCm. The Radeon/Ryzen compatibility matrix lists Ryzen AI Max+ 395 under ROCm 6.4.4 and later, through ROCm 7.x and the ROCm Core SDK 10.x line ([ROCm compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-6.4.4/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html), [ROCm 10.1 matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html)).
- Early gotchas (now mostly historical): some ROCm builds didn't recognize gfx1151 without `HSA_OVERRIDE_GFX_VERSION=11.5.1`; Ollama ≥ 0.18 detects it natively ([ollama#14855](https://github.com/ollama/ollama/issues/14855)). ROCm 7.1.0 had a null-pointer bug in the stock HSA runtime on gfx1151 requiring a nightly runtime overlay ([HF bench dataset README](https://huggingface.co/datasets/NorthstarAurora/strix-halo-bench-data)).
- **Correctness caveat (important):** llama.cpp HIP on integrated hosts had a silent-corruption issue at long context / multimodal / multi-slot (llama.cpp issue #26209); a revert mitigation shipped in llama.cpp v0.4.1, but the community guide treats stock HIP as *not fully correctness-qualified* on Strix Halo as of late 2026 ([strix-halo-guide CURRENT_MODELS](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/CURRENT_MODELS.md)).
- ROCm wins on **prefill for dense models** (e.g. +52% pp on 70B) and on very long context; it **loses on decode** for MoE (−20 to −30% vs Vulkan) ([visorcraft benchmarks](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md), [strix-halo bench sweep](https://huggingface.co/datasets/NorthstarAurora/strix-halo-bench-data)).
- AMD publishes a Strix Halo system-optimization guide ([ROCm docs](https://rocm.docs.amd.com/en/docs-7.2.0/how-to/system-optimization/strixhalo.html)).

**Verdict:** works, useful for specific batch/prefill-heavy lanes, but not the default choice for this workload mix.

### 2.2 llama.cpp Vulkan (Mesa RADV)

- **The default recommendation for Strix Halo.** RADV (Mesa ≥ 25.2, ideally 26.x) supports gfx1151 properly: fp16, warp 64, `KHR_coopmat`. Matches or beats ROCm on token generation across the board; wins both prefill and decode on MoE models ([visorcraft](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md), [codersera guide](https://codersera.com/blog/amd-strix-halo-ryzen-ai-max-local-llm-setup-2026/)).
- Zero driver wrangling: prebuilt llama.cpp Vulkan binaries work out of the box on Linux and Windows.
- Gotchas: RADV caps a single allocation at 4 GiB (matters only for exotic single-tensor loads); on Linux you must raise the GTT limit so the iGPU can address the full unified memory (`amdgpu.gttsize=110000` or `amdttm.pages_limit=...` kernel params, BIOS UMA framebuffer set small — 512 MB) ([codersera guide](https://codersera.com/blog/amd-strix-halo-ryzen-ai-max-local-llm-setup-2026/)).
- AMDVLK (the other Vulkan driver) is **broken on gfx1151** (misreports shared memory as 32 KB vs 64 KB actual; −247% prefill). Use RADV only ([visorcraft](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md)).

**Verdict: use this.** Vulkan/RADV + llama.cpp is the boring, fast, correct default.

### 2.3 NPU stack (XDNA 2)

- **`ryzenai-faststack`: no public project by this name was found as of 2026-10-24 (UNVERIFIED — likely a misremembered name).** The actual AMD NPU software stack is:
  - **RyzenAI-SW** ([amd/RyzenAI-SW](https://github.com/amd/RyzenAI-SW)) — ONNX Runtime GenAI (OGA) based LLM deployment, NPU-only and NPU+iGPU hybrid modes ([docs](https://ryzenai.docs.amd.com/en/latest/llm/overview.html)). Windows-first tooling; model support is a curated list (small models: Gemma-3-4B, GPT-OSS-20B, SmolLM, etc.), long context capped ~16K.
  - **FastFlowLM** ([ROCm/FastFlowLM](https://github.com/ROCm/FastFlowLM)) — newer purpose-built NPU runtime; Linux support announced March 2026 ([Lemonade announcement](https://lemonade-server.ai/flm_npu_linux.html)).
  - **Lemonade SDK** — OpenAI-compatible server wrapping RyzenAI-SW/OGA models.
- Practical status for LLMs on XDNA 2: the NPU is fine for tiny models (ASR, embeddings, ≤4B) at low power, but the ONNX export pipeline is per-model, slow to iterate on, and context-limited. Community measurement: running load on the NPU costs the iGPU far more (+68.96% latency with a comparable iGPU aux load) than it helps (+3.29% with NPU sidecar) — the NPU is a sidecar, not a co-worker, for iGPU-bound LLM work ([strix-halo-guide community results](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/CURRENT_MODELS.md)).

**Verdict (revised by the live inventory):** skip the NPU for *general* LLM work — but halogen-flash-server changes this for *triage*: it runs small models (0.6B–2B, incl. a `decider-0.8b` classifier) on the NPU as a managed sidecar with the fabric-clock problem already solved. That is the one case where the NPU earns its keep here (§5.3).

### 2.4 ONNX Runtime (plain)

Viable for CV/encoder-style models (embeddings, OCR) via DirectML/RyzenAI EP, but for LLM generation everything routes through OGA/RyzenAI-SW (see 2.3). Not a primary path.

### 2.5 Ollama (AMD)

- Works well on gfx1151; native ROCm detection since 0.18; Vulkan mode also available. Current stable ~0.40.x ([strix-halo-guide availability check, 2026-10-21](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/CURRENT_MODELS.md)).
- Measured on Strix Halo: Qwen3.6-35B-A3B Q4_K_M ~60–73 t/s warm via API; requires `OLLAMA_IGPU_ENABLE=1` on some versions to keep the iGPU active. Convenient OpenAI-compatible server, but historically under-allocates unified memory vs raw llama.cpp and adds its own scheduling layer ([strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md)).

**Verdict:** fine for prototyping; for a router we control, run llama.cpp `llama-server` directly.

### 2.6 LM Studio (AMD)

- Ships selectable llama.cpp runtimes (Vulkan and ROCm) on Windows and Linux; AMD's own playbook validates it ([AMD AI Playbook: LM Studio + ROCm](https://developer.amd.com/playbooks/lmstudio-rocm-llms/), validated Aug 2026). Good GUI for manual model curation; not appropriate as an embedded runtime in a production router.

### 2.7 halogen-flash-server (the live enrichment runtime)

Dedicated ROCm/HIP inference engine for **Qwen3.8-Flash-Next only**, built for agents: OpenAI-compatible API, session fork/join, token budgets, a `/classify` endpoint, and small models on the NPU ([halogen docs](https://peonist-ai.github.io/halogen-flash-server/), [repo](https://github.com/peonist-ai/halogen-flash-server)). This is what is currently loaded on the boldhalo router and what the user wants to keep.

Key operational facts (full detail in §5.2): ~68 GiB pinned weights (w4b), up-front KV pool reservation, 47.7 GiB n-gram table in page cache, `free`/`MemAvailable` understate usage by the model size, `HALOGEN_WEIGHTS_LOCK=1` required when co-tenants exist, GPU compute-queue budget of 8 across all processes, NPU small-model sidecar (`decider-0.8b`, embeddings, reranker, guard, 2B, ASR/TTS) with a fabric-clock-hold requirement.


**Verdict:** the right enrichment runtime for this deployment. Its "owns the machine" design is the constraint that shapes the whole stack — see §5.

---

## 3. Small model candidates (triage)

Task shape: ~200-token prompt, 1-token label output, hundreds of calls per session. **Prefill speed and per-call overhead dominate; decode speed barely matters.** All numbers below are llama.cpp on Strix Halo-class hardware (Ryzen AI Max+ 395 / Radeon 8060S), Vulkan/RADV unless noted.

| Model | Class | Context | Quant | Measured on Strix Halo | Source |
|---|---|---|---|---|---|
| Qwen3-0.6B | 0.6B dense | 32K (40K+) | Q8_0 | pp512 4,666 / tg128 208.7 (HIP); pp512 13,112 / tg128 266 (one Vulkan run) | [strix-halo-guide BENCHMARKS](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md) |
| TinyLlama 1.1B | 1.1B dense | 2K | Q4_K_M | pp512 6,513 / tg128 249 | [visorcraft](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md) |
| Llama 3.2 3B | 3B dense | 128K | Q8_0 | pp512 2,248 / tg128 60.9 | [visorcraft](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md) |
| Qwen3-1.7B | 1.7B dense | 32K (131K w/ YaRN) | Q4_K_M | **No direct Strix Halo run found (UNVERIFIED).** Interpolating 1.1B↔3B: ~3,000–4,500 t/s prefill, ~120–160 t/s decode | — |
| Qwen3-4B / Qwen3-4B-Instruct-2507 | 4B dense | 128K (256K extended) | Q4_K_M (~2.5 GB) | **No direct Strix Halo run found (UNVERIFIED).** Same-class 4B proxy (Bonsai-4B Q4): pp512 1,401 / tg128 85 | [Bonsai community bench](https://github.com/PrismML-Eng/Bonsai-demo/blob/97ec2057763ab83faf6eb794b92cb0e333b8dd7d/community-benchmarks/bonsai/vulkan-strix-halo-128gb-archlinux.md) |
| Qwen3.6 4B QAT | 4B dense, quant-aware trained | — | UD-Q4 | 110.0 t/s best repeat (with MTP head) | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md) |
| Gemma 3 4B | 4B dense | 128K | Q4 | **No direct Strix Halo run found (UNVERIFIED).** Same-size class ≈ 85 t/s decode | — |
| LFM2.5 8B-A1B | 8B MoE, 1B active | 32K+ | Q4_K_M | pp512 3,398 / tg128 176.5 | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md) |

Triage throughput math: at ~200 prompt tokens per listing, a 4B-class model at ~1,400–3,000 t/s prefill processes one listing in **~0.07–0.15 s**; 500 listings ≈ 35–75 s of GPU time per session. Even the slowest credible 4B number clears "hundreds per session" comfortably. A 1.7B model roughly doubles that headroom.

**Candidate ranking for triage (given halogen is the live runtime):**

1. **`decider-0.8b` on the NPU, served by halogen** (`HALOGEN_NPU_MODELS=decider-0.8b`, `/classify` endpoint) — purpose-built for exactly this one-label-out task, zero GPU memory cost, runs concurrent with GPU enrichment, and halogen supports fine-tuning it on your own labeled data. This is the recommended path (§5.3, §6).
2. **Qwen3-4B-Instruct-2507 Q4_K_M** (CPU-only fallback) — best quality-per-size for classification/instruction tasks in the 2026 small-model field ([tool-calling comparison](https://www.ertas.ai/blog/on-device-tool-calling-2026-qwen3-gemma4-phi4)); 128K context gives room for a fat system prompt with the product description.
3. **Qwen3.6 4B QAT UD-Q4** — if available for the exact model you pick, quant-aware training preserves quality at 4-bit and it measured fastest-in-class.
4. **Qwen3-1.7B Q4_K_M** (CPU-only fallback) — if you want maximum throughput and can accept a small accuracy drop; verify against a labeled sample set.
5. Phi-4-mini / Gemma 3 4B — viable alternates; no Strix-specific numbers found; treat as UNVERIFIED on this hardware.

---

## 4. Reasoning model candidates (enrichment)

Task shape: 1–3k token input, structured JSON output (~300–1,500 tokens), quality-sensitive. Decode speed matters (output is long), prefill is moderate. Q4 vs Q6: on this hardware the Q4→Q6 decode penalty is small for MoE (weights read per token dominated by active experts) but real for dense models; community quality testing found Q4_K_M vs Q8_0 indistinguishable on structured tasks ([agmind Q8 vs Q4 study](https://agmind.ai/reports/q8-0-vs-q4-k-m-strix-halo/)).

| Model | Class | Quant | Measured on Strix Halo | Notes | Source |
|---|---|---|---|---|---|
| Qwen3-30B-A3B-Instruct-2507 | 30B MoE, 3B active | IQ4_XS (13.9 GB) | **100–103 t/s** decode, ~1,430 t/s prefill | The sweet spot: 100+ t/s direct, 100% strict-JSON task success measured | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md), [agmind](https://github.com/botAGI/strix-halo-llm-benchmarks) |
| Qwen3-Coder-30B-A3B | 30B MoE, 3B active | Q4_K_S (17.5 GB) | 98–101 t/s decode, ~1,400 t/s prefill | Coding-flavored; overkill for extraction but excellent JSON discipline | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md) |
| Qwen3.6-35B-A3B | 35B MoE, 3B active | Q4_K_M (~20 GB) | 62–77 t/s decode; 100% strict-JSON success; TTFA 210 ms (no-think) | Newer generation, slightly slower quants, better quality | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md), [agmind](https://github.com/botAGI/strix-halo-llm-benchmarks) |
| Gemma 4 26B-A4B IT (QAT) | 26B MoE, 4B active | UD-Q4_K_XL (14.2 GB) | 74.8 t/s direct; 102–110 t/s with matched MTP head | QAT variant notably faster than non-QAT (54 t/s) | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md) |
| Qwen3.8-27B | 27B dense | Q4_K_M (17.7 GB) | ~20 t/s (Ollama w/ MTP); ~7.5 t/s plain Q8 RADV | Dense = slow here. Avoid unless quality delta is decisive | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/CURRENT_MODELS.md) |
| gpt-oss-120b | 117B MoE, 5.1B active | MXFP4 (~60 GB) | 55.6 t/s decode, ~730 t/s prefill | Fits easily; slower than 30B-A3B class, near-frontier quality | [strix-halo-guide](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/BENCHMARKS.md) |
| MiniMax M2.5 | 229B MoE, ~10B active | Q3_K_M (102 GB) | 32.8 t/s decode | 80% SWE-bench class; fits with ~21 GB headroom; overkill for extraction | [visorcraft](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md) |
| DeepSeek-R1-distill 14B/32B | dense | Q4_K_M | 32B-class dense ≈ 11 t/s (Qwen2.5-32B proxy); 14B ≈ 24 t/s (Qwen2.5-14B proxy) | Dense, slow; superseded by MoE reasoning models | [visorcraft](https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md) |

Key findings:

- **MoE with ~3B active params is the winning shape.** 30B-A3B models decode at ~100 t/s — 2× the 8B dense class and 20× dense 70B — because per-token memory traffic tracks *active* params, not total.
- **Q4 vs Q6:** for MoE, Q4_K_M/Q4_K_S quality on structured extraction matched higher quants in published gates; Q6 costs ~10–15% decode speed for no measured gain on this task type. Q4_K_M (or Unsloth UD-Q4_K_XL) is the right default.
- **Reasoning-mode tax:** enabling extended thinking on 35B-class models pushed time-to-first-answer from ~0.2 s to ~20 s per call ([agmind](https://github.com/botAGI/strix-halo-llm-benchmarks)). For enrichment, use the model's low/no-thinking mode with a well-structured prompt; don't let it free-associate.
- **Concurrency cliff (Vulkan):** llama.cpp Vulkan aggregate throughput drops ~35% going from 8 to 9 parallel slots on 30B MoE (llama.cpp #25356; persists through b10034). For single-stream or ≤4 concurrent enrichment calls this is irrelevant; if the router ever fans out >8 parallel requests, batch or use the density-gate build ([strix-halo-guide MOE_CONCURRENCY](https://github.com/hogeheer499-commits/strix-halo-guide/blob/main/MOE_CONCURRENCY.md)).

---

## 5. Co-residency (grounded in the live boldhalo inventory)

**Live state:** halogen-flash-server runs `qwen3.8-flash-next-w4b-q8-halogen` (Qwen3.8-Flash-Next, W4B + Q8 overlay, ROCm/HIP, 200k context) and stays loaded. Registered but unloaded: deepseek-v4-flash IQ2_XXS (ds4) and UD-IQ2_XXS (llama.cpp Vulkan), qwen3.8-27b UD-Q4_K_XL (llama.cpp ROCm), flash-next Q4 (ds4), flash-next UD-IQ4_XS (llama.cpp Vulkan), flash-next UD-Q4_K_XL and UD-Q4_K_XL mtp-7 (gufo).

### 5.1 What Qwen3.8-Flash-Next actually is

Per Qwen's own release: **125B-parameter main model + 51B n-gram (Engram) embedding table = ~176B total, 6B active per token**, 262K native context ([Qwen blog](https://qwen.ai/blog?id=qwen3.8-flash-next), [SGLang cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-Flash-Next)). The n-gram table is *host-side lookup* memory, not per-token compute — which is why this architecture fits 128 GB while behaving like a 6B-active MoE.

### 5.2 Halogen's memory behavior (from halogen's own docs)

Halogen is a dedicated ROCm/HIP engine for this one model family. Its host-setup doc is blunt: **"This server is built to own its machine."** ([halogen host-setup](https://peonist-ai.github.io/halogen-flash-server/host-setup/))

- **Weights: ~68.0 GiB pinned** (w4b checkpoint; 62.1 GiB for the default checkpoint). Pinned means non-movable; compaction cannot reclaim it.
- **KV pool reserved up front**, sized by `HALOGEN_KV_POOL_POSITIONS` / `HALOGEN_KV_SLOTS` / `HALOGEN_MAX_TOK`. Halogen's own sizing table (default checkpoint; **add ~6 GiB for w4b**):

| Halogen config | Device side | Halogen takes | Host left (128 GB box) |
|---|---|---|---|
| Quickstart defaults (pool 524288, 4 slots, MAX_TOK 32768) | ~27 GiB | ~89 GiB | ~12.4 GiB, mostly non-contiguous |
| pool 262144, 2 slots | ~20 GiB | ~82 GiB | ~20 GiB |
| pool 262144, 2 slots, MAX_TOK 16384 | ~15 GiB | ~77 GiB | ~25 GiB |
| ctx 131072, pool 131072, 2 slots, MAX_TOK 16384 | ~12 GiB | ~74 GiB | ~28 GiB |

- **`free`/`MemAvailable` lie by ~62–68 GiB**: halogen's locked weights are registered as file-backed memory and the kernel counts them as reclaimable page cache. Halogen prints the truth at startup: `host memory left for everything else: N contiguous 2 MiB blocks`. **Size co-tenants to that line, not to `free`.**
- **The 47.7 GiB n-gram lookup table lives in the page cache**, read on demand per request. A co-tenant that evicts it costs ~1.3 s extra on a 32k cold prompt from NVMe. This is the main hidden interaction with a neighbor.
- **Memory-pressure failure mode is ugly**: if a co-tenant takes the room halogen needs to grow, the kernel hunts for contiguous memory and *both sides* stall for minutes at 100% of one core, no disk activity, looks like a hang (halogen issues #79, #83, #85). `HALOGEN_WEIGHTS_LOCK=1` moves the weights out of the reclaim cycle: measured 81/81 requests answered with a 12 GiB co-tenant and <1 GiB host-left, ~5% longer walls. Requires `memlock unlimited` in `/etc/security/limits.conf` (container `--ulimit` alone is not enough on Ubuntu's 8 MiB default).
- **Hardware queue gotcha**: the iGPU goes to 100%-busy-at-idle (~30 W vs 4 W) once >8 hardware compute queues are open across all processes. Halogen holds 2. Start any other GPU server with `GPU_MAX_HW_QUEUES=1` or `2`.
- **NPU + GPU concurrency**: halogen's docs warn GPU+NPU simultaneous work "can otherwise hang a Strix Halo machine" unless the GPU fabric clock is held at top speed (halogen does this itself with root/host-sys access). With the clock held, the Flash model runs "somewhat slower" while the NPU works.

### 5.3 Can a second llama.cpp server coexist with halogen?

**Technically yes — the driver multiprocesses fine (halogen itself runs as a container sharing /dev/kfd + /dev/dri) — but halogen's own recommendation is a dedicated machine, and the math agrees.** With the Quickstart 200k config you get ~12.4 GiB of genuinely-free host memory. A 4B Q4 llama.cpp server needs ~2.5–3.5 GiB weights + ~1–2 GiB KV ≈ 5 GiB. It *fits* the 12 GiB budget, but leaves ~7 GiB for OS + router + page cache for the 47.7 GiB lookup table — which is exactly the pressure that produces halogen's stall mode.

**The clean answer is halogen's own feature: run the triage model on the NPU, inside the halogen server, behind the same port.** Halogen supports small models on the XDNA 2 NPU via `HALOGEN_NPU_MODELS=`: `decider-0.8b` (decision/classification), `qwen3-embedding-0.6b`, `qwen3-reranker-0.6b`, `qwen3guard-gen-0.6b`, `qwen3.5-2b`, plus ASR/TTS and image gen, and **your own fine-tune of the first four** ([halogen NPU small models](https://peonist-ai.github.io/halogen-flash-server/npu-small-models/)). It even ships a `/classify` endpoint and a "Using it as a classifier" doc ([CLASSIFY.md](https://github.com/peonist-ai/halogen-flash-server/blob/main/docs/CLASSIFY.md)). Triage = one label out = exactly `decider-0.8b`'s job. NPU runs on its own silicon; the only cost is the Flash model's "somewhat slower" decode while the NPU is busy, and the fabric-clock requirement (handled by halogen's host unit).

**Budget check (128 GB unified, halogen w4b + 200k):**

| Resident | Footprint |
|---|---|
| Halogen weights (w4b, pinned) | 68.0 GiB |
| Halogen KV pool (200k, 2 slots) | ~15–20 GiB |
| Halogen n-gram table (page cache, evictable) | 47.7 GiB (want resident) |
| NPU triage model (0.8B, halogen-managed) | ~1 GiB |
| OS + router + app | ~8–10 GiB |
| **Total** | **~140 GiB demand vs 128 GB** |

The n-gram table is the squeeze: it *wants* 47.7 GiB of page cache but is evictable, and cold-read cost is only ~1.3 s per 32k prompt. Practical resolution: **shrink halogen's KV pool** (2 slots, MAX_TOK 16384 → halogen takes ~77+6 ≈ 83 GiB) so ~45 GiB remains for OS + router + lookup-table cache. Triage on NPU costs no GPU memory. This is the configuration to verify first.

### 5.4 Fallback: CPU-only triage

If NPU-in-halogen is unavailable (no XRT/driver, or the fabric-clock hold conflicts with your setup), run the triage model CPU-only in a separate llama.cpp server:

- Strix Halo CPU: 16 Zen 5 cores / 32 threads. CPU-only inference on this class of hardware for a 1.7B Q4 model is roughly **25–40 t/s aggregate** (16 threads); a 4B Q4 roughly **12–20 t/s**. [UNVERIFIED for this exact box — no published CPU-only Strix Halo small-model numbers found; extrapolated from CPU-only llama.cpp community data.]
- At ~200 prompt tokens per listing: 1.7B CPU-only ≈ 5–8 s per listing → ~100 listings in 9–13 min. Tolerable for a nightly/batch sweep, not for interactive triage.
- CPU-only keeps the GPU 100% to halogen, zero co-residency risk. If triage volume is high and interactive, prefer the NPU route.

### 5.5 What NOT to do

- Do not load a second large model (27B/35B/235B) alongside halogen — the 12 GiB free cannot hold it, and the OOM killer will pick halogen (largest resident set, locked weights count) → exit 137 loop.
- Do not trust `free`/`MemAvailable` for sizing; use halogen's `host memory left` startup line.
- Do not run halogen without `HALOGEN_WEIGHTS_LOCK=1` if anything else lives on the host.
- Do not open >8 total GPU compute queues (set `GPU_MAX_HW_QUEUES` on co-tenants).

---

## 6. Recommendation

**One concrete stack (halogen stays loaded):**

| Slot | Choice |
|---|---|
| OS | Linux (kernel ≥ 6.19, Mesa/RADV ≥ 26.x via a current PPA) |
| Enrichment runtime | **halogen-flash-server** (ROCm/HIP), pinned image, `qwen3.8-flash-next-w4b-q8-halogen` — already loaded, stays loaded |
| Halogen config | `HALOGEN_WEIGHTS_LOCK=1` + `memlock unlimited`; shrink KV pool to 2 slots / `HALOGEN_MAX_TOK=16384` to free ~45 GiB host RAM for the n-gram table + OS + router |
| Triage model | **`decider-0.8b` on the NPU, served by halogen itself** (`HALOGEN_NPU_MODELS=decider-0.8b`, `/classify` endpoint). Fallback: Qwen3-4B-Instruct-2507 Q4_K_M in a CPU-only llama.cpp server |
| Quantization | Fixed by the halogen checkpoint (W4B+Q8); triage Q4 0.8B is halogen-managed |
| ROCm | Already present (halogen needs it) |
| Second GPU server | **No.** Do not co-load a second large model with halogen |

**Why this stack:**

1. Halogen owns the GPU by design (~68 GiB pinned weights + reserved KV + 47.7 GiB page-cached n-gram table). Fighting that with a second GPU process invites the stall mode its own docs describe. The router's job becomes: triage → NPU (via halogen), enrichment → GPU (via halogen), one server, one port, no swap.
2. Halogen ships the exact triage primitive (`decider-0.8b` + `/classify`) and supports fine-tuning it on your own data — the right long-term path for match/not-match/unsure labels.
3. The 6B-active Flash-Next model is a strong enrichment model at 200k context; the user already likes it. Keep it.
4. NPU triage costs zero GPU memory and runs concurrently with GPU enrichment; the only coupling is halogen's "somewhat slower" Flash decode while the NPU is busy — measure it, but for 200-token classification bursts it should be negligible.

**Verify first (in order, on the actual box):**

1. **Halogen startup line**: record `host memory left for everything else` with the current 200k config. If < 10 GiB, shrink the KV pool per §5.2 before adding anything.
2. **NPU availability**: XRT + NPU driver present, fabric-clock hold working (halogen refuses to start without it — that's your gate). Then smoke `decider-0.8b` via `/classify` on 20 real listings.
3. **Triage accuracy**: labeled sample of real listings vs `decider-0.8b` output; target ≥95% agreement. If the 0.8B underperforms, fine-tune it (halogen supports custom fine-tunes of the decider) before considering a bigger triage model.
4. **Concurrent-load interference**: run triage (NPU) at full sweep rate while enrichment (GPU) is decoding; measure Flash decode delta vs idle-NPU baseline. If the slowdown is material, throttle triage concurrency or fall back to CPU-only triage.
5. **`HALOGEN_WEIGHTS_LOCK=1`**: set it, confirm `Mlocked`/`Unevictable` carry the weights, confirm no output change.
6. **Sustained thermals**: 2 h continuous mixed NPU+GPU load, watch clocks and the halogen watchdog log lines.

**What would change the recommendation:** if NPU support is absent/broken on your unit, CPU-only 1.7B triage (§5.4) is the fallback — batch-oriented, ~100 listings per 10 min. If triage quality needs >4B, that's the point to reconsider the whole layout (e.g. a second machine for triage, or moving enrichment to a leaner model to free GPU memory).

---

## Sources

- Minisforum MS-S1 Max official: https://www.minisforum.com/products/ms-s1-max
- Minisforum MS-S1 MAX-P495 (PRO 495 variant): https://store.minisforum.com/products/minisforum-ms-s1-max-p495-ai-workstation
- HotHardware announcement (CPU/GPU/RAM confirmation): https://hothardware.com/news/minisforum-ms-s1-max-mini-pc-announced
- AMD Ryzen AI Max+ 395 product page: https://www.amd.com/en/products/processors/laptop/ryzen/ai-300-series/amd-ryzen-ai-max-plus-395.html
- ROCm Radeon/Ryzen compatibility matrices: https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-6.4.4/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html and https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html
- ROCm Strix Halo system optimization: https://rocm.docs.amd.com/en/docs-7.2.0/how-to/system-optimization/strixhalo.html
- Strix Halo LLM Inference Benchmarks (HF dataset, gfx1151): https://huggingface.co/datasets/NorthstarAurora/strix-halo-bench-data
- strix-halo-guide (benchmark source-of-truth, Oct 2026): https://github.com/hogeheer499-commits/strix-halo-guide (BENCHMARKS.md, CURRENT_MODELS.md)
- visorcraft strix-halo-llm-perf (Vulkan vs ROCm, TDP study): https://github.com/visorcraft/strix-halo-llm-perf/blob/main/BENCHMARKS.md
- botAGI / AGmind measured benchmarks (TTFA, JSON, endurance): https://github.com/botAGI/strix-halo-llm-benchmarks
- Ollama Strix Halo ROCm guide: https://github.com/ollama/ollama/issues/14855
- DataHardware Strix Halo tokens/sec (bandwidth analysis): https://datahardware.ai/blog/strix-halo-tokens-per-second-2026
- Codersera Strix Halo setup guide: https://codersera.com/blog/amd-strix-halo-ryzen-ai-max-local-llm-setup-2026/
- AMD AI Playbook — LM Studio + ROCm: https://developer.amd.com/playbooks/lmstudio-rocm-llms/
- Ryzen AI Software docs (NPU/OGA LLM deployment): https://ryzenai.docs.amd.com/en/latest/llm/overview.html
- FastFlowLM (NPU runtime): https://github.com/ROCm/FastFlowLM
- RyzenAI-SW: https://github.com/amd/RyzenAI-SW
- On-device tool-calling small-model comparison: https://www.ertas.ai/blog/on-device-tool-calling-2026-qwen3-gemma4-phi4
- Bonsai Vulkan Strix Halo community bench: https://github.com/PrismML-Eng/Bonsai-demo/blob/97ec2057763ab83faf6eb794b92cb0e333b8dd7d/community-benchmarks/bonsai/vulkan-strix-halo-128gb-archlinux.md
- halogen-flash-server docs: https://peonist-ai.github.io/halogen-flash-server/
- halogen-flash-server repo: https://github.com/peonist-ai/halogen-flash-server
- halogen host setup (memory behavior, sharing, watchdog): https://peonist-ai.github.io/halogen-flash-server/host-setup/
- halogen small models on NPU: https://peonist-ai.github.io/halogen-flash-server/npu-small-models/
- halogen weights (HF): https://huggingface.co/peonist-ai/halogen-qwen3.8-flash-next
- Qwen3.8-Flash-Next official (125B + 51B n-gram, 6B active): https://qwen.ai/blog?id=qwen3.8-flash-next
- Qwen3.8-Flash-Next SGLang cookbook: https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-Flash-Next
