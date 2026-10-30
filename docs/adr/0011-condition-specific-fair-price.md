# 0011. Condition-specific fair price; cross-condition volatility

**Status:** accepted

**Supersedes:** ADR 0001 insofar as it treated the pooled (all-conditions) statistic as the basis for price.

Context: the glossary says fair price is a function of product and condition "never the product alone," while ADR 0001 describes the analysis window as pooled across all conditions for a product. Data review confirmed the conflict is real: mixing $300-complete and $80-for-parts observations in one pool measures structural spread, not market noise, which would mis-raise thresholds on every multi-condition product. We decided two distinct statistics. **Fair price** = median of trailing 90-day price observations for one (Product Identity, Condition); below n=5 there is no fair price and the deal verdict is `unknown` — honesty over fake precision. **Volatility analysis** — the IQR fence, MAD noise detection, and the 30-day surge detection of ADR 0001 — is pooled across all conditions per product line, because its subject is the movement of the product line, not the price of one condition. The global deal threshold defaults to 25%, overridable per Product Identity; market refinement may raise a threshold but never below the floor, per ADR 0001.
