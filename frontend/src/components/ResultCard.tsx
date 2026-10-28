// ResultCard (ticket #45): one Listing inside a Bargain Search — Sift
// verdict chip, Enrichment display (a section of the card), asking price,
// the title hyperlinked to the marketplace listing (the title IS the link),
// and the per-card actions (shared CardActions, #47). Look settled in
// prototypes/src/TileView.

import type { ResultCard as ResultCardData } from "../api/types";
import CardActions, { str } from "./CardActions";
import "./results.css";

// verdict → tone (#36): match→ok, not_match→neutral, unsure→warn,
// pending→accent.
const VERDICT: Record<string, { label: string; tone: string }> = {
  match: { label: "MATCH", tone: "ok" },
  not_match: { label: "NO", tone: "neutral" },
  unsure: { label: "SURE?", tone: "warn" },
  pending: { label: "SIFTING", tone: "accent" },
};

export default function ResultCard({
  card,
  searchId,
}: {
  card: ResultCardData;
  searchId: number;
}) {
  const { label, tone } = VERDICT[card.verdict] ?? VERDICT.pending;
  const dead = card.availability === "dead";
  const enriched = card.enrichment?.status === "enriched";

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

      <CardActions card={card} searchId={searchId} />
    </article>
  );
}

// The Enrichment display: resolved product, condition, bundle, per-field
// confidence, and the low-confidence note (an authored description can
// fix what the model wasn't sure about). Shared with the condensed view's
// expand panel (#47).
export function EnrichedBlock({ card }: { card: ResultCardData }) {
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
