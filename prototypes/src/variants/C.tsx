// Variant C — Dense ledger / table.
// Results as a compact data table: every deal-math column visible at once
// (verdict, effective, fair, delta, ask, condition, marketplace). Reading a
// page of results is scanning, not scrolling-through-cards. Tap a row to
// expand it inline with the full Enrichment + actions. Desktop: 8-column
// table, filter rail sticky on the left. Phone: the table reflows to a
// 2-line-per-row stack with a horizontal scroll strip of columns. Banner is
// an inline strip in the table header row.

import { useState } from "react";
import { SEARCH, LISTINGS, money, pct } from "../data";
import { VERDICT_LABEL, confidenceColor } from "../theme";
import { img, brokenImgFallback } from "../img";
import "./variants.css";

function RowC({ r }: { r: (typeof LISTINGS)[number] }) {
  const [open, setOpen] = useState(false);
  const delta = r.fair_price ? pct(r.effective_price, r.fair_price) : null;
  return (
    <>
      <tr className="vc-row" onClick={() => setOpen(!open)}>
        <td className="vc-photo">
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
            className={`vc-dot ${
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
        <td className="vc-title">{r.title}</td>
        <td className="vc-num vc-eff">{money(r.effective_price)}</td>
        <td className="vc-num">
          {r.fair_price ? money(r.fair_price) : "—"}
        </td>
        <td
          className="vc-num"
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
        <td className="vc-num">{money(r.asking_price)}</td>
        <td className="vc-cond">
          {r.enrichment ? r.enrichment.condition : "—"}
        </td>
        <td className="vc-mp">{r.marketplace}</td>
      </tr>
      {open && (
        <tr className="vc-expand">
          <td colSpan={9}>
            {r.enrichment ? (
              <div className="vc-enrich">
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
            <div className="vc-actions">
              <button className="va-primary">Author description</button>
              <button>Re-enrich</button>
              <button className="va-reject">Reject</button>
              <a href={r.url}>Open listing ↗</a>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function VariantC() {
  return (
    <div className="vc">
      <div className="vc-rail">
        <h4>Filters</h4>
        <label>
          <input type="checkbox" defaultChecked /> match
        </label>
        <label>
          <input type="checkbox" defaultChecked /> unsure
        </label>
        <label>
          <input type="checkbox" /> not_match
        </label>
        <label>
          Max price <input className="vc-input" defaultValue="600" />
        </label>
        <label>
          Availability
          <select defaultValue="live">
            <option value="all">all</option>
            <option value="live">live</option>
            <option value="dead">dead</option>
          </select>
        </label>
        <label>
          Sort
          <select defaultValue="price_asc">
            <option value="newest">newest</option>
            <option value="price_asc">price ↑</option>
            <option value="price_desc">price ↓</option>
          </select>
        </label>
      </div>
      <div className="vc-tablewrap">
        <div className="vc-head">
          <strong>{SEARCH.summary}</strong> — sifting{" "}
          {SEARCH.live.sifted}/{SEARCH.live.total} ·{" "}
          {SEARCH.live.new_deals} new deals
        </div>
        <div className="vc-scroll">
          <table className="vc-table">
            <thead>
              <tr>
                <th></th>
                <th>Verdict</th>
                <th>Listing</th>
                <th>Effective</th>
                <th>Fair</th>
                <th>Δ</th>
                <th>Ask</th>
                <th>Cond.</th>
                <th>MP</th>
              </tr>
            </thead>
            <tbody>
              {LISTINGS.map((r) => (
                <RowC key={r.id} r={r} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
