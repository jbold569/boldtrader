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

// The Enrichment display (#45/#46 look from prototypes/src/TileView):
// resolved product name + condition chip + a confidence bar, and the
// bundle as a `+ item · item` line. The wire carries per-field string
// confidences ("high"/"medium"/"low"); the bar shows the MINIMUM across
// fields, colored by the same ramp (high→ok/100%, medium→warn/50%,
// low|unknown→bad/20%).
const RANK: Record<string, number> = { high: 2, medium: 1, low: 0, unknown: 0 };

export function EnrichedBlock({ card }: { card: ResultCardData }) {
  const e = card.enrichment!;
  const bundle = Array.isArray(e.bundle) ? (e.bundle as string[]) : [];
  const conf = (e.confidence ?? {}) as Record<string, unknown>;
  const fields = ["manufacturer", "model", "config", "condition", "bundle"];
  const ranks = fields.map((f) => RANK[String(conf[f] ?? "unknown")] ?? 0);
  const min = Math.min(...ranks);
  const pct = [20, 50, 100][min];
  const color = ["var(--bad)", "var(--warn)", "var(--ok)"][min];
  const model = str(e.product, "model");
  const maker = str(e.product, "manufacturer");
  const name =
    model && model !== "?"
      ? maker && maker !== "?" && !model.toLowerCase().includes(maker.toLowerCase())
        ? `${maker} ${model}`
        : model
      : maker;
  const low = min === 0;
  return (
    <div className="rc-enrich">
      <div className="rc-enrich-row">
        <b>{name || "Unidentified"}</b>
        <span className="chip">{e.condition ?? "?"}</span>
        <span className="conf-track" aria-label={`confidence ${pct}%`}>
          <span className="conf-fill" style={{ width: `${pct}%`, background: color }} />
        </span>
      </div>
      {bundle.length > 0 && (
        <div className="rc-bundle">+ {bundle.join(" · ")}</div>
      )}
      {low && (
        <div className="rc-lowconf">
          Low confidence — an authored description overrides this.
        </div>
      )}
    </div>
  );
}
