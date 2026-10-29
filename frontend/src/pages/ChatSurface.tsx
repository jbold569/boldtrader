// Chat surface (ticket #49): `/` lands in a fresh Chat Session; `/chat/:id`
// deep-links one. All turn folding lives in turnReducer.ts — this component
// owns I/O: streaming turns, stop (client-side abort), regenerate, and
// recovery (a dead stream re-GETs the persisted session; no replay).

import DraftCard, { draftKey } from "../components/DraftCard";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  createChatSession,
  getChatSession,
  streamChatTurn,
} from "../api/client";
import type { ChatMessage, Draft, Search } from "../api/types";
import {
  clearError,
  emptyTurn,
  reduce,
  type ChatViewMessage,
  type TurnState,
} from "../turnReducer";
import { markViewed, type ViewedMap } from "../unread";
import "./chat.css";

// --- minimal markdown (bold, italics, inline code, links, fenced code) ----
// react-markdown is not a dependency by design; this covers what the agent
// emits. pre-wrap carries line breaks, so only fences are block-parsed.

function inlineMd(text: string, keyBase: string): ReactNode[] {
  const re =
    /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*\n]+)\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = `${keyBase}-${k++}`;
    if (m[1] !== undefined) out.push(<code key={key}>{m[1]}</code>);
    else if (m[2] !== undefined) out.push(<strong key={key}>{m[2]}</strong>);
    else if (m[3] !== undefined) out.push(<em key={key}>{m[3]}</em>);
    else
      out.push(
        <a key={key} href={m[4]} target="_blank" rel="noreferrer">
          {m[5]}
        </a>,
      );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function renderMd(text: string): ReactNode {
  const fence = /```[^\n]*\n([\s\S]*?)```/g;
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  let m: RegExpExecArray | null;
  while ((m = fence.exec(text))) {
    if (m.index > last) out.push(inlineMd(text.slice(last, m.index), `a${k}`));
    out.push(
      <pre key={`f${k}`}>
        <code>{m[1]}</code>
      </pre>,
    );
    last = m.index + m[0].length;
    k++;
  }
  if (last < text.length) out.push(inlineMd(text.slice(last), `z${k}`));
  return out;
}

// --- persisted-session mapping -------------------------------------------
// The backend persists tool turns as assistant rows whose content is the raw
// OpenAI JSON ({"content","tool_calls"}) plus role:"tool" rows. Render those
// as chips + text; never surface raw JSON or tool rows to the user.

function mapPersisted(raw: ChatMessage[]): ChatViewMessage[] {
  const out: ChatViewMessage[] = [];
  for (const m of raw) {
    if (m.role === "tool") continue;
    if (m.role === "assistant") {
      const parsed = tryParse(m.content);
      if (parsed && typeof parsed.content === "string" && Array.isArray(parsed.tool_calls)) {
        out.push({
          role: "assistant",
          content: parsed.content,
          created_at: m.created_at,
          toolCalls: parsed.tool_calls.map((tc) => {
            const fn = (tc as Record<string, unknown>)?.function as
              | Record<string, unknown>
              | undefined;
            return {
              name: typeof fn?.name === "string" ? fn.name : "tool",
              arguments: fn?.arguments ?? null,
              status: "done" as const,
              chip: null,
            };
          }),
        });
        continue;
      }
    }
    out.push({ role: m.role === "user" ? "user" : "assistant", content: m.content, created_at: m.created_at });
  }
  return out;
}

