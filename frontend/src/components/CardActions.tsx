// The per-listing action set (#45), shared by the tile ResultCard and the
// condensed ledger's expand panel (#47): reject with reason, author/edit
// description, re-enrich failed Enrichment. Extracted verbatim so the two
// densities cannot drift apart.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createRejection, patchListing, triggerReenrichment } from "../api/client";
import type { ResultCard as ResultCardData } from "../api/types";
import "./results.css";

// Reads a string field off the unknown-shaped product/confidence wire
// objects (enrichment schema is validated server-side). "?" = missing,
// blank, or 'unknown' — same rendering as the legacy view.
export function str(obj: unknown, key: string): string {
  const v =
    typeof obj === "object" && obj !== null && key in obj
      ? (obj as Record<string, unknown>)[key]
      : undefined;
  return typeof v === "string" && v.trim() !== "" && v !== "unknown" ? v : "?";
}

export default function CardActions({
  card,
  searchId,
}: {
  card: ResultCardData;
  searchId: number;
}) {
  const [mode, setMode] = useState<null | "reject" | "author">(null);
  const [reason, setReason] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const enriched = card.enrichment?.status === "enriched";
  // Unidentified = Enrichment never resolved a real product (missing,
  // pending, failed, or model still 'unknown'). The authored-description
  // bucket.
  const unidentified =
    !enriched || str(card.enrichment?.product, "model") === "?";

  const queryClient = useQueryClient();

  const submit = async (what: "reject" | "author" | "reenrich") => {
    setBusy(true);
    setError(null);
    try {
      if (what === "reject") {
        await createRejection(searchId, card.listing_id, reason.trim());
      } else if (what === "author") {
        await patchListing(card.listing_id, text.trim() || null);
        setMode(null);
        setText("");
      } else {
        const { requeued } = await triggerReenrichment(searchId);
        setNote(
          `Requeued ${requeued} listing${requeued === 1 ? "" : "s"} for Enrichment.`,
        );
      }
      // These writes don't always echo on the SSE stream (a PATCH has no
      // event of its own; rejections have none at all), so pull the
      // updated cards now. The later `enrichment` events refresh again.
      queryClient.invalidateQueries({ queryKey: ["results", searchId] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {mode === "reject" ? (
        <div className="rc-inline">
          <input
            aria-label="Rejection reason"
            placeholder="Why? e.g. wrong model, overpriced"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="rc-inline-row">
            <button
              className="rc-reject"
              disabled={busy || !reason.trim()}
              onClick={() => submit("reject")}
            >
              {busy ? "Rejecting…" : "Reject"}
            </button>
            <button type="button" onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : mode === "author" ? (
        <div className="rc-inline">
          <textarea
            aria-label="Authored description"
            placeholder="What this listing actually is, in plain words."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="rc-inline-row">
            <button
              className="btn-primary"
              disabled={busy || !text.trim()}
              onClick={() => submit("author")}
            >
              {busy ? "Saving…" : "Save description"}
            </button>
            <button type="button" onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="rc-actions">
          {!card.authored_description && unidentified && (
            <button
              className="btn-primary"
              onClick={() => {
                setText(card.authored_description ?? "");
                setMode("author");
              }}
            >
              Author description
            </button>
          )}
          {card.authored_description && (
            <button
              onClick={() => {
                setText(card.authored_description ?? "");
                setMode("author");
              }}
            >
              Edit description
            </button>
          )}
          {!enriched && (
            <button disabled={busy} onClick={() => submit("reenrich")}>
              {busy ? "Re-enriching…" : "Re-enrich"}
            </button>
          )}
          <button className="rc-reject" onClick={() => setMode("reject")}>
            Reject
          </button>
        </div>
      )}

      {error && <p className="rc-note rc-note-bad">{error}</p>}
      {note && !error && <p className="rc-note">{note}</p>}
    </>
  );
}
