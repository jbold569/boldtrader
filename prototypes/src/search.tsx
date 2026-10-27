// Search-form prototype — wayfinder #33.
// Three structural takes on the two search surfaces, switchable with ?form=a|b|c:
//   A  classic stack: horizontal ad-hoc search row, one-column draft form,
//      submit-time validation, primary button bottom-right, label "Location"
//   B  chips + collapse: inline search with chip refinements; draft grouped with
//      tag inputs, tucked-away fields, primary button at top, blur validation,
//      label "Locality" (the GLOSSARY term)
//   C  panel + stepper: ad-hoc search lives in a slide-over panel; the draft is
//      a 3-step wizard (What -> How -> Where) with per-step gating, "Locality"
// Throwaway. Fake data inline; no backend calls.

import { useState } from "react";
import { LISTINGS, money, type ResultListing } from "./data";
import { patchUrl } from "./filters";
import { img } from "./img";
import "./search.css";

const MARKETPLACES = [
  { key: "all", label: "All marketplaces" },
  { key: "offerup", label: "OfferUp" },
  { key: "facebook", label: "Facebook" },
  { key: "ebay", label: "eBay" },
];
// Local marketplaces are metro-scoped: without a locality they see nothing
// (GLOSSARY: Locality). eBay does not need one.
const LOCAL = new Set(["offerup", "facebook"]);

// ---------------------------------------------------------------- validation

interface Draft {
  summary: string;
  product_identity: string;
  queries: string[];
  exclusions: string[];
  target_price: string;
  location: string;
}

const EMPTY_DRAFT: Draft = {
  summary: "",
  product_identity: "",
  queries: [],
  exclusions: [],
  target_price: "",
  location: "",
};

const EDIT_DRAFT: Draft = {
  summary: "HP Z440 workstations under $300",
  product_identity: "HP Z440",
  queries: ["hp z440", "z440 workstation"],
  exclusions: ["no monitor"],
  target_price: "300",
  location: "Kenmore, WA",
};

interface DraftErrors {
  fields: Record<string, string>;
  server: string | null;
}

// Client-side checks are per-field; the cross-field clash mimics what the real
// API's 422 invalid_draft carries, so the two feedback layers look different.
function validateDraft(d: Draft): DraftErrors {
  const fields: Record<string, string> = {};
  if (!d.summary.trim())
    fields.summary = "Name it something you'll recognise in the list later.";
  if (!d.product_identity.trim())
    fields.product_identity = "Make and model, or the spec that defines it.";
  if (d.queries.length === 0)
    fields.queries = "At least one keyword query to fan out.";
  if (d.target_price.trim() !== "" && !Number.isFinite(Number(d.target_price)))
    fields.target_price = "Numbers only — e.g. 300";
  if (!d.location.trim())
    fields.location = "Local marketplaces return nothing without a locality.";
  const clash = d.queries.find((q) =>
    d.exclusions.some(
      (e) => e.toLowerCase().trim() === q.toLowerCase().trim()
    )
  );
  const server = clash
    ? `422 invalid_draft — “${clash}” is in both queries and exclusions.`
    : null;
  return { fields, server };
}

function validateFind(q: string, marketplace: string, location: string) {
  const fields: Record<string, string> = {};
  if (!q.trim()) fields.q = "Type what you're after.";
  else if (q.trim().length < 2) fields.q = "At least two characters.";
  if (LOCAL.has(marketplace) && !location.trim())
    fields.location = "Required for local marketplaces.";
  return fields;
}

// ---------------------------------------------------------------- shared bits

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="fd">
      <span className="fd-label">{label}</span>
      {children}
      {error ? (
        <span className="fd-err">{error}</span>
      ) : hint ? (
        <span className="fd-hint">{hint}</span>
      ) : null}
    </label>
  );
}

const SUGGESTED_QUERIES = [
  "hp z440",
  "dell optiplex 7040",
  "xeon workstation",
  "lenovo thinkstation",
  "32gb ddr4 ram",
];
const SUGGESTED_EXCLUSIONS = [
  "no monitor",
  "no keyboard",
  "not refurbished",
  "no tower only",
];

