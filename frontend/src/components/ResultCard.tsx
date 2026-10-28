// ResultCard (ticket #45): one Listing inside a Bargain Search — Sift
// verdict chip, Enrichment display (a section of the card), asking price,
// the title hyperlinked to the marketplace listing (the title IS the link),
// and the per-card actions: reject with reason, author description inline,
// re-enrich failed Enrichment. Look settled in prototypes/src/TileView.

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createRejection, patchListing, triggerReenrichment } from "../api/client";
import type { ResultCard as ResultCardData } from "../api/types";
import "./results.css";

// verdict → tone (#36): match→ok, not_match→neutral, unsure→warn,
// pending→accent.
const VERDICT: Record<string, { label: string; tone: string }> = {
  match: { label: "MATCH", tone: "ok" },
  not_match: { label: "NO", tone: "neutral" },
  unsure: { label: "SURE?", tone: "warn" },
  pending: { label: "SIFTING", tone: "accent" },
};

// Reads a string field off the unknown-shaped product/confidence wire
// objects (enrichment schema is validated server-side). "?" = missing,
// blank, or 'unknown' — same rendering as the legacy view.
function str(obj: unknown, key: string): string {
  const v =
    typeof obj === "object" && obj !== null && key in obj
      ? (obj as Record<string, unknown>)[key]
      : undefined;
  return typeof v === "string" && v.trim() !== "" && v !== "unknown" ? v : "?";
}

export default function ResultCard({
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

  const { label, tone } = VERDICT[card.verdict] ?? VERDICT.pending;
  const dead = card.availability === "dead";
  const enriched = card.enrichment?.status === "enriched";
  // Unidentified = Enrichment never resolved a real product (missing,
  // pending, failed, or model still 'unknown'). The authored-description
  // bucket.
  const unidentified = !enriched || str(card.enrichment?.product, "model") === "?";

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
        setNote(`Requeued ${requeued} listing${requeued === 1 ? "" : "s"} for Enrichment.`);
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
    <article className={`rc rc-${tone}${dead ? " rc-dead" : ""}`}>
      <div className="rc-head">
        {card.image_url && (
          <img
            className="rc-thumb"
            src={card.image_url}
            alt=""
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        )}
        <div className="rc-priceblock">
          <span className={`rc-verdict rc-verdict-${tone}`}>{label}</span>
          <span className="rc-ask">
            ask{" "}
            {card.asking_price === null
              ? "?"
              : `$${card.asking_price.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          </span>
        </div>
      </div>

      <h3 className="rc-title">
        <a href={card.url} target="_blank" rel="noreferrer">
          {card.title}
        </a>
      </h3>

      <div className="rc-meta">
        {card.marketplace && <span className="chip">{card.marketplace}</span>}
        {dead && <span className="chip bad">Ended</span>}
      </div>

      {card.authored_description ? (
        <div className="rc-authored">{card.authored_description}</div>
      ) : enriched ? (
        <EnrichedBlock card={card} />
      ) : (
        <div className="rc-enrich rc-enrich-pending">
          Enrichment {card.enrichment?.status === "pending" ? "pending" : "failed"} — this
          listing is Unidentified. Author a description to resolve it.
        </div>
      )}

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
    </article>
  );
}

// The Enrichment display: resolved product, condition, bundle, per-field
// confidence, and the low-confidence note (an authored description can
// fix what the model wasn't sure about).
function EnrichedBlock({ card }: { card: ResultCardData }) {
  const e = card.enrichment!;
  const bundle = Array.isArray(e.bundle) ? (e.bundle as string[]).join(", ") : "?";
  const parts = [
    `manufacturer: ${str(e.product, "manufacturer")} (${str(e.confidence, "manufacturer")})`,
    `model: ${str(e.product, "model")} (${str(e.confidence, "model")})`,
    `config: ${str(e.product, "config")} (${str(e.confidence, "config")})`,
    `condition: ${str(e, "condition")} (${str(e.confidence, "condition")})`,
    `bundle: ${bundle === "" ? "?" : bundle} (${str(e.confidence, "bundle")})`,
  ];
  const low = ["manufacturer", "model", "config", "condition", "bundle"].some(
    (f) => ["?", "low", "unknown"].includes(str(e.confidence, f)),
  );
  return (
    <div className="rc-enrich">
      ✨ {parts.join(" · ")}
      {low && (
        <div className="rc-lowconf">
          Low confidence — an authored description overrides this.
        </div>
      )}
    </div>
  );
}
