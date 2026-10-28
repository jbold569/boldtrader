// Fake chat-turn SSE simulator for wayfinder #21.
// Emits the exact BoldTrader contract events (docs/api-contract.md): token,
// reasoning, tool_call, tool_result, draft, turn_complete, error. Frames are
// paced with real timers so streaming rhythm is *experienced*, not asserted.
//
// shortcut: scripted scenarios, no model in the loop; upgrade when the real
// /api/v1 chat-turn endpoint (M1) exists and this feeds off the wire.

export type ToolCall = { name: string; arguments: Record<string, unknown> };
export type ToolResult = { name: string; output: string; chip: string };
export type Draft = {
  summary: string;
  product_identity: string;
  queries: string[];
  exclusions: string[];
  target_price: number | null;
  location: string;
};

export type SimEvent =
  | { type: "token"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "tool_call"; data: ToolCall }
  | { type: "tool_result"; data: ToolResult }
  | { type: "draft"; data: Draft }
  | { type: "turn_complete"; text: string }
  | { type: "error"; code: string; message: string };

// Each scenario = [pauseMsBeforeThisFrame, event] pairs. First delay 0.
type Frame = [number, SimEvent];

// Split text into stream-ish chunks: words of 1-3, like real token deltas.
function chunks(text: string): string[] {
  const words = text.split(/(?<=\s)/);
  const out: string[] = [];
  for (let i = 0; i < words.length; i += 2) {
    out.push(words.slice(i, i + 2).join(""));
  }
  return out;
}

function tokenFrames(text: string, pace = 55): Frame[] {
  return chunks(text).map((c) => [pace, { type: "token", text: c } as SimEvent]);
}

const DRAFT_1: Draft = {
  summary: "HP Z440 workstations under $300",
  product_identity: "HP Z440",
  queries: ["hp z440", "z440 workstation"],
  exclusions: ["no monitor"],
  target_price: 300,
  location: "Kenmore, WA",
};

// S1: simple question, no tools, no draft.
const S_SIMPLE: Frame[] = [
  [0, { type: "reasoning", text: "The user is asking a factual question about DDR4 pricing. I have recent price observations in context; no tool needed." }],
  ...tokenFrames(
    "DDR4 3200 16GB modules are running about $35–45 used right now. The market loosened over the past month as the DDR5 transition matured; for-parts sticks stay near $30. If you're buying in lots of 8+, you can push under $30 per stick."
  ),
  [20, { type: "turn_complete", text: "done" }],
];

// S2: research turn — reasoning, tool calls with results, no draft.
const S_RESEARCH: Frame[] = [
  [0, { type: "reasoning", text: "Need current listings for Xeon E5 bundles. I'll run a web search and check the Listing Store for what we already have." }],
  [400, { type: "tool_call", data: { name: "web_search", arguments: { query: "Xeon E5 workstation bundle price" } } }],
  [1600, { type: "tool_result", data: { name: "web_search", output: "12 results", chip: 'web search: "Xeon E5 bundle" — 12 results' } }],
  [300, { type: "tool_call", data: { name: "listing_store_search", arguments: { query: "xeon e5", max_price: 200 } } }],
  [2200, { type: "tool_result", data: { name: "listing_store_search", output: "7 listings", chip: 'listing store: "xeon e5" — 7 listings, 3 under $200' } }],
  ...tokenFrames(
    "Across the web and our Listing Store: E5-2680 v4 dual-socket towers with 64GB RAM are clustering at $180–220 this week. Three under $200 already in the store — two Dell T5810s and one HP Z640. The wave of corporate decommissions is clearly landing; I'd expect more of the same for the next few weeks."
  ),
  [20, { type: "turn_complete", text: "done" }],
];

