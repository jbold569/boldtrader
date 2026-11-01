# Price-history archives in this folder

Static reference data, captured 2026-11-01. Not live. Re-capture only if the
source changes or a gap must be closed.

## shuckstop-db.csv

- Source: https://shucks.top/so-long/shuckstop-db.csv — the farewell dump left
  by Ryan when ShuckStop shut down.
- Schema: `Date,Timestamp,TB,Model,Site,Price,In_Stock`
- 62,262 rows, 2020-06-23 → 2026-06-09, daily.
- 3 external-drive models (Easystore, Elements, My Book) × 8–24 TB × 5 sellers
  (amazon, bestbuy, bh, ebay, newegg).
- Coverage holes: `amazon` stops 2024-01-18, `bh` stops 2025-01-17, plus a
  10-day gap 2024-04-20→30 (site redesigns / blocking-rule changes, per Ryan).
- New-retail asking prices only. No used/refurb/secondhand pricing.

## shuckstop-lowest.csv

- Source: https://shucks.top/so-long/shuckstop-lowest.csv
- Per capacity+model: lowest-ever price/site/date and last-decent
  price/site/date. Same 3-model scope. Hand-checked summary of the DB above.

## listofdisks-price-history.csv + listofdisks-products.csv

- Source: https://www.listofdisks.com — successor site recommended by ShuckStop.
  Captured by `.scratch/listofdisks-capture/capture.py` (read-only crawl of
  public `/products/<slug>?range=365` pages; robots.txt allows all but
  /admin /alerts /api).
- `price-history`: `slug,date,median_price_per_tb,min_price_per_tb` —
  26,092 rows, 518 products, 2026-08-17 → 2026-11-01 (77 days).
- `products`: `slug,name,mpn,captured_at,points` — 752 products.
  234 slugs rendered no chart (no points): not a parser miss, the pages
  genuinely have no history for those SKUs.
- All NEW-retail prices across 8 US retailers. Short history (started ~Aug 2026).

## What we do NOT have here

- Secondhand / used / refurbished price history. Neither source tracks it.
  All rows are new-goods retail asks. If secondhand fair value matters for a
  component, this folder will mislead — boldtrader's own observed asks are
  the only used-side history.
- Deep history for any component beyond hard drives. Both sites are storage-only.

## Re-capture

```
python3 .scratch/listofdisks-capture/capture.py
```
Overwrites the two listofdisks CSVs. Needs network access to listofdisks.com.
