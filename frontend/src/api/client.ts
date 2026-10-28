// Typed fetch wrapper over BoldTrader API v1 (docs/api-contract.md).
// Native fetch only; JSON in/out; error bodies parsed into ApiError.

import type {
  ChatSession,
  ChatSessionSummary,
  Draft,
  Envelope,
  Liveness,
  MarketplaceSearchResult,
  ResultCard,
  Search,
  SearchListItem,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "unknown", err.message ?? res.statusText);
  }
  return data as T;
}

// --- Bargain Searches ------------------------------------------------

export const listSearches = (page = 1) =>
  request<Envelope<SearchListItem>>("GET", `/searches?page=${page}`);

export const getSearch = (id: number | string) =>
  request<Search>("GET", `/searches/${id}`);

export const createSearch = (draft: Draft) =>
  request<Search>("POST", "/searches", draft);

export const updateSearch = (id: number | string, draft: Draft) =>
  request<Search>("PATCH", `/searches/${id}`, draft);

export const deleteSearch = (id: number | string) =>
  request<null>("DELETE", `/searches/${id}`);

// --- Results ---------------------------------------------------------

export interface ResultsFilters {
  page?: number;
  per_page?: number;
  verdict?: string;
  max_price?: number;
  availability?: "live" | "dead";
  sort?: "price_asc" | "price_desc" | "newest";
}

export const getResults = (searchId: number | string, filters: ResultsFilters = {}) => {
  const qs = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v !== undefined) as [string, string][],
  );
  const q = qs.toString();
  return request<Envelope<ResultCard>>("GET", `/searches/${searchId}/results${q ? `?${q}` : ""}`);
};

export const createRejection = (searchId: number | string, listing_id: string, reason: string) =>
  request<{ listing_id: string; reason: string }>("POST", `/searches/${searchId}/rejections`, {
    listing_id,
    reason,
  });

export const triggerReenrichment = (searchId: number | string) =>
  request<{ requeued: number }>("POST", `/searches/${searchId}/reenrichment`);

export const getLiveness = (searchId: number | string) =>
  request<Liveness>("GET", `/searches/${searchId}/liveness`);

// --- Marketplace / listings -------------------------------------------

export interface MarketplaceSearchParams {
  q: string;
  marketplace?: string;
  location?: string;
  page?: number;
}

export const marketplaceSearch = (params: MarketplaceSearchParams) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][],
  );
  return request<MarketplaceSearchResult>("GET", `/marketplace/search?${qs}`);
};

export const patchListing = (id: string, authored_description: string | null) =>
  request<{ id: string; authored_description: string | null; availability: string }>(
    "PATCH",
    `/listings/${id}`,
    { authored_description },
  );

// --- Chat sessions ----------------------------------------------------

export const listChatSessions = (page = 1) =>
  request<Envelope<ChatSessionSummary>>("GET", `/chat/sessions?page=${page}`);

export const createChatSession = (title?: string) =>
  request<ChatSession>("POST", "/chat/sessions", title ? { title } : {});

export const getChatSession = (id: number | string) =>
  request<ChatSession>("GET", `/chat/sessions/${id}`);

export const deleteChatSession = (id: number | string) =>
  request<null>("DELETE", `/chat/sessions/${id}`);

// --- Chat turn (streaming) --------------------------------------------
// POST + SSE: EventSource can't POST, so we read the fetch body stream and
// emit (event, data) for each `event: <name>\ndata: <json>\n\n` frame.

export interface SseFrame {
  event: string;
  data: unknown;
}

export async function streamChatTurn(
  sessionId: number | string,
  message: string,
  onFrame: (frame: SseFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text();
    let err: { code?: string; message?: string } = {};
    try {
      err = JSON.parse(text)?.error ?? {};
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, err.code ?? "unknown", err.message ?? res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const raw = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length > 0) {
        onFrame({ event, data: JSON.parse(dataLines.join("\n")) });
      }
    }
  }
}