function TagInput({
  tags,
  onChange,
  suggestions,
  placeholder,
  invalid,
}: {
  tags: string[];
  onChange: (t: string[]) => void;
  suggestions: string[];
  placeholder: string;
  invalid?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const t = draft.trim();
    if (t && !tags.includes(t)) onChange([...tags, t]);
    setDraft("");
  };
  return (
    <div className="tagin">
      <div className="tagin-row">
        {tags.map((t) => (
          <span key={t} className="chip tagin-chip">
            {t}
            <button
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => onChange(tags.filter((x) => x !== t))}
            >
              ✕
            </button>
          </span>
        ))}
        <input
          className={invalid ? "is-bad" : ""}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
      </div>
      <div className="tagin-sug">
        {suggestions
          .filter((s) => !tags.includes(s))
          .slice(0, 4)
          .map((s) => (
            <button type="button" key={s} onClick={() => onChange([...tags, s])}>
              + {s}
            </button>
          ))}
      </div>
    </div>
  );
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="mdl-scrim" onClick={onClose}>
      <div
        className="mdl"
        role="dialog"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mdl-head">
          <h2>{title}</h2>
          <button type="button" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="mdl-body">{children}</div>
      </div>
    </div>
  );
}

// Ad-hoc Search result cards: raw listing, no verdict, no Enrichment.
function RawCards({ items }: { items: ResultListing[] }) {
  if (items.length === 0)
    return <p className="fs-empty muted">Nothing matched. Try fewer words.</p>;
  return (
    <div className="fs-grid">
      {items.map((r) => (
        <article className="fs-card" key={r.id}>
          <div className="fs-thumb">
            <img
              src={img(r)}
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).src = img({
                  ...r,
                  image_url: null,
                });
              }}
              alt=""
            />
          </div>
          <h3 className="fs-title">
            <a href={r.url}>{r.title}</a>
          </h3>
          <div className="fs-meta">
            <span className="chip">{r.marketplace}</span>
            <strong>{money(r.asking_price)}</strong>
          </div>
        </article>
      ))}
    </div>
  );
}

function fakeFind(q: string): ResultListing[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return LISTINGS;
  return LISTINGS.filter((r) =>
    words.some((w) => r.title.toLowerCase().includes(w))
  );
}

// Success/failure mimic: after a submit, a green confirmation strip replaces the
// form area. The fake "server" never fails on the ad-hoc side; only marketplace
// partial-failure is shown, per contract (failures reported, not fatal).
function FindResults({
  q,
  marketplace,
}: {
  q: string;
  marketplace: string;
}) {
  const items = fakeFind(q);
  return (
    <>
      {marketplace === "all" && (
        <div className="fs-warn">
          Facebook failed to respond — showing eBay and OfferUp only.
        </div>
      )}
      <p className="fs-count muted">
        {items.length} listings · page 1 of 3
      </p>
      <RawCards items={items} />
    </>
  );
}

// ============================================================ VARIANT A
function FindA() {
  const [q, setQ] = useState("");
  const [mp, setMp] = useState("all");
  const [loc, setLoc] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [searched, setSearched] = useState(false);
  const search = () => {
    const e = validateFind(q, mp, loc);
    setErrs(e);
    if (Object.keys(e).length === 0) {
      patchUrl({ q, marketplace: mp, location: loc });
      setSearched(true);
    }
  };
  return (
    <div className="fa">
      <div className="fa-row">
        <Field label="Search" error={errs.q}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder="gaming pc, ddr4, thinkstation…"
            enterKeyHint="search"
          />
        </Field>
        <Field label="Marketplace">
          <select value={mp} onChange={(e) => setMp(e.target.value)}>
            {MARKETPLACES.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Location" error={errs.location}>
          <input
            value={loc}
            onChange={(e) => setLoc(e.target.value)}
            placeholder="City, State"
          />
        </Field>
        <button className="fa-go" onClick={search}>
          Search
        </button>
      </div>
      {searched && <FindResults q={q} marketplace={mp} />}
    </div>
  );
}

function DraftA({
  mode,
  onClose,
}: {
  mode: "create" | "edit";
  onClose: () => void;
}) {
  const [d, setD] = useState<Draft>(mode === "edit" ? EDIT_DRAFT : EMPTY_DRAFT);
  const [errs, setErrs] = useState<DraftErrors>({ fields: {}, server: null });
  const [saved, setSaved] = useState(false);
  const set = (k: keyof Draft) => (v: string) => setD({ ...d, [k]: v });
  const save = () => {
    const e = validateDraft(d);
    setErrs(e);
    if (Object.keys(e.fields).length === 0 && !e.server) setSaved(true);
  };
  if (saved)
    return (
      <p className="ok-strip">
        Bargain Search saved — fanning out across 3 marketplaces.
      </p>
    );
  return (
    <>
      {errs.server && <div className="fs-warn">{errs.server}</div>}
      <div className="fa-col">
        <Field label="Summary" error={errs.fields.summary}>
          <input
            value={d.summary}
            onChange={(e) => set("summary")(e.target.value)}
            placeholder="HP Z440 workstations under $300"
          />
        </Field>
        <Field label="Product identity" error={errs.fields.product_identity}>
          <input
            value={d.product_identity}
            onChange={(e) => set("product_identity")(e.target.value)}
            placeholder="HP Z440"
          />
        </Field>
        <Field label="Target price" error={errs.fields.target_price}>
          <input
            value={d.target_price}
            inputMode="decimal"
            onChange={(e) => set("target_price")(e.target.value)}
            placeholder="300"
          />
        </Field>
        <Field
          label="Location"
          error={errs.fields.location}
          hint="Center of the hunt; radius is fixed server-side."
        >
          <input
            value={d.location}
            onChange={(e) => set("location")(e.target.value)}
            placeholder="Kenmore, WA"
          />
        </Field>
        <Field label="Queries" error={errs.fields.queries}>
          <TagInput
            tags={d.queries}
            onChange={(t) => setD({ ...d, queries: t })}
            suggestions={SUGGESTED_QUERIES}
            placeholder="type a query, press Enter"
          />
        </Field>
        <Field label="Exclusions">
          <TagInput
            tags={d.exclusions}
            onChange={(t) => setD({ ...d, exclusions: t })}
            suggestions={SUGGESTED_EXCLUSIONS}
            placeholder="type an exclusion, press Enter"
          />
        </Field>
        <div className="fa-foot">
          <button onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save}>
            {mode === "edit" ? "Save changes" : "Create Bargain Search"}
          </button>
        </div>
      </div>
    </>
  );
}