function tryParse(s: string): Record<string, unknown> | null {
  if (!s.startsWith("{")) return null;
  try {
    const v = JSON.parse(s);
    return v && typeof v === "object" ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function ChipRow({ chips }: { chips: { name: string; status: string; chip: string | null }[] }) {
  if (chips.length === 0) return null;
  return (
    <div className="ct-chips">
      {chips.map((c, i) => (
        <span
          key={i}
          className={`ct-chip ${c.status === "running" ? "ct-chip-run" : "ct-chip-done"}`}
        >
          {c.status === "running" ? (
            <>
              <span className="ct-dot" /> {c.name}…
            </>
          ) : (
            <>✓ {c.chip || c.name}</>
          )}
        </span>
      ))}
    </div>
  );
}

interface Props {
  viewed: ViewedMap;
  onViewed: (sessionId: number | string) => void;
}

export default function ChatSurface({ viewed, onViewed }: Props) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [turn, setTurn] = useState<TurnState>(emptyTurn);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  // Draft disposition keyed by draft content, so a card's saved/discarded
  // state survives the pending → committed re-render (ticket #50).
  const [savedDrafts, setSavedDrafts] = useState<Record<string, Search>>({});
  const [discardedDrafts, setDiscardedDrafts] = useState<Record<string, boolean>>({});

  const sessionIdRef = useRef<number | null>(null);
  const lastUserRef = useRef<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const loadSession = useCallback(
    async (sid: number | string) => {
      try {
        const s = await getChatSession(sid);
        setTurn({
          messages: mapPersisted(s.messages),
          pending: { text: "", reasoning: "", toolCalls: [], drafts: [] },
          error: null,
          lastCommittedSessionId: s.id,
        });
        sessionIdRef.current = s.id;
        onViewed(s.id);
      } catch (e) {
        setFatal(e instanceof Error ? e.message : String(e));
      }
    },
    [onViewed],
  );

  // Route change to a different session loads it; `/` resets to a fresh chat.

  useEffect(() => {
    const urlId = id ? Number(id) : null;
    if (urlId === sessionIdRef.current) return;
    if (urlId !== null && Number.isFinite(urlId)) {
      loadSession(urlId);
    } else {
      sessionIdRef.current = null;
      lastUserRef.current = "";
      setTurn(emptyTurn());
      setFatal(null);
      setSavedDrafts({});
      setDiscardedDrafts({});
    }
  }, [id, loadSession]);

  // Keep the log pinned to the bottom as tokens stream in.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turn]);

  const runTurn = useCallback(
    async (sid: number, text: string) => {
      setStreaming(true);
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        await streamChatTurn(
          sid,
          text,
          (frame) => {
            setTurn((prev) => reduce(prev, frame));
            if (frame.event === "turn_complete") {
              // Titles may change server-side; refresh the sidebar list.
              queryClient.invalidateQueries({ queryKey: ["chatSessions"] });
              onViewed(sid);
            }
          },
          ac.signal,
        );
      } catch {
        // Stop or dropped connection: the server persists the user message
        // at turn start; re-GET and render that state (#49: no replay).
        // A server-side turn failure arrives as an `error` event frame and
        // is folded by the reducer, so it never reaches this branch.
        await loadSession(sid);
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [loadSession, onViewed, queryClient],
  );

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    lastUserRef.current = text;
    setTurn((prev) => ({
      ...prev,
      messages: [...prev.messages, { role: "user", content: text }],
      error: null,
    }));
    let sid = sessionIdRef.current;
    if (sid === null) {
      try {
        const s = await createChatSession();
        sid = s.id;
        sessionIdRef.current = sid;
        navigate(`/chat/${sid}`, { replace: true });
      } catch (e) {
        setFatal(e instanceof Error ? e.message : String(e));
        return;
      }
    }
    await runTurn(sid, text);
    textareaRef.current?.focus();
  }, [input, navigate, runTurn, streaming]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const regenerate = useCallback(async () => {
    if (streaming || !sessionIdRef.current || !lastUserRef.current) return;
    setTurn((prev) => clearError(prev));
    await runTurn(sessionIdRef.current, lastUserRef.current);
  }, [runTurn, streaming]);
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const hasLiveOutput = turn.pending.text !== "" || turn.pending.toolCalls.length > 0;

  // One draft → one confirm card, keyed by content so the same proposal
  // keeps its saved/discarded face whether it's still pending or committed.
  const renderDraft = (raw: unknown) => {
    const k = draftKey(raw as Draft);
    return (
      <DraftCard
        key={k}
        draft={raw as Draft}
        saved={savedDrafts[k]}
        discarded={discardedDrafts[k]}
        onSaved={(s) => setSavedDrafts((p) => ({ ...p, [k]: s }))}
        onDiscard={() => setDiscardedDrafts((p) => ({ ...p, [k]: true }))}
      />
    );
  };

  return (
    <div className="chat">
      <div className="ct-scroll" ref={scrollRef}>
        {turn.messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ct-msg ct-user">
              {m.content}
            </div>
          ) : (
            <div key={i} className="ct-msg">
              <div className="ct-role">Agent</div>
              {m.toolCalls && m.toolCalls.length > 0 && <ChipRow chips={m.toolCalls} />}
              <div className="ct-text">{renderMd(m.content)}</div>
              {(m.drafts ?? []).map(renderDraft)}
              {i === turn.messages.length - 1 && (
                <div>
                  <button className="ct-regen" onClick={() => void regenerate()}>
                    ↻ Regenerate
                  </button>
                </div>
              )}
            </div>
          ),
        )}

        {streaming && (
          <div className="ct-msg">
            <div className="ct-role">Agent</div>
            <ChipRow chips={turn.pending.toolCalls} />
            {hasLiveOutput ? (
              <div className="ct-text ct-caret">{renderMd(turn.pending.text)}</div>
            ) : (
              <div className="ct-thinking">
                <span className="ct-dot" /> thinking…
              </div>
            )}
            {turn.pending.drafts.map(renderDraft)}
          </div>
        )}

        {!streaming && turn.error && (
          <div className="ct-error">
            <span>
              {turn.error.message} ({turn.error.code})
            </span>
            <button className="ct-regen" onClick={() => void regenerate()}>
              ↻ Regenerate
            </button>
          </div>
        )}

        {fatal && <div className="ct-error">{fatal}</div>}

        {turn.messages.length > 0 &&
          turn.messages[turn.messages.length - 1]?.role === "user" &&
          !streaming &&
          !turn.error && (
            <div style={{ textAlign: "center" }}>
              <button className="ct-regen" onClick={() => void regenerate()}>
                ↻ Regenerate
              </button>
            </div>
          )}
      </div>

      <div className="ct-composer">
        <textarea
          ref={textareaRef}
          value={input}
          placeholder="Ask the agent anything… (Enter sends)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Chat message"
        />
        {streaming ? (
          <button className="ct-stop" onClick={stop}>
            ■ Stop
          </button>
        ) : (
          <button className="ct-send" onClick={() => void send()} disabled={!input.trim()}>
            Send
          </button>
        )}
      </div>
    </div>
  );
}
