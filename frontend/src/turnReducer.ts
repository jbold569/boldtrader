// Pure turn reducer (ticket #49). The decision-encoding module from
// docs/migration-plan.md "SSE turn reducer": everything before turn_complete is
// preview; turn_complete is the ONLY commit point.
//
// I/O lives in the consumer (ChatSurface): stream frames arrive via
// api/client.streamChatTurn, a stream death mid-turn re-GETs the persisted
// session, and stop/regenerate are client-side. This module never touches the
// network or the DOM, so the fold table is unit-testable in isolation.

export interface ToolCallChip {
  name: string;
  arguments: unknown;
  status: "running" | "done";
  chip: string | null;
}

export interface ChatViewMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  toolCalls?: ToolCallChip[];
  drafts?: unknown[];
  error?: { code: string; message: string } | null;
}

export interface PendingTurn {
  text: string;
  reasoning: string;
  toolCalls: ToolCallChip[];
  drafts: unknown[];
}

export interface TurnState {
  messages: ChatViewMessage[];
  pending: PendingTurn;
  error: { code: string; message: string } | null;
  lastCommittedSessionId: number | null;
}

export interface TurnEvent {
  event: string;
  data: unknown;
}

export function emptyPending(): PendingTurn {
  return { text: "", reasoning: "", toolCalls: [], drafts: [] };
}

// Frames carry JSON objects; trust only the keys we read, nothing else.
function obj(d: unknown): Record<string, unknown> {
  return d && typeof d === "object" ? (d as Record<string, unknown>) : {};
}

function str(d: Record<string, unknown>, k: string): string {
  const v = d[k];
  return typeof v === "string" ? v : "";
}

export function emptyTurn(): TurnState {
  return {
    messages: [],
    pending: emptyPending(),
    error: null,
    lastCommittedSessionId: null,
  };
}

export function reduce(state: TurnState, e: TurnEvent): TurnState {
  const d = obj(e.data);
  switch (e.event) {
    case "token":
      return {
        ...state,
        pending: { ...state.pending, text: state.pending.text + str(d, "text") },
      };

    case "reasoning":
      // Captured but suppressed in the UI; the "thinking…" spinner covers the gap.
      return {
        ...state,
        pending: { ...state.pending, reasoning: state.pending.reasoning + str(d, "text") },
      };

    case "tool_call":
      return {
        ...state,
        pending: {
          ...state.pending,
          toolCalls: [
            ...state.pending.toolCalls,
            {
              name: str(d, "name") || "tool",
              arguments: d.arguments ?? null,
              status: "running" as const,
              chip: null,
            },
          ],
        },
      };

    case "tool_result": {
      // Complete the oldest still-running chip with this name; ignore if none.
      const name = str(d, "name");
      let done = false;
      const toolCalls = state.pending.toolCalls.map((c) => {
        if (!done && c.status === "running" && c.name === name) {
          done = true;
          return { ...c, status: "done" as const, chip: str(d, "chip") || null };
        }
        return c;
      });
      return { ...state, pending: { ...state.pending, toolCalls } };
    }

    case "draft":
      // The model may propose several Bargain Searches in one turn; each
      // draft event appends its own confirmation card.
      return { ...state, pending: { ...state.pending, drafts: [...state.pending.drafts, e.data] } };

    case "turn_complete": {
      const msg: ChatViewMessage = {
        role: "assistant",
        content: str(d, "message") || state.pending.text,
        toolCalls: state.pending.toolCalls,
        drafts: state.pending.drafts,
        error: null,
      };
      return {
        messages: [...state.messages, msg],
        pending: emptyPending(),
        error: null,
        lastCommittedSessionId: typeof d.session_id === "number" ? d.session_id : null,
      };
    }

    case "error":
      // Preserve the user's typed text and the partial turn; surface the error.
      return {
        ...state,
        error: { code: str(d, "code") || "error", message: str(d, "message") || "Unknown error" },
      };

    default:
      return state; // ping and unknown frames are no-ops
  }
}

export function reduceAll(initial: TurnState, events: TurnEvent[]): TurnState {
  return events.reduce(reduce, initial);
}

// After an errored turn, the user's next send starts from a clean pending but
// keeps the committed transcript.
export function clearError(state: TurnState): TurnState {
  return { ...state, error: null, pending: emptyPending() };
}
