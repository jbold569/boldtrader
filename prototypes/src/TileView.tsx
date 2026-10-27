// Tile view — verdict-first cards (the look from variant A), in a responsive
// tile grid. Every tile: verdict + effective-vs-fair math as the headline,
// photo thumb, Enrichment tinted section, per-card actions at the foot.
// Dead listings are visibly dimmed. Filtering/sorting lives in the shared
// FilterBar above; this view only renders what it's given.

import { money, pct, postedLabel, type ResultListing } from "./data";
import { VERDICT_LABEL, confidenceColor } from "./theme";
import { img, brokenImgFallback } from "./img";
import "./views.css";

export default function TileView({
  listings,
}: {
  listings: ResultListing[];
}) {
  return (
    <div className="tl-grid">
      {listings.map((r) => {
        const tone =
          r.verdict === "match" &&
          r.fair_price &&
          r.effective_price < r.fair_price
            ? "good"
            : r.verdict === "not_match"
              ? "off"
              : "mid";
        const dead = r.availability === "dead";
        return (
          <article
            key={r.id}
            className={`tl-card tl-${tone}${dead ? " tl-dead" : ""}`}
          >
            <div className="tl-head">
              <img
                className="tl-thumb"
                src={r.image_url === "" ? brokenImgFallback() : img(r)}
                onError={(e) => {
                  (e.target as HTMLImageElement).src = brokenImgFallback();
                }}
                alt=""
              />
              <div className="tl-priceblock">
                <span
                  className={`tl-verdict tl-verdict-${r.verdict ?? "pending"}`}
                >
                  {VERDICT_LABEL[r.verdict ?? "pending"]}
                </span>
                <span className="tl-effective">{money(r.effective_price)}</span>
                {r.fair_price ? (
                  <span className="tl-vs">
                    vs fair {money(r.fair_price)} ·{" "}
                    <b
                      style={{
                        color:
                          r.effective_price < r.fair_price
                            ? "var(--ok)"
                            : "var(--bad)",
                      }}
                    >
                      {pct(r.effective_price, r.fair_price)}%
                    </b>
                  </span>
                ) : (
                  <span className="tl-vs muted">no fair price on file</span>
                )}
              </div>
              <div className="tl-ask">
                ask {money(r.asking_price)}
                {r.shipping > 0 && ` + ${money(r.shipping)} ship`}
              </div>
            </div>
            <h3 className="tl-title">{r.title}</h3>
            <div className="tl-meta">
              <span className="chip">{r.marketplace}</span>
              <span className="chip">{postedLabel(r.posted_minutes)}</span>
              {dead && <span className="chip bad">no longer available</span>}
              {r.flip_value > 0 && (
                <span className="chip">flip value {money(r.flip_value)}</span>
              )}
            </div>
            <div className="tl-enrich">
              {r.enrichment ? (
                <>
                  <div className="tl-enrich-row">
                    <b>{r.enrichment.product}</b>
                    <span className="chip">{r.enrichment.condition}</span>
                    <span className="conf-track">
                      <span
                        className="conf-fill"
                        style={{
                          width: `${r.enrichment.confidence * 100}%`,
                          background: confidenceColor(r.enrichment.confidence),
                        }}
                      />
                    </span>
                  </div>
                  {r.enrichment.bundle.length > 0 && (
                    <div className="tl-bundle">
                      + {r.enrichment.bundle.join(" · ")}
                    </div>
                  )}
                </>
              ) : (
                <div className="tl-enrich-missing muted">
                  Enrichment missing —{" "}
                  <a href="#re-enrich" onClick={(e) => e.preventDefault()}>
                    re-enrich
                  </a>
                </div>
              )}
            </div>
            <div className="tl-actions">
              <button className="tl-primary">Author description</button>
              <button>Re-enrich</button>
              <button className="tl-reject">Reject</button>
              <a className="tl-open" href={r.url}>
                Open listing ↗
              </a>
            </div>
          </article>
        );
      })}
    </div>
  );
}
