// ListingCard (ticket #48): one raw Marketplace listing on the ad-hoc
// Search page — thumbnail, the title hyperlinked out to the Marketplace
// (the title IS the link, per ResultCard's settled pattern), and the ask.
// No verdict, no Enrichment, no actions: the ad-hoc payload carries none
// (docs/frontend-architecture.md — two components, not optional-props soup).

import type { ListingCard as ListingCardData } from "../api/types";
import "./adhoc.css";

export default function ListingCard({ card }: { card: ListingCardData }) {
  return (
    <article className="lc">
      {card.image_url && (
        <div className="lc-thumb">
          <img
            src={card.image_url}
            alt=""
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        </div>
      )}
      <h3 className="lc-title">
        <a href={card.url} target="_blank" rel="noreferrer">
          {card.title}
        </a>
      </h3>
      <div className="lc-meta">
        {card.marketplace && <span className="chip">{card.marketplace}</span>}
        <strong>
          {card.asking_price === null
            ? "?"
            : `$${card.asking_price.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
        </strong>
      </div>
    </article>
  );
}
