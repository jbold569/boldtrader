// Variant A — Verdict-first single column.
// The verdict + deal math IS the card: big colored verdict band with effective
// price vs fair price, photo as a thumbnail inside the band, Enrichment below in
// a light section, per-card actions as buttons at the card foot. Phone: full-
// bleed cards, 16px gutters. Banner sits sticky under the header.

import { SEARCH, LISTINGS, money, pct } from "../data";
import { useTheme, VERDICT_LABEL, confidenceColor } from "../theme";
import { img, brokenImgFallback } from "../img";
import "./variants.css";

function verdictTone(r: (typeof LISTINGS)[number]): string {
  if (r.verdict === "match" && r.fair_price && r.effective_price < r.fair_price)
    return "good";
  if (r.verdict === "not_match") return "off";
  return "mid";
}

export default function VariantA() {
  useTheme();
  return (
    <div className="va">
      <div className="va-banner">
        Sifting {SEARCH.live.sifted}/{SEARCH.live.total} ·{" "}
        <strong>{SEARCH.live.new_deals} new deals</strong> since you last looked
      </div>
      <div className="va-list">
        {LISTINGS.map((r) => {
          const tone = verdictTone(r);
          return (
            <article key={r.id} className={`va-card va-${tone}`}>
              <div className="va-head">
                <img
                  className="va-thumb"
                  src={r.image_url === "" ? brokenImgFallback() : img(r)}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = brokenImgFallback();
                  }}
                  alt=""
                />
                <div className="va-priceblock">
                  <span className={`va-verdict va-verdict-${r.verdict ?? "pending"}`}>
                    {VERDICT_LABEL[r.verdict ?? "pending"]}
                  </span>
                  <span className="va-effective">{money(r.effective_price)}</span>
                  {r.fair_price ? (
                    <span className="va-vs">
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
                    <span className="va-vs muted">no fair price on file</span>
                  )}
                </div>
                <div className="va-ask">
                  ask {money(r.asking_price)}
                  {r.shipping > 0 && ` + ${money(r.shipping)} ship`}
                </div>
              </div>
              <h3 className="va-title">{r.title}</h3>
              <div className="va-meta">
                <span className="chip">{r.marketplace}</span>
                <span className="chip">{r.posted}</span>
                {r.flip_value > 0 && (
                  <span className="chip">flip value {money(r.flip_value)}</span>
                )}
              </div>
              <div className="va-enrich">
                {r.enrichment ? (
                  <>
                    <div className="va-enrich-row">
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
                      <div className="va-bundle">
                        + {r.enrichment.bundle.join(" · ")}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="va-enrich-missing muted">
                    Enrichment missing —{" "}
                    <a href="#re-enrich" onClick={(e) => e.preventDefault()}>
                      re-enrich
                    </a>
                  </div>
                )}
              </div>
              <div className="va-actions">
                <button className="va-primary">Author description</button>
                <button>Re-enrich</button>
                <button className="va-reject">Reject</button>
                <a className="va-open" href={r.url}>
                  Open listing ↗
                </a>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