// ============================================================ VARIANT B
function FindB() {
  const [q, setQ] = useState("");
  const [mp, setMp] = useState("all");
  const [loc, setLoc] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(false);
  const [searched, setSearched] = useState(false);
  const search = () => {
    const e = validateFind(q, mp, loc);
    setErrs(e);
    if (Object.keys(e).length === 0) {
      patchUrl({ q, marketplace: mp, location: loc });
      setSearched(true);
    }
  };
  const mpLabel =
    MARKETPLACES.find((m) => m.key === mp)?.label ?? "All marketplaces";
  return (
    <div className="fb2">
      <div className="fb2-bar">
        <input
          className="fb2-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="Search the marketplaces…"
          enterKeyHint="search"
        />
        <button className="fb2-go" onClick={search}>
          Search
        </button>
      </div>
      {errs.q && <div className="fd-err">{errs.q}</div>}
      <div className="fb2-chips">
        <button
          className={`fchip${open ? " on" : ""}`}
          onClick={() => setOpen(!open)}
        >
          ⚙ {mpLabel}
          {loc ? ` · ${loc}` : ""}
        </button>
      </div>
      {open && (
        <div className="fb2-panel">
          <Field label="Marketplace">
            <select value={mp} onChange={(e) => setMp(e.target.value)}>
              {MARKETPLACES.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Locality" error={errs.location}>
            <input
              value={loc}
              onChange={(e) => setLoc(e.target.value)}
              placeholder="Kenmore, WA"
            />
          </Field>
          <button className="btn-primary fb2-apply" onClick={search}>
            Apply
          </button>
        </div>
      )}
      {searched && <FindResults q={q} marketplace={mp} />}
    </div>
  );
}

// B's draft: what you want is always open; how it hunts + where are tucked.
function DraftB({
  mode,
  onClose,
}: {
  mode: "create" | "edit";
  onClose: () => void;
}) {
  const [d, setD] = useState<Draft>(mode === "edit" ? EDIT_DRAFT : EMPTY_DRAFT);
  const [errs, setErrs] = useState<DraftErrors>({ fields: {}, server: null });
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);
  const blur = (k: string) => setTouched({ ...touched, [k]: true });
  const errFor = (k: string) => (touched[k] ? errs.fields[k] : undefined);
  const save = () => {
    const e = validateDraft(d);
    setErrs(e);
    setTouched({
      summary: true,
      product_identity: true,
      queries: true,
      location: true,
    });
    if (Object.keys(e.fields).length === 0 && !e.server) setSaved(true);
  };
  if (saved)
    return (
      <p className="ok-strip">
        Bargain Search saved — fanning out across 3 marketplaces.
      </p>
    );
  return (
    <>
      {errs.server && <div className="fs-warn">{errs.server}</div>}
      <div className="fb2-save-top">
        <button className="btn-primary" onClick={save}>
          {mode === "edit" ? "Save changes" : "Create Bargain Search"}
        </button>
        <span className="muted fb2-save-hint">
          Two sections, one tap each. Nothing required.
        </span>
      </div>
      <section className="fsec">
        <h3>What you want</h3>
        <Field label="Summary" error={errFor("summary")}>
          <input
            value={d.summary}
            onBlur={() => blur("summary")}
            onChange={(e) => setD({ ...d, summary: e.target.value })}
            placeholder="HP Z440 workstations under $300"
          />
        </Field>
        <Field label="Product identity" error={errFor("product_identity")}>
          <input
            value={d.product_identity}
            onBlur={() => blur("product_identity")}
            onChange={(e) => setD({ ...d, product_identity: e.target.value })}
            placeholder="HP Z440"
          />
        </Field>
      </section>
      <details className="fsec" open={mode === "edit"}>
        <summary>How it hunts — queries and exclusions</summary>
        <Field label="Queries" error={errFor("queries")}>
          <TagInput
            tags={d.queries}
            onChange={(t) => setD({ ...d, queries: t })}
            suggestions={SUGGESTED_QUERIES}
            placeholder="type a query, press Enter"
          />
        </Field>
        <Field
          label="Exclusions"
          hint="Fed into Sifting; the listing gets dropped on these words."
        >
          <TagInput
            tags={d.exclusions}
            onChange={(t) => setD({ ...d, exclusions: t })}
            suggestions={SUGGESTED_EXCLUSIONS}
            placeholder="type an exclusion, press Enter"
          />
        </Field>
      </details>
      <details className="fsec">
        <summary>Where and how much</summary>
        <Field
          label="Locality"
          error={errFor("location")}
          hint="Center point; local marketplaces need it."
        >
          <input
            value={d.location}
            onBlur={() => blur("location")}
            onChange={(e) => setD({ ...d, location: e.target.value })}
            placeholder="Kenmore, WA"
          />
        </Field>
        <Field label="Target price" error={errFor("target_price")}>
          <input
            value={d.target_price}
            inputMode="decimal"
            onBlur={() => blur("target_price")}
            onChange={(e) => setD({ ...d, target_price: e.target.value })}
            placeholder="300"
          />
        </Field>
      </details>
      <div className="fb2-foot">
        <button onClick={onClose}>Cancel</button>
      </div>
    </>
  );
}