// S3: the draft turn — reasoning, tool, draft, and the user confirms later.
const S_DRAFT: Frame[] = [
  [0, { type: "reasoning", text: "User wants HP Z440 machines under $300 near Kenmore. Local marketplaces need a locality; eBay doesn't. Building the draft: queries should cover model-number sellers and vague-title sellers both." }],
  [500, { type: "tool_call", data: { name: "web_search", arguments: { query: "HP Z440 price used workstation" } } }],
  [1400, { type: "tool_result", data: { name: "web_search", output: "12 results", chip: 'web search: "HP Z440" — 12 results' } }],
  ...tokenFrames(
    "Z440s are plentiful right now — complete units with Xeon E5-2620 v3 and 16GB ask $280–380, and the good ones go fast. Under $300 is a fair target for a complete machine. I've drafted a Bargain Search:"
  ),
  [300, { type: "draft", data: DRAFT_1 }],
  ...tokenFrames("Review the draft below — edit anything, then save it to start the hunt."),
  [20, { type: "turn_complete", text: "done" }],
];

// S4: long response — stress test for typewriter + scroll.
const LONG_TEXT =
  "Here's the full picture on the RTX 3060 bundle market. Asking prices for 12GB cards in complete bundles have drifted down from their $340 peak in August to a $285 median this month. The supply side tells the story: three regional ITADs cleared inventory at once, and bundle-heavy listings (card + PSU + case) now make up roughly 40% of new arrivals — up from 22% last quarter. That matters for flip-value math. A bundle where you don't need the PSU or case gets those subtracted from the out-the-door price before comparing against fair price, so a $310 bundle with a $60 flip value on the extras is really a $250 card — comfortably a deal against the $285 median. Watch for the mirror case: cards listed inside gaming PCs. The tower's fair price eats most of the margin unless the CPU/RAM are worth more than the asking minus the card. On condition: refurb 3060s carry warranty value and should be compared at the refurb price band, not against plain complete — a 10% discount on a refurb is not automatically the better buy. Two live risks tonight. First, the wave may be one big ITAD clearing rather than a trend; if tomorrow's arrivals thin, expect prices to bounce back above $300 within a week. Second, several sellers are pricing at the surged level and calling it a bargain — anchor to our own recorded observations, not their 'was $450' strikethroughs. Recommendation: set the deal threshold at 15% below fair for this product, which is where our observations stop being noisy, and prefer complete-with-warranty over bare card unless the flip value on the bundle carries the difference.";

const S_LONG: Frame[] = [
  [0, { type: "reasoning", text: "Long-form market analysis requested. Pulling from price observations, supply patterns, and flip-value considerations. Structure: price level → supply → flip math → condition → risks → recommendation." }],
  ...tokenFrames(LONG_TEXT, 40),
  [20, { type: "turn_complete", text: "done" }],
];

// S5: error mid-turn — router dies after some tokens.
const S_ERROR: Frame[] = [
  [0, { type: "reasoning", text: "Scanning the request... looks like a simple lookup, I'll pull recent" }],
  ...tokenFrames("Sure — the top deals right now are a Z640 at $175 and an OptiPlex 7040 at $140, bot"),
  [900, { type: "error", code: "router_unavailable", message: "Model router connection lost mid-turn." }],
];

const SCENARIOS: Record<string, { label: string; frames: Frame[] }> = {
  simple: { label: "Simple answer", frames: S_SIMPLE },
  research: { label: "Tool-call turn", frames: S_RESEARCH },
  draft: { label: "Draft turn", frames: S_DRAFT },
  long: { label: "Long response", frames: S_LONG },
  error: { label: "Error mid-turn", frames: S_ERROR },
};

export const SCENARIO_KEYS = Object.keys(SCENARIOS);
export const SCENARIO_LABELS = Object.fromEntries(
  Object.entries(SCENARIOS).map(([k, v]) => [k, v.label])
);

export function streamTurn(
  key: string,
  onEvent: (e: SimEvent) => void
): () => void {
  const frames = (SCENARIOS[key] ?? SCENARIOS.simple).frames;
  let i = 0;
  let timer: ReturnType<typeof setTimeout>;
  const step = () => {
    if (i >= frames.length) return;
    const [delay, ev] = frames[i++];
    timer = setTimeout(() => {
      onEvent(ev);
      if (i < frames.length && ev.type !== "error") step();
    }, delay);
  };
  step();
  return () => clearTimeout(timer);
}
