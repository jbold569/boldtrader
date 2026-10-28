// Chat Sessions page — the destination "View all →" points at.
// Lists every Chat Session with a fuzzy search box on top to find past
// sessions of interest. Fake data inline (32 sessions); no backend.
//
// Fuzzy = case-insensitive subsequence match with a contiguous-word bonus,
// good enough to judge whether fuzzy search is the right finder here vs an
// exact/substring search. No ranking beyond that.

import { useMemo, useState } from "react";
import "./sessions.css";

interface Session {
  id: string;
  title: string;
  when: string;
  unread: boolean;
  blurb: string;
}

const SESSIONS: Session[] = [
  ["HP Z440 workstations under $300", "2m", true, "Sifted 47 listings; 12 confirmed matches. Draft saved."],
  ["Is this Dell OptiPlex a deal?", "18m", true, "Checked fair price against eBay sold comps."],
  ["DDR4 3200 price history", "44m", false, "Trend over 90 days: $34 → $29."],
  ["Authored description — Lenovo M920q", "1h", false, "Rewrote description to improve match quality."],
  ["Flip values for RTX 3060 bundles", "2h", false, "Bundle math; margins thin after shipping."],
  ["MacBook Air M1 complete under $600", "3h", true, "Active bargain search, 3 new deals flagged."],
  ["ThinkPad T480 battery questions", "4h", false, "Internal + external battery health checks."],
  ["OfferUp vs eBay fee comparison", "5h", false, "Fees change effective-price ranking."],
  ["Exclusion list for monitor listings", "6h", true, "\"no monitor\" keeps catching keyboards too."],
  ["Surface Pro 7 screen replacement cost", "7h", false, "$219 part + labor; kills the margin."],
  ["Kenmore WA pickup radius", "8h", false, "Location parsing for locality filters."],
  ["Bike trailers under $80", "9h", false, "Off-topic test of the search terms."],
  ["Steam deck OLED 512GB deals", "10h", true, "2 matches this morning."],
  ["iPad 9th gen wifi 64GB", "11h", false, "Mostly blocked by condition issues."],
  ["Why did this get filtered out?", "12h", false, "Debugging an exclusion rule."],
  ["Refurbished vs used classification", "13h", false, "Glossary refinement for enrichment."],
  ["Batch re-enrichment results", "14h", false, "24 listings re-enriched, 2 failed."],
  ["Standing search: Herman Miller Aeron", "15h", true, "Long-running search, weekly digest."],
  ["Craigslist is dead for this", "16h", false, "Marketplace coverage note."],
  ["GPU price crash watch", "17h", false, "Set target price at $180."],
  ["Camera lens 50mm f1.8 under $120", "18h", false, "4 matches, all with fungus."],
  ["Rejection reasons matter", "19h", false, "Feeding exclusions back into the sift."],
  ["Coffee grinder Baratza under $60", "20h", false, "Quiet week."],
  ["Ergonomic keyboard split under $100", "21h", false, "3 unsure verdicts."],
  ["Standing search: espresso machines", "22h", false, "Paused; too noisy."],
  ["Vacuum robot deals", "23h", false, "Ruled out — not our category."],
  ["Treadmill under $200 folding", "1d", false, "All dead within a day."],
  ["Stand mixer KitchenAid used", "1d", false, "Price floor is holding at $180."],
  ["Monitor arm dual under $60", "2d", false, "Good matches, sold fast."],
  ["Desk riser standing converter", "2d", false, "2 matches yesterday."],
  ["Office chair mesh under $90", "2d", false, "Condition risk too high."],
  ["First session — how does this work?", "3d", false, "Onboarding chat."],
].map((r, i) => ({
  id: `s${String(i + 1).padStart(2, "0")}`,
  title: r[0] as string,
  when: r[1] as string,
  unread: r[2] as boolean,
  blurb: r[3] as string,
}));

// subsequence fuzzy match: every query char appears in order in the target.
// bonus points for a contiguous word hit. Returns -1 for no match.
function fuzzy(q: string, text: string): number {
  if (!q) return 0;
  const t = text.toLowerCase();
  const s = q.toLowerCase().trim();
  let score = 0;
  let ti = 0;
  for (const ch of s) {
    if (ch === " ") continue;
    const at = t.indexOf(ch, ti);
    if (at === -1) return -1;
    score += at === ti ? 2 : 1;
    ti = at + 1;
  }
  if (t.includes(s)) score += 10;
  return score;
}

export default function SessionsPage() {
  const [q, setQ] = useState("");
  const results = useMemo(() => {
    if (!q.trim()) return SESSIONS;
    return SESSIONS.map((s) => ({ s, sc: fuzzy(q, s.title) }))
      .filter((r) => r.sc >= 0)
      .sort((a, b) => b.sc - a.sc)
      .map((r) => r.s);
  }, [q]);

  return (
    <div className="sp">
      <div className="sp-search">
        <input
          autoFocus
          type="search"
          placeholder="Search past sessions…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search past chat sessions"
        />
        <span className="sp-count muted" aria-live="polite">
          {results.length} of {SESSIONS.length}
        </span>
      </div>
      {results.length === 0 ? (
        <p className="sp-empty muted">No session matches “{q}”.</p>
      ) : (
        <ul className="sp-list">
          {results.map((s) => (
            <li key={s.id} className="sp-item">
              <a href="#" onClick={(e) => e.preventDefault()}>
                {s.unread && <span className="dot" />}
                <span className="sp-title">{s.title}</span>
                <span className="muted sp-when">{s.when}</span>
              </a>
              <p className="muted sp-blurb">{s.blurb}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
