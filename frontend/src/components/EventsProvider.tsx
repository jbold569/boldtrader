// App-root SSE fan-out (ticket #44; docs/frontend-architecture.md "SSE fan-out").
// Exactly one EventSource on GET /api/v1/events, mounted above the router.
// No component ever opens its own connection. The stream is notification-only,
// so fan-out = TanStack Query invalidation per the table below.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

export default function EventsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const es = new EventSource("/api/v1/events");
    es.addEventListener("enrichment", () => {
      // The client can't know which searches show the listing; full-prefix
      // invalidation is cheap locally.
      queryClient.invalidateQueries({ queryKey: ["results"] });
    });
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
    return () => es.close();
  }, [queryClient]);

  return <>{children}</>;
}
