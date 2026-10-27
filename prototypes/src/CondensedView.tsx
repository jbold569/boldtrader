// Condensed view — dense ledger table (the look from variant C): every
// deal-math column visible at once, tap a row to expand the full Enrichment
// and actions. Phone: filter/sort controls sit above (shared FilterBar); the
// table keeps a horizontal scroll strip. The thumbnail column is frozen
// (sticky) so the photo stays as the row's visual anchor while scrolling
// horizontally.

import { useState } from "react";
import { money, pct, postedLabel } from "./data";
import type { ResultListing } from "./data";
import { confidenceColor } from "./theme";
import { img, brokenImgFallback } from "./img";
import "./views.css";

function Row({ r }: { r: ResultListing }) {
  const [open, setOpen] = useState(false);
  const delta = r.fair_price ? pct(r.effective_price, r.fair_price) : null;
  const dead = r.availability === "dead";
  return (
    <>
      <tr
        className={`cd-row${dead ? " cd-dead" : ""}`}
        onClick={() => setOpen(!open)}
      >
        <td className="cd-photo">
          <img
            src={r.image_url === "" ? brokenImgFallback() : img(r)}
            onError={(e) => {
              (e.target as HTMLImageElement).src = brokenImgFallback();
            }}
            alt=""
          />
        </td>
        <td>
          <span
            className={`cd-dot ${
              r.verdict === "match"
                ? "dot-ok"
                : r.verdict === "not_match"
                  ? "dot-off"
                  : r.verdict === "unsure"
                    ? "dot-warn"
                    : "dot-idle"
            }`}
          />
        </td>
        <td className="cd-title">{r.title}</td>
        <td className="cd-num cd-eff">{money(r.effective_price)}</td>
        <td className="cd-num">
          {r.fair_price ? money(r.fair_price) : "—"}
        </td>
        <td
          className="cd-num"
          style={{
            color:
              delta == null
                ? "var(--muted)"
                : delta > 0
                  ? "var(--ok)"
                  : "var(--bad)",
          }}
        >
          {delta == null ? "—" : `${delta}%`}
        </td>
        <td className="cd-num">{money(r.asking_price)}</td>
        <td className="cd-cond">
          {r.enrichment ? r.enrichment.condition : "—"}
        </td>
        <td className="cd-mp">{r.marketplace}</td>
        <td className="cd-posted">{postedLabel(r.posted_minutes)}</td>
      </tr>
      {open && (
        <tr className="cd-expand">
          <td colSpan={10}>
            {r.enrichment ? (
              <div className="cd-enrich">
                <p>
                  <b>{r.enrichment.product}</b>{" "}
                  <span className="conf-track">
                    <span
                      className="conf-fill"
                      style={{
                        width: `${r.enrichment.confidence * 100}%`,
                        background: confidenceColor(r.enrichment.confidence),
                      }}
                    />
                  </span>{" "}
                  {r.enrichment.confidence >= 0.8
                    ? "high confidence"
                    : r.enrichment.confidence >= 0.6
                      ? "medium confidence"
                      : "low confidence"}
                </p>
                {r.enrichment.bundle.length > 0 && (
                  <p>Bundle: {r.enrichment.bundle.join(", ")}</p>
                )}
                <p>
                  Flip value {money(r.flip_value)} → effective{" "}
                  {money(r.effective_price)} vs fair{" "}
                  {r.fair_price ? money(r.fair_price) : "n/a"}
                </p>
              </div>
            ) : (
              <p className="muted">
                Enrichment missing. Re-enrich to resolve this listing.
              </p>
            )}
            <div className="cd-actions">
              <button className="tl-primary">Author description</button>
              <button>Re-enrich</button>
              <button className="tl-reject">Reject</button>
              <a href={r.url}>Open listing ↗</a>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function CondensedView({
  listings,
}: {
  listings: ResultListing[];
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
              <th>Effective</th>
              <th>Fair</th>
              <th>Δ</th>
              <th>Ask</th>
              <th>Cond.</th>
              <th>MP</th>
              <th>Posted</th>
            </tr>
          </thead>
          <tbody>
            {listings.map((r) => (
              <Row key={r.id} r={r} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
