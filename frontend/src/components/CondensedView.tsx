// CondensedView (#47): the dense ledger density of the SAME results data
// the tile grid renders. Look settled in prototypes/src/CondensedView +
// views.css (#34): the thumbnail column is frozen (position: sticky) so
// the photo stays as the row's visual anchor while the other columns
// slide, and each row expands into a detail panel that is likewise
// viewport-locked — the enrichment and actions stay in front while the
// ledger scrolls horizontally. Only the renderer changes with density;
// the data, filters, sort and live behavior are the page's, untouched.

import { useState } from "react";
import type { ResultCard as ResultCardData } from "../api/types";
import { EnrichedBlock } from "./ResultCard";
import CardActions from "./CardActions";
import "./condensed.css";

// dot tone (#36): match→ok, unsure→warn, not_match→off, pending→idle.
function dotClass(verdict: string): string {
  if (verdict === "match") return "dot-ok";
  if (verdict === "unsure") return "dot-warn";
  if (verdict === "not_match") return "dot-off";
  return "dot-idle";
}

function Row({
  card,
  searchId,
}: {
  card: ResultCardData;
  searchId: number;
}) {
  const [open, setOpen] = useState(false);
  const dead = card.availability === "dead";
  const enriched = card.enrichment?.status === "enriched";

  return (
    <>
      <tr
        className={`cd-row${dead ? " cd-dead" : ""}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <td className="cd-photo">
          {card.image_url ? (
            <img
              src={card.image_url}
              alt=""
              onError={(e) => {
                e.currentTarget.style.display = "none";
              }}
            />
          ) : null}
        </td>
        <td className="cd-verdict">
          <span className={`cd-dot ${dotClass(card.verdict)}`} />
        </td>
        <td className="cd-title">
          <a href={card.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
            {card.title}
          </a>
        </td>
        <td className="cd-num">
          {card.asking_price === null
            ? "?"
            : `$${card.asking_price.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
        </td>
        <td className="cd-cond">{card.enrichment?.condition ?? "?"}</td>
        <td className="cd-mp">
          {card.marketplace}
          {dead && <span className="chip bad">Ended</span>}
        </td>
      </tr>
      {open && (
        <tr className="cd-expand">
          <td colSpan={6}>
            {/* stopPropagation: the panel is full of interactive controls;
                none of their clicks should collapse the row. */}
            <div className="cd-expand-inner" onClick={(e) => e.stopPropagation()}>
              <div className="cd-panel-body">
                {card.authored_description ? (
                  <div className="rc-authored">{card.authored_description}</div>
                ) : enriched ? (
                  <EnrichedBlock card={card} />
                ) : (
                  <p className="muted">
                    Enrichment{" "}
                    {card.enrichment?.status === "pending" ? "pending" : "failed"} —
                    this listing is Unidentified. Author a description to
                    resolve it.
                  </p>
                )}
                <CardActions card={card} searchId={searchId} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function CondensedView({
  items,
  searchId,
}: {
  items: ResultCardData[];
  searchId: number;
}) {
  return (
    <div className="cd-wrap">
      <div className="cd-scroll">
        <table className="cd-table">
          <thead>
            <tr>
              <th className="cd-photo"></th>
              <th>Verdict</th>
              <th>Listing</th>
              <th>Ask</th>
              <th>Cond.</th>
              <th>MP</th>
            </tr>
          </thead>
          <tbody>
            {items.map((card) => (
              <Row key={card.listing_id} card={card} searchId={searchId} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
