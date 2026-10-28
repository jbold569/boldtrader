// App-root SSE fan-out (tickets #44, #46). Exactly one EventSource on
// GET /api/v1/events, mounted above the router. No component ever opens its
// own connection. The stream is notification-only, so fan-out = TanStack
// Query invalidation per the architecture table; components that need the
// raw event payloads (#46's prepend-on-arrivals) subscribe through the
// context exported here instead of touching EventSource.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

// Wire payloads per docs/api-contract.md "Global events stream".
export interface EnrichmentEvent {
  listing_id: string;
  status: string;
}
export interface LivenessEvent {
  search_id: number;
  done: boolean;
  dead_count: number;
  banner: string;
}
export interface SearchCompleteEvent {
  search_id: number;
  match_count: number;
}

// Overloads so subscribers get the right payload type per event name.
export interface EventsHub {
  on(name: "enrichment", handler: (data: EnrichmentEvent) => void): () => void;
  on(name: "liveness", handler: (data: LivenessEvent) => void): () => void;
  on(
    name: "search_complete",
    handler: (data: SearchCompleteEvent) => void,
  ): () => void;
}

const Ctx = createContext<EventsHub | null>(null);

export function useEvents(): EventsHub {
  const api = useContext(Ctx);
  if (!api) throw new Error("useEvents must be used under <EventsProvider>");
  return api;
}

export default function EventsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const listeners = useRef<Record<string, Set<(data: unknown) => void>>>({});

  const hub = useMemo<EventsHub>(
    () => ({
      on: ((name: string, handler: (data: unknown) => void) => {
        const set = (listeners.current[name] ??= new Set());
        set.add(handler);
        return () => {
          set.delete(handler);
        };
      }) as EventsHub["on"],
    }),
    [],
  );

  useEffect(() => {
    const es = new EventSource("/api/v1/events");
    es.addEventListener("liveness", (e) => {
      const { search_id } = JSON.parse(e.data);
      queryClient.invalidateQueries({ queryKey: ["search", search_id] });
      queryClient.invalidateQueries({ queryKey: ["liveness", search_id] });
    });
    es.addEventListener("search_complete", () => {
      queryClient.invalidateQueries({ queryKey: ["searches"] });
    });
    // Events are ephemeral; durable state is the DB. A reconnect refetches
    // everything and converges.
    es.addEventListener("error", () => {
      queryClient.invalidateQueries();
    });

    const handlers: Array<[string, (e: MessageEvent) => void]> = [];
    for (const name of ["enrichment", "liveness", "search_complete"] as const) {
      const h = (e: MessageEvent) => {
        const data = JSON.parse(e.data);
        (listeners.current[name] ?? new Set()).forEach((fn) => fn(data));
      };
      handlers.push([name, h]);
      es.addEventListener(name, h);
    }
    return () => {
      for (const [name, h] of handlers) es.removeEventListener(name, h);
      es.close();
    };
  }, [queryClient]);

  return <Ctx.Provider value={hub}>{children}</Ctx.Provider>;
}
