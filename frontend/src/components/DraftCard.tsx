// Draft → Bargain Search confirm card (ticket #50, M7 exit). A `draft`
// event renders the same shared SearchForm pre-filled, inline in the
// conversation where the draft arrived. Save = POST /api/v1/searches +
// invalidate the list; discard = client-side no-op — ignoring a proposal
// must cost nothing, so nothing reaches the server.
//
// Save/discard status lives in the parent (keyed by draft content) so it
// survives the pending → committed re-render: the card the user was
// looking at mid-stream is the same card after turn_complete.

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { createSearch } from "../api/client";
import type { Draft, Search } from "../api/types";
import SearchForm, { type SearchFormState } from "./SearchForm";
import "./draft.css";

// Content-addressed key: two renders of the same draft agree on identity
// regardless of object/key ordering.
export function draftKey(d: Draft): string {
  return JSON.stringify([
    d.summary,
    d.product_identity,
    d.queries,
    d.exclusions,
    d.target_price,
    d.location,
  ]);
}

// The wire draft carries target_price as number|null; the form keeps it a
// string while editing (see SearchFormState).
export function draftToForm(d: Draft): SearchFormState {
  return {
    summary: d.summary ?? "",
    product_identity: d.product_identity ?? "",
    target_price: d.target_price == null ? "" : String(d.target_price),
    location: d.location ?? "",
    queries: d.queries ?? [],
    exclusions: d.exclusions ?? [],
  };
}

export default function DraftCard({
  draft,
  saved,
  discarded,
  onSaved,
  onDiscard,
}: {
  draft: Draft;
  saved?: Search | undefined;
  discarded?: boolean;
  onSaved: (search: Search) => void;
  onDiscard: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  if (saved) {
    return (
      <div className="dr-card dr-saved">
        <span className="dr-title">✓ Bargain Search created:</span>{" "}
        <Link to={`/bargains/${saved.id}`}>{saved.summary}</Link>
      </div>
    );
  }
  if (discarded) {
    return <div className="dr-discarded">Draft discarded — nothing was created.</div>;
  }

  return (
    <div className="dr-card">
      <div className="dr-head">
        <span className="dr-title">Agent proposes a Bargain Search</span>
        <button type="button" className="dr-discard" onClick={onDiscard}>
          Discard
        </button>
      </div>
      <SearchForm
        initial={draftToForm(draft)}
        submitting={saving}
        serverError={serverError}
        submitLabel="Save as Bargain Search"
        onSubmit={async (d) => {
          setSaving(true);
          setServerError(null);
          try {
            const created = await createSearch(d);
            // The row itself must show up immediately; search_complete
            // (fan-out done) refreshes match counts later.
            queryClient.invalidateQueries({ queryKey: ["searches"] });
            onSaved(created);
          } catch (e) {
            setServerError(e instanceof Error ? e.message : String(e));
          } finally {
            setSaving(false);
          }
        }}
      />
    </div>
  );
}