// ============================================================ VARIANT C
// Ad-hoc search lives off-canvas; the visible chrome is the active-query echo.
function FindC() {
  const [q, setQ] = useState("");
  const [mp, setMp] = useState("all");
  const [loc, setLoc] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<{
    q: string;
    mp: string;
    loc: string;
  } | null>(null);
  const search = () => {
    const e = validateFind(q, mp, loc);
    setErrs(e);
    if (Object.keys(e).length === 0) {
      setActive({ q, mp, loc });
      patchUrl({ q, marketplace: mp, location: loc });
      setOpen(false);
    }
  };
  const mpLabel =
    MARKETPLACES.find((m) => m.key === (active?.mp ?? mp))?.label ??
    "All marketplaces";
  return (
    <div className="fc">
      {!open && (
        <div className="fc-echo">
          {active ? (
            <span className="fc-echo-txt">
              “{active.q}” · {mpLabel}
              {active.loc ? ` · ${active.loc}` : ""}
            </span>
          ) : (
            <span className="muted">No search yet.</span>
          )}
          <button onClick={() => setOpen(true)}>
            {active ? "✎ Change search" : "🔍 New search"}
          </button>
        </div>
      )}
      {open && (
        <div className="fc-panel">
          <h2>Search the marketplaces</h2>
          <Field label="Search" error={errs.q}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="gaming pc, ddr4…"
              enterKeyHint="search"
            />
          </Field>
          <Field label="Marketplace">
            <select value={mp} onChange={(e) => setMp(e.target.value)}>
              {MARKETPLACES.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Locality" error={errs.location}>
            <input
              value={loc}
              onChange={(e) => setLoc(e.target.value)}
              placeholder="Kenmore, WA"
            />
          </Field>
          <div className="fc-panel-foot">
            <button onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn-primary" onClick={search}>
              Search
            </button>
          </div>
        </div>
      )}
      {active && !open && (
        <FindResults q={active.q} marketplace={active.mp} />
      )}
    </div>
  );
}

// C's draft: 3-step wizard, each step gates on its own fields.
const STEPS = [
  { key: "what", title: "What you want", fields: ["summary", "product_identity"] },
  { key: "how", title: "How it hunts", fields: ["queries", "exclusions"] },
  { key: "where", title: "Where and how much", fields: ["location", "target_price"] },
] as const;

function DraftC({
  mode,
  onClose,
}: {
  mode: "create" | "edit";
  onClose: () => void;
}) {
  const [d, setD] = useState<Draft>(mode === "edit" ? EDIT_DRAFT : EMPTY_DRAFT);
  const [step, setStep] = useState(0);
  const [errs, setErrs] = useState<DraftErrors>({ fields: {}, server: null });
  const [saved, setSaved] = useState(false);
  const next = () => {
    const e = validateDraft(d);
    setErrs(e);
    const bad = STEPS[step].fields.filter((f) => e.fields[f]);
    if (bad.length > 0) return;
    setStep(step + 1);
  };
  const save = () => {
    const e = validateDraft(d);
    setErrs(e);
    const bad = STEPS[2].fields.filter((f) => e.fields[f]);
    if (bad.length > 0 || e.server) return;
    setSaved(true);
  };
  if (saved)
    return (
      <p className="ok-strip">
        Bargain Search saved — fanning out across 3 marketplaces.
      </p>
    );
  const cur = STEPS[step];
  const set = (k: keyof Draft) => (v: string) => setD({ ...d, [k]: v });
  return (
    <div className="fc-wiz">
      <ol className="fc-dots">
        {STEPS.map((s, i) => (
          <li
            key={s.key}
            className={
              i === step ? "on" : i < step ? "done" : ""
            }
          >
            {i + 1}. {s.title}
          </li>
        ))}
      </ol>
      {errs.server && <div className="fs-warn">{errs.server}</div>}
      {cur.key === "what" && (
        <>
          <Field label="Summary" error={errs.fields.summary}>
            <input
              value={d.summary}
              onChange={(e) => set("summary")(e.target.value)}
              placeholder="HP Z440 workstations under $300"
            />
          </Field>
          <Field label="Product identity" error={errs.fields.product_identity}>
            <input
              value={d.product_identity}
              onChange={(e) => set("product_identity")(e.target.value)}
              placeholder="HP Z440"
            />
          </Field>
        </>
      )}
      {cur.key === "how" && (
        <>
          <Field label="Queries" error={errs.fields.queries}>
            <TagInput
              tags={d.queries}
              onChange={(t) => setD({ ...d, queries: t })}
              suggestions={SUGGESTED_QUERIES}
              placeholder="type a query, press Enter"
            />
          </Field>
          <Field label="Exclusions">
            <TagInput
              tags={d.exclusions}
              onChange={(t) => setD({ ...d, exclusions: t })}
              suggestions={SUGGESTED_EXCLUSIONS}
              placeholder="type an exclusion, press Enter"
            />
          </Field>
        </>
      )}
      {cur.key === "where" && (
        <>
          <Field
            label="Locality"
            error={errs.fields.location}
            hint="Center point; local marketplaces need it."
          >
            <input
              value={d.location}
              onChange={(e) => set("location")(e.target.value)}
              placeholder="Kenmore, WA"
            />
          </Field>
          <Field label="Target price" error={errs.fields.target_price}>
            <input
              value={d.target_price}
              inputMode="decimal"
              onChange={(e) => set("target_price")(e.target.value)}
              placeholder="300"
            />
          </Field>
        </>
      )}
      <div className="fc-wiz-foot">
        {step > 0 && (
          <button onClick={() => setStep(step - 1)}>← Back</button>
        )}
        <button onClick={onClose}>Cancel</button>
        {step < STEPS.length - 1 ? (
          <button className="btn-primary" onClick={next}>
            Next →
          </button>
        ) : (
          <button className="btn-primary" onClick={save}>
            {mode === "edit" ? "Save changes" : "Create Bargain Search"}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- host

export default function SearchPage({
  variant,
}: {
  variant: "a" | "b" | "c";
}) {
  const [modal, setModal] = useState<null | "create" | "edit">(null);
  const V = variant === "b" ? "B" : variant === "c" ? "C" : "A";
  const Find = variant === "b" ? FindB : variant === "c" ? FindC : FindA;
  const Draft =
    variant === "b" ? DraftB : variant === "c" ? DraftC : DraftA;
  return (
    <div className="sp">
      <div className="sp-head">
        <h1>Search · variant {V}</h1>
        <div className="sp-actions">
          <button className="btn-primary" onClick={() => setModal("create")}>
            ＋ Bargain Search
          </button>
          <button onClick={() => setModal("edit")}>✎ Edit one (prefilled)</button>
        </div>
      </div>
      <Find />
      {modal && (
        <Modal
          title={
            modal === "edit"
              ? "Edit Bargain Search"
              : "New Bargain Search"
          }
          onClose={() => setModal(null)}
        >
          <Draft mode={modal} onClose={() => setModal(null)} />
        </Modal>
      )}
    </div>
  );
}
