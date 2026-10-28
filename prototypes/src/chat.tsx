// Chat-page UX prototype — wayfinder #21.
// Three structural takes on the streaming chat surface, switchable with
// ?chat=a|b|c, driven by a fake chat-turn SSE (chatSim.ts).
//
//   A  inline waterfall: one linear column. Thinking, tool chips, draft cards
//      all land in the stream exactly where the event happened.
//   B  status rail: turn machinery (thinking + tool chips) lives in a fixed
//      rail above the transcript; the stream stays clean prose.
//   C  inspector: transcript is foreground; a right-hand panel holds live
//      tool/thinking state, auto-opening when activity starts.
//
// The reasoning channel is a SEPARATE axis, toggled with ?reason=show|hide
// across all three variants — that is the decision #21 exists to settle.
// Draft-confirm (the old /confirm path restaged in chat) is present in all
// three via the "Draft turn" scenario: preview → edit inline → save/discard.
// Throwaway. Fake data inline; no backend calls.

import { useEffect, useRef, useState } from "react";
import { patchUrl } from "./filters";
import {
  streamTurn,
  SCENARIO_KEYS,
  SCENARIO_LABELS,
  type Draft,
  type SimEvent,
} from "./chatSim";
import "./chat.css";

// ---------------------------------------------------------------- turn state

interface TurnTool {
  name: string;
  chip: string;
  status: "running" | "done" | "failed";
}

interface Turn {
  text: string;
  reasoning: string;
  tools: TurnTool[];
  draft: Draft | null;
  error: string | null;
  streaming: boolean;
}

const EMPTY_TURN: Turn = {
  text: "",
  reasoning: "",
  tools: [],
  draft: null,
  error: null,
  streaming: false,
};

// The client turn reducer (docs/migration-plan.md) folded over fake events.
function reduce(turn: Turn, e: SimEvent): Turn {
  switch (e.type) {
    case "token":
      return { ...turn, text: turn.text + e.text };
    case "reasoning":
      return { ...turn, reasoning: turn.reasoning + e.text };
    case "tool_call":
      return {
        ...turn,
        tools: [
          ...turn.tools,
          { name: e.data.name, chip: `${e.data.name}…`, status: "running" },
        ],
      };
    case "tool_result": {
      // complete the oldest still-running chip with this name
      let done = false;
      return {
        ...turn,
        tools: turn.tools.map((t) => {
          if (!done && t.name === e.data.name && t.status === "running") {
            done = true;
            return { ...t, chip: e.data.chip, status: "done" as const };
          }
          return t;
        }),
      };
    }
    case "draft":
      return { ...turn, draft: e.data };
    case "turn_complete":
      return { ...turn, streaming: false };
    case "error":
      return { ...turn, streaming: false, error: e.message };
  }
}

// A committed chat log entry. Drafts are their own entries so they keep
// their own phase state independent of the turn that produced them.
type Entry =
  | { kind: "user"; text: string }
  | { kind: "agent"; text: string; reasoning: string; tools: TurnTool[] }
  | { kind: "draft"; draft: Draft }
  | { kind: "error"; message: string };

// ---------------------------------------------------------------- shared bits

function ThinkingBlock({ text, live }: { text: string; live: boolean }) {
  if (!text) return null;
  return (
    <details className={`ct-think ${live ? "ct-think-live" : ""}`}>
      <summary>Thinking</summary>
      <div className="ct-think-body">{text}</div>
    </details>
  );
}

function ToolChip({ t }: { t: TurnTool }) {
  const cls =
    t.status === "running"
      ? "ct-chip-run"
      : t.status === "done"
        ? "ct-chip-done"
        : "ct-chip-fail";
  return (
    <span className={`ct-chip ${cls}`}>
      {t.status === "running" ? <span className="ct-dot" /> : "✓"}
      {t.chip}
    </span>
  );
}

function Spinner() {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: "var(--accent)",
        display: "inline-block",
        animation: "ct-pulse 1s infinite",
      }}
    />
  );
}

// Draft card lifecycle: preview → edit → saved | discarded.
type DraftPhase = "preview" | "edit" | "saved" | "discarded";

