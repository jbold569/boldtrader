// Draft → Bargain Search confirm card (ticket #50, M7 exit; preview phase
// per #35). A `draft` event first shows a READ-ONLY preview of the proposal
// (Discard / ✎ Edit / Save as-is). ✎ Edit reveals the shared SearchForm
// pre-filled for the revision phase. Save = POST /api/v1/searches +
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
    d.target_price,
    d.location,
    d.queries,
    d.exclusions,
  ]);
}

// The wire draft carries target_price as number|null; the form keeps it a
// string while editing (see SearchFormState).
export function draftToForm(d: Draft): SearchFormState {
  return {
    summary: d.summary,
    product_identity: d.product_identity,
    target_price: d.target_price == null ? "" : String(d.target_price),
    location: d.location ?? "",
    queries: d.queries,
    exclusions: d.exclusions,
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
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  if (saved) {
    return (
      <div className="dr-saved">
        ✓ Saved “<Link to={`/bargains/${saved.id}`}>{saved.summary}</Link>”.
      </div>
    );
  }
  if (discarded) {
    return <div className="dr-discarded">Draft discarded — nothing was created.</div>;
  }
  async function save(d: Draft) {
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
  }

  if (!editing) {
    // Preview face: read-only (#35 — the user confirms first, edits only
    // if they choose to). "Location" is the canonical word (#35/glossary).
    return (
      <div className="dr-card dr-preview">
        <h3 className="dr-title">💰 Draft Bargain Search: {draft.summary}</h3>
        <div className="dr-row">
          <span className="k">Product</span>
          <span>{draft.product_identity}</span>
        </div>
        <div className="dr-row">
          <span className="k">Target price</span>
          <span>{draft.target_price == null ? "—" : `$${draft.target_price}`}</span>
        </div>
        <div className="dr-row">
          <span className="k">Location</span>
          <span>{draft.location || "—"}</span>
        </div>
        <div className="dr-row">
          <span className="k">Queries</span>
          <span>{draft.queries.join(", ") || "—"}</span>
        </div>
        <div className="dr-row">
          <span className="k">Exclusions</span>
          <span>{draft.exclusions.join(", ") || "—"}</span>
        </div>
        <div className="dr-actions">
          <button type="button" onClick={onDiscard} disabled={saving}>
            Discard
          </button>
          <button type="button" onClick={() => setEditing(true)} disabled={saving}>
            ✎ Edit
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={saving}
            onClick={() => void save(draft)}
          >
            {saving ? "Saving…" : "Save as-is"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="dr-card">
      <div className="dr-head">
        <span className="dr-title">Edit the proposed search</span>
      </div>
      <SearchForm
        initial={draftToForm(draft)}
        submitting={saving}
        serverError={serverError}
        submitLabel="Save as Bargain Search"
        onSubmit={(d) => void save(d)}
      />
    </div>
  );
}
