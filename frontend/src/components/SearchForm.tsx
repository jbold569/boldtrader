// Shared Bargain Search draft form (ticket #44).
// Two mount points: the create/edit modals over the bargain lists, and chat's
// draft-confirm flow (the `draft` SSE event renders this same form pre-filled).
// Plain controlled inputs, no form library (docs/frontend-architecture.md).

import { useState } from "react";
import type { Draft } from "../api/types";
import "./form.css";

// The form keeps target_price as a string while typing; it becomes a JSON
// number (or null) only at submit time.
export interface SearchFormState {
  summary: string;
  product_identity: string;
  target_price: string;
  location: string;
  queries: string[];
  exclusions: string[];
}

const EMPTY: SearchFormState = {
  summary: "",
  product_identity: "",
  target_price: "",
  location: "",
  queries: [],
  exclusions: [],
};

// Per-field checks mirror the server's contract; the cross-field clash mirrors
// the API's 422 invalid_draft (a query repeating an exclusion), so the user
// sees it before submit instead of after.
function validate(f: SearchFormState): Record<string, string> {
  const errs: Record<string, string> = {};
  if (!f.summary.trim())
    errs.summary = "Name it something you'll recognise in the list later.";
  if (!f.product_identity.trim())
    errs.product_identity = "Make and model, or the spec that defines it.";
  if (f.queries.length === 0)
    errs.queries = "At least one keyword query to fan out.";
  if (!f.location.trim())
    errs.location =
      "A location is needed — local marketplaces return nothing without one.";
  const tp = f.target_price.trim();
  if (tp !== "" && (!Number.isFinite(Number(tp)) || Number(tp) <= 0))
    errs.target_price = "A positive number — e.g. 300, or leave it empty.";
  const clash = f.queries.find((q) =>
    f.exclusions.some((e) => e.trim().toLowerCase() === q.trim().toLowerCase()),
  );
  if (clash)
    errs.queries = `"${clash}" is in both queries and exclusions — a query can't also be excluded.`;
  return errs;
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

function TagInput({
  tags,
  onChange,
  suggestions,
  placeholder,
}: {
  tags: string[];
  onChange: (t: string[]) => void;
  suggestions: string[];
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !tags.includes(t)) onChange([...tags, t]);
    setText("");
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
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
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

export default function SearchForm({
  initial = EMPTY,
  onSubmit,
  submitting = false,
  serverError = null,
  submitLabel = "Create Bargain Search",
  onCancel,
}: {
  initial?: SearchFormState;
  onSubmit: (draft: Draft) => void;
  submitting?: boolean;
  serverError?: string | null;
  submitLabel?: string;
  onCancel?: () => void;
}) {
  const [f, setF] = useState<SearchFormState>(initial);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const set = (k: keyof SearchFormState) => (v: string) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const found = validate(f);
    setErrs(found);
    if (Object.keys(found).length > 0) return;
    onSubmit({
      summary: f.summary.trim(),
      product_identity: f.product_identity.trim(),
      queries: f.queries,
      exclusions: f.exclusions,
      target_price: f.target_price.trim() === "" ? null : Number(f.target_price),
      location: f.location.trim(),
    });
  };

  return (
    <form className="sform" onSubmit={submit}>
      {serverError && <div className="fs-warn">{serverError}</div>}
      <Field label="Summary" error={errs.summary}>
        <input
          value={f.summary}
          onChange={(e) => set("summary")(e.target.value)}
          placeholder="HP Z440 workstations under $300"
        />
      </Field>
      <Field label="Product identity" error={errs.product_identity}>
        <input
          value={f.product_identity}
          onChange={(e) => set("product_identity")(e.target.value)}
          placeholder="HP Z440"
        />
      </Field>
      <Field label="Target price" error={errs.target_price}>
        <input
          value={f.target_price}
          inputMode="decimal"
          onChange={(e) => set("target_price")(e.target.value)}
          placeholder="300"
        />
      </Field>
      <Field
        label="Location"
        error={errs.location}
        hint="Center of the hunt; radius is fixed server-side."
      >
        <input
          value={f.location}
          onChange={(e) => set("location")(e.target.value)}
          placeholder="Kenmore, WA"
        />
      </Field>
      <Field label="Queries" error={errs.queries}>
        <TagInput
          tags={f.queries}
          onChange={(t) => setF((prev) => ({ ...prev, queries: t }))}
          suggestions={SUGGESTED_QUERIES}
          placeholder="type a query, press Enter"
        />
      </Field>
      <Field label="Exclusions">
        <TagInput
          tags={f.exclusions}
          onChange={(t) => setF((prev) => ({ ...prev, exclusions: t }))}
          suggestions={SUGGESTED_EXCLUSIONS}
          placeholder="type an exclusion, press Enter"
        />
      </Field>
      <div className="sform-foot">
        {onCancel && (
          <button type="button" className="btn-cancel" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