function DraftBlock({
  draft: initial,
  phase,
  setPhase,
}: {
  draft: Draft;
  phase: DraftPhase;
  setPhase: (p: DraftPhase) => void;
}) {
  const [d, setD] = useState<Draft>(initial);

  if (phase === "saved")
    return (
      <p className="ct-saved">
        ✓ Saved “{d.summary}” — fanning out across 3 marketplaces.
      </p>
    );
  if (phase === "discarded")
    return <p className="muted" style={{ fontSize: 13 }}>Draft discarded.</p>;

  if (phase === "preview")
    return (
      <div className="ct-draft">
        <h3>💰 Draft Bargain Search: {initial.summary}</h3>
        <div className="ct-draft-row">
          <span className="k">Product</span>
          <span>{initial.product_identity}</span>
        </div>
        <div className="ct-draft-row">
          <span className="k">Target price</span>
          <span>${initial.target_price}</span>
        </div>
        <div className="ct-draft-row">
          <span className="k">Locality</span>
          <span>{initial.location}</span>
        </div>
        <div className="ct-draft-row">
          <span className="k">Queries</span>
          <span>{initial.queries.join(", ")}</span>
        </div>
        <div className="ct-draft-row">
          <span className="k">Exclusions</span>
          <span>{initial.exclusions.join(", ")}</span>
        </div>
        <div className="ct-draft-actions">
          <button onClick={() => setPhase("discarded")}>Discard</button>
          <button onClick={() => setPhase("edit")}>✎ Edit</button>
          <button className="btn-primary" onClick={() => setPhase("saved")}>
            Save as-is
          </button>
        </div>
      </div>
    );

  return (
    <div className="ct-draft">
      <h3>✎ Edit draft</h3>
      <div className="ct-draft-edit">
        <label>
          Summary
          <input
            value={d.summary}
            onChange={(e) => setD({ ...d, summary: e.target.value })}
          />
        </label>
        <label>
          Product identity
          <input
            value={d.product_identity}
            onChange={(e) => setD({ ...d, product_identity: e.target.value })}
          />
        </label>
        <label>
          Target price
          <input
            value={String(d.target_price ?? "")}
            inputMode="decimal"
            onChange={(e) =>
              setD({
                ...d,
                target_price: e.target.value === "" ? null : Number(e.target.value),
              })
            }
          />
        </label>
        <label>
          Locality
          <input
            value={d.location}
            onChange={(e) => setD({ ...d, location: e.target.value })}
          />
        </label>
        <label>
          Queries (comma-separated)
          <input
            defaultValue={d.queries.join(", ")}
            onChange={(e) =>
              setD({
                ...d,
                queries: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
        <label>
          Exclusions (comma-separated)
          <input
            defaultValue={d.exclusions.join(", ")}
            onChange={(e) =>
              setD({
                ...d,
                exclusions: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
      </div>
      <div className="ct-draft-actions">
        <button onClick={() => setPhase("discarded")}>Discard</button>
        <button className="btn-primary" onClick={() => setPhase("saved")}>
          Save Bargain Search
        </button>
      </div>
    </div>
  );
}

function ScenarioPicker({ onPick }: { onPick: (k: string) => void }) {
  return (
    <div className="ct-scenarios">
      {SCENARIO_KEYS.map((k) => (
        <button key={k} onClick={() => onPick(k)}>
          ▶ {SCENARIO_LABELS[k]}
        </button>
      ))}
    </div>
  );
}

function Composer({
  streaming,
  onSend,
  onStop,
}: {
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const send = () => {
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  };
  return (
    <div className="ct-composer">
      <textarea
        value={text}
        placeholder="Ask the agent anything… (Enter sends)"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
      />
      {streaming ? (
        <button className="ct-stop" onClick={onStop}>
          ■ Stop
        </button>
      ) : (
        <button className="btn-primary" onClick={send}>
          Send
        </button>
      )}
    </div>
  );
}

function ErrorStrip({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="ct-error">
      <span>⚠ {message}</span>
      <button onClick={onRetry}>↻ Retry</button>
    </div>
  );
}

// Hook: shared chat log + turn runner for all three variants.
function useChatLog(defaultScenario: string) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [turn, setTurn] = useState<Turn>(EMPTY_TURN);
  const [busy, setBusy] = useState(false);
  const cancelRef = useRef<() => void>(() => {});
  const scrollRef = useRef<HTMLDivElement>(null);

  const commit = (t: Turn) =>
    setEntries((m) => [
      ...m,
      ...(t.text || t.reasoning || t.tools.length
        ? [
            {
              kind: "agent" as const,
              text: t.text,
              reasoning: t.reasoning,
              tools: t.tools,
            },
          ]
        : []),
      ...(t.draft ? [{ kind: "draft" as const, draft: t.draft }] : []),
      ...(t.error ? [{ kind: "error" as const, message: t.error }] : []),
    ]);

  const run = (key: string) => {
    setBusy(true);
    setTurn(EMPTY_TURN);
    cancelRef.current = streamTurn(key, (e) => {
      setTurn((prev) => {
        const next = reduce(prev, e);
        if (e.type === "turn_complete" || e.type === "error") {
          setBusy(false);
          commit(next);
          return EMPTY_TURN;
        }
        return next;
      });
    });
  };

  // auto-scroll to keep the live tail visible
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turn.text, turn.tools.length, entries.length]);

  const send = (text: string) => {
    setEntries((m) => [...m, { kind: "user", text }]);
    run(defaultScenario);
  };

  // Stop = keep what arrived, commit it, drop the live preview.
  const stop = () => {
    cancelRef.current();
    setBusy(false);
    commit(turn);
    setTurn(EMPTY_TURN);
  };

  return { entries, turn, busy, run, send, stop, scrollRef };
}

// ============================================================ VARIANT A
// Classic waterfall: one column; every event lands inline where it happened.
function ChatA({
  showReasoning,
  scenarioKey,
  onPick,
}: {
  showReasoning: boolean;
  scenarioKey: string;
  onPick: (k: string) => void;
}) {
  const { entries, turn, busy, run, send, stop, scrollRef } =
    useChatLog("draft");
  const [phases, setPhases] = useState<Record<number, DraftPhase>>({});

  return (
    <div className="va-wrap">
      <div className="ct-scroll" ref={scrollRef}>
        <ScenarioPicker
          onPick={(k) => {
            onPick(k);
            run(k);
          }}
        />
        {entries.map((en, i) => {
          if (en.kind === "user")
            return (
              <div key={i} className="ct-msg ct-user">
                {en.text}
              </div>
            );
          if (en.kind === "agent")
            return (
              <div key={i} className="ct-msg">
                <div className="ct-role">Agent</div>
                {showReasoning && <ThinkingBlock text={en.reasoning} live={false} />}
                {en.tools.length > 0 && (
                  <div className="ct-tools">
                    {en.tools.map((t, j) => (
                      <ToolChip key={j} t={t} />
                    ))}
                  </div>
                )}
                {en.text}
              </div>
            );
          if (en.kind === "error")
            return (
              <div key={i} className="ct-msg">
                <ErrorStrip message={en.message} onRetry={() => run(scenarioKey)} />
              </div>
            );
          return (
            <div key={i} className="ct-msg">
              <DraftBlock
                draft={en.draft}
                phase={phases[i] ?? "preview"}
                setPhase={(p) => setPhases((m) => ({ ...m, [i]: p }))}
              />
            </div>
          );
        })}
        {busy && (
          <div className="ct-msg">
            <div className="ct-role">Agent</div>
            {showReasoning && (
              <ThinkingBlock text={turn.reasoning} live={!turn.text} />
            )}
            {turn.tools.length > 0 && (
              <div className="ct-tools">
                {turn.tools.map((t, i) => (
                  <ToolChip key={i} t={t} />
                ))}
              </div>
            )}
            {turn.text ? (
              <span className="ct-caret">{turn.text}</span>
            ) : (
              turn.tools.length === 0 && (
                <div className="va-tail">
                  <Spinner /> thinking…
                </div>
              )
            )}
          </div>
        )}
      </div>
      <Composer streaming={busy} onSend={send} onStop={stop} />
    </div>
  );
}

// ============================================================ VARIANT B
// Status rail above the transcript: tools + thinking live in the rail,
// never in the stream. Draft still lands inline (it's content, not machinery).
function ChatB({
  showReasoning,
  scenarioKey,
  onPick,
}: {
  showReasoning: boolean;
  scenarioKey: string;
  onPick: (k: string) => void;
}) {
  const { entries, turn, busy, run, send, stop, scrollRef } =
    useChatLog("draft");
  const [phases, setPhases] = useState<Record<number, DraftPhase>>({});

  return (
    <div className="vb-wrap">
      <div className="vb-rail">
        <span className="vb-rail-label">{busy ? "Working" : "Idle"}</span>
        {busy && turn.tools.length === 0 && (
          <span className="ct-chip ct-chip-run">
            <span className="ct-dot" /> warming up…
          </span>
        )}
        {turn.tools.map((t, i) => (
          <ToolChip key={i} t={t} />
        ))}
      </div>
      {showReasoning && turn.reasoning && (
        <div className="vb-thinking-strip">🧠 {turn.reasoning}</div>
      )}
      <div className="ct-scroll" ref={scrollRef}>
        <ScenarioPicker
          onPick={(k) => {
            onPick(k);
            run(k);
          }}
        />
        {entries.map((en, i) => {
          if (en.kind === "user")
            return (
              <div key={i} className="ct-msg ct-user">
                {en.text}
              </div>
            );
          if (en.kind === "agent")
            return (
              <div key={i} className="ct-msg">
                <div className="ct-role">Agent</div>
                {en.text}
              </div>
            );
          if (en.kind === "error")
            return (
              <div key={i} className="ct-msg">
                <ErrorStrip message={en.message} onRetry={() => run(scenarioKey)} />
              </div>
            );
          return (
            <div key={i} className="ct-msg">
              <DraftBlock
                draft={en.draft}
                phase={phases[i] ?? "preview"}
                setPhase={(p) => setPhases((m) => ({ ...m, [i]: p }))}
              />
            </div>
          );
        })}
        {busy && turn.text && (
          <div className="ct-msg">
            <div className="ct-role">Agent</div>
            <span className="ct-caret">{turn.text}</span>
          </div>
        )}
      </div>
      <Composer streaming={busy} onSend={send} onStop={stop} />
    </div>
  );
}

// ============================================================ VARIANT C
// Inspector: live machinery lives in the right-hand panel; the transcript
// carries prose + inline drafts only. Panel auto-opens on tool activity.
function ChatC({
  showReasoning,
  scenarioKey,
  onPick,
}: {
  showReasoning: boolean;
  scenarioKey: string;
  onPick: (k: string) => void;
}) {
  const { entries, turn, busy, run, send, stop, scrollRef } =
    useChatLog("draft");
  const [open, setOpen] = useState(false);
  const [phases, setPhases] = useState<Record<number, DraftPhase>>({});
  // phone: auto-open while tools are active; user can still close it
  useEffect(() => {
    if (turn.tools.length > 0) setOpen(true);
  }, [turn.tools.length]);

  return (
    <div className="vc-wrap">
      <div className="vc-main">
        <div className="ct-scroll" ref={scrollRef}>
          <ScenarioPicker
            onPick={(k) => {
              onPick(k);
              run(k);
            }}
          />
          {entries.map((en, i) => {
            if (en.kind === "user")
              return (
                <div key={i} className="ct-msg ct-user">
                  {en.text}
                </div>
              );
            if (en.kind === "agent")
              return (
                <div key={i} className="ct-msg">
                  <div className="ct-role">Agent</div>
                  {en.text}
                </div>
              );
            if (en.kind === "error")
              return (
                <div key={i} className="ct-msg">
                  <ErrorStrip
                    message={en.message}
                    onRetry={() => run(scenarioKey)}
                  />
                </div>
              );
            return (
              <div key={i} className="ct-msg">
                <DraftBlock
                  draft={en.draft}
                  phase={phases[i] ?? "preview"}
                  setPhase={(p) => setPhases((m) => ({ ...m, [i]: p }))}
                />
              </div>
            );
          })}
          {busy && (
            <div className="ct-msg">
              <div className="ct-role">Agent</div>
              {turn.text ? (
                <span className="ct-caret">{turn.text}</span>
              ) : (
                <div className="va-tail">
                  <Spinner /> working — open the inspector to watch.
                </div>
              )}
            </div>
          )}
        </div>
        <Composer streaming={busy} onSend={send} onStop={stop} />
      </div>
      <aside className={`vc-panel ${open ? "open" : ""}`}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 8,
          }}
        >
          <h4 style={{ margin: 0 }}>Inspector</h4>
          <button onClick={() => setOpen(false)} aria-label="Close inspector">
            ✕
          </button>
        </div>
        {turn.tools.length === 0 && !busy && (
          <p className="muted" style={{ fontSize: 13 }}>
            Idle. Live tool activity appears here.
          </p>
        )}
        {turn.tools.map((t, i) => (
          <div
            key={i}
            className={`vc-card ${
              t.status === "running" ? "vc-card-running" : "vc-card-done"
            }`}
          >
            <strong>{t.name}</strong>
            <div className="muted">{t.chip}</div>
          </div>
        ))}
        {showReasoning && turn.reasoning && (
          <div className="vc-card">
            <strong>🧠 Reasoning</strong>
            <div className="muted" style={{ whiteSpace: "pre-wrap" }}>
              {turn.reasoning}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- host

export default function ChatPage({
  variant,
}: {
  variant: "a" | "b" | "c";
}) {
  const q = new URLSearchParams(window.location.search);
  const showReasoning = q.get("reason") !== "hide";
  const scenario = q.get("scenario") ?? "simple";

  const V = variant === "b" ? "B" : variant === "c" ? "C" : "A";
  const Chat = variant === "b" ? ChatB : variant === "c" ? ChatC : ChatA;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        // viewport minus page top padding (14px) and the switcher zone (~82px)
        height: "calc(100vh - 96px)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 14px",
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
          flex: "none",
        }}
      >
        <h1 style={{ margin: 0, fontSize: 16 }}>💬 Chat · variant {V}</h1>
        <button
          onClick={() => patchUrl({ reason: showReasoning ? "hide" : "show" })}
        >
          🧠 reasoning: {showReasoning ? "shown" : "hidden"}
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <Chat
          showReasoning={showReasoning}
          scenarioKey={scenario}
          onPick={(k) => patchUrl({ scenario: k })}
        />
      </div>
    </div>
  );
}
