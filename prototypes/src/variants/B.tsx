// Variant B — Photo-dominant grid.
// The photo IS the card (4:3, full-bleed, rounded). Verdict rides as a corner
// ribbon on the photo; price sits in a scrim at the photo foot. Title + a single
// Enrichment chip under the photo. Everything else (bundle, fair price math,
// actions) is hidden behind a tap-to-expand drawer. 2-col grid on desktop,
// 1-col under 640px. Banner floats over the grid as a dismissible toast.

import { useState } from "react";
import { SEARCH, LISTINGS, money, pct } from "../data";
import { VERDICT_LABEL, confidenceColor } from "../theme";
import { img, brokenImgFallback } from "../img";
import "./variants.css";

function CardB({ r }: { r: (typeof LISTINGS)[number] }) {
  const [open, setOpen] = useState(false);
  const ribbonTone =
    r.verdict === "match"
      ? "rib-ok"
      : r.verdict === "not_match"
        ? "rib-off"
        : r.verdict === "unsure"
          ? "rib-warn"
          : "rib-idle";
  return (
    <article className="vb-card" onClick={() => setOpen(!open)}>
      <div className="vb-photo">
        <img
          src={r.image_url === "" ? brokenImgFallback() : img(r)}
          onError={(e) => {
            (e.target as HTMLImageElement).src = brokenImgFallback();
          }}
          alt=""
        />
        <span className={`vb-ribbon ${ribbonTone}`}>
          {VERDICT_LABEL[r.verdict ?? "pending"]}
        </span>
        <div className="vb-scrim">
          <span className="vb-effective">{money(r.effective_price)}</span>
          <span className="vb-askline">
            ask {money(r.asking_price)}
            {r.shipping > 0 && ` +${money(r.shipping)}`}
          </span>
        </div>
      </div>
      <div className="vb-under">
        <h3 className="vb-title">{r.title}</h3>
        <div className="vb-chips">
          <span className="chip">{r.marketplace}</span>
          {r.enrichment ? (
            <span className="chip">{r.enrichment.condition}</span>
          ) : (
            <span className="chip warn">no enrichment</span>
          )}
          {r.fair_price && (
            <span
              className={`chip ${
                r.effective_price < r.fair_price ? "ok" : "bad"
              }`}
            >
              {pct(r.effective_price, r.fair_price)}% vs fair
            </span>
          )}
        </div>
        {open && (
          <div className="vb-drawer">
            {r.enrichment && (
              <p className="vb-prod">
                {r.enrichment.product}{" "}
                <span className="conf-track">
                  <span
                    className="conf-fill"
                    style={{
                      width: `${r.enrichment.confidence * 100}%`,
                      background: confidenceColor(r.enrichment.confidence),
                    }}
                  />
                </span>
              </p>
            )}
            {r.enrichment && r.enrichment.bundle.length > 0 && (
              <p className="vb-bundle">Bundle: {r.enrichment.bundle.join(", ")}</p>
            )}
            <p className="vb-flip">
              Flip value: {money(r.flip_value)} · effective{" "}
              {money(r.effective_price)}
            </p>
            <div className="vb-actions">
              <button className="va-primary">Author description</button>
              <button>Re-enrich</button>
              <button className="va-reject">Reject</button>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

export default function VariantB() {
  const [toast, setToast] = useState(true);
  return (
    <div className="vb">
      {toast && (
        <div className="vb-toast">
          <span>
            Sifting {SEARCH.live.sifted}/{SEARCH.live.total} ·{" "}
            {SEARCH.live.new_deals} new deals
          </span>
          <button onClick={() => setToast(false)}>Dismiss</button>
        </div>
      )}
      <div className="vb-grid">
        {LISTINGS.map((r) => (
          <CardB key={r.id} r={r} />
        ))}
      </div>
    </div>
  );
}
