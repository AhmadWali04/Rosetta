"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../lib/api";
import type { components } from "../../../lib/api-types";

type Candidate = components["schemas"]["PipelineCandidate"];
type Detail = components["schemas"]["CandidateDetail"];
type Preview = components["schemas"]["PromotionPreview"];
type Sort = "score_desc" | "score_asc" | "created_desc";
type Label = "valid" | "pending" | "rejected";
const HEADERS = { "X-Role": "hr" };
export const JOB_ID = "job-ai-intern-procogia";
const control = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-teal-600 disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${control} border-teal-800 bg-teal-800 text-white hover:bg-teal-900`;

function percent(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function message(error: unknown, fallback: string) {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") return error.detail;
  return fallback;
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="inline-block rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">{children}</span>;
}

export default function HrPortal() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<Sort>("score_desc");
  const [blind, setBlind] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [activeChunk, setActiveChunk] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [promotionPercent, setPromotionPercent] = useState(25);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [promotionBusy, setPromotionBusy] = useState(false);
  const [promotionError, setPromotionError] = useState("");
  const chunkRefs = useRef<Record<string, HTMLElement | null>>({});
  const previewRequest = useRef(0);

  useEffect(() => {
    let current = true;
    api.GET("/hr/applications", { headers: HEADERS, params: { query: { job_id: JOB_ID, status: status || undefined, sort } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (!data) throw new Error(message(error, "Could not load the candidate pipeline."));
        setCandidates(data);
      }).catch((err: unknown) => { if (current) setError(err instanceof Error ? err.message : "Could not load the candidate pipeline."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [status, sort, revision]);

  useEffect(() => {
    if (!selected) return;
    let current = true;
    api.GET("/hr/applications/{application_id}", { headers: HEADERS, params: { path: { application_id: selected } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (!data) throw new Error(message(error, "Could not load this candidate."));
        setDetail(data);
      }).catch((err: unknown) => { if (current) setDetailError(err instanceof Error ? err.message : "Could not load this candidate."); })
      .finally(() => { if (current) setDetailLoading(false); });
    return () => { current = false; };
  }, [selected, revision]);

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    setDetailLoading(true);
    setDetailError("");
    setActiveChunk(null);
    setReason("");
    setPreview(null);
    previewRequest.current += 1;
    setRevision((value) => value + 1);
  }, []);

  async function labelCandidate(label: Label) {
    if (!detail || saving) return;
    setSaving(true);
    setDetailError("");
    setNotice("");
    try {
      const { error, response } = await api.PATCH("/applications/{application_id}/status", {
        headers: HEADERS, params: { path: { application_id: detail.id } }, body: { status: label, reason: reason || undefined },
      });
      if (!response.ok) throw new Error(message(error, "Could not save the label. Refresh and try again."));
      setNotice(`Candidate labelled ${label}. Decision recorded in the audit log.`);
      refresh();
    } catch (err) { setDetailError(err instanceof Error ? err.message : "Could not save the label."); }
    finally { setSaving(false); }
  }

  async function previewPromotion() {
    const request = ++previewRequest.current;
    setPromotionBusy(true);
    setPromotionError("");
    setPreview(null);
    try {
      const { data, error } = await api.POST("/pools/{job_id}/promote/preview", { headers: HEADERS, params: { path: { job_id: JOB_ID } }, body: { percent: promotionPercent } });
      if (request !== previewRequest.current) return;
      if (!data) throw new Error(message(error, "Could not preview the pending pool."));
      setPreview(data);
    } catch (err) { if (request === previewRequest.current) setPromotionError(err instanceof Error ? err.message : "Could not preview the pending pool."); }
    finally { setPromotionBusy(false); }
  }

  async function confirmPromotion() {
    if (!preview || promotionBusy) return;
    setPromotionBusy(true);
    setPromotionError("");
    setNotice("");
    try {
      const { error, response } = await api.POST("/pools/{job_id}/promote", { headers: HEADERS, params: { path: { job_id: JOB_ID } }, body: { percent: preview.percent, application_ids: preview.application_ids } });
      if (!response.ok) throw new Error(message(error, "Pool changed or promotion failed. Preview the pool again before confirming."));
      setNotice(`${preview.application_ids.length} candidate(s) promoted to Valid. Decisions recorded in the audit log.`);
      refresh();
    } catch (err) {
      setPreview(null);
      setPromotionError(err instanceof Error ? err.message : "Promotion failed. Preview the pool again.");
    } finally { setPromotionBusy(false); }
  }

  function selectCandidate(id: string) {
    if (id === selected || saving || promotionBusy) return;
    setDetail(null);
    setDetailLoading(true);
    setDetailError("");
    setActiveChunk(null);
    setReason("");
    setSelected(id);
  }

  function cite(id: string) {
    setActiveChunk(id);
    chunkRefs.current[id]?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    chunkRefs.current[id]?.focus({ preventScroll: true });
  }

  function citationButtons(ids: string[], context: string) {
    return <div className="mt-2 flex flex-wrap gap-2">{ids.map((id, index) => <button key={id} type="button" disabled={blind} onClick={() => cite(id)} className="rounded border border-teal-200 bg-teal-50 px-2 py-1 text-xs font-medium text-teal-900 disabled:opacity-40" aria-label={`View evidence ${index + 1} for ${context}`}>↗ Evidence {index + 1}</button>)}</div>;
  }

  return <main className="min-h-screen bg-slate-50 text-slate-900">
    <div className="mx-auto max-w-screen-2xl px-5 py-8 sm:px-8">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div><p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-teal-800">SkillBridge / HR workspace</p><h1 className="text-3xl font-semibold tracking-tight">Candidate pipeline</h1><p className="mt-2 text-sm text-slate-600">AI Intern, Applied &amp; Agentic AI · ProCogia</p></div>
        <button type="button" className={control} onClick={refresh} disabled={loading || saving || promotionBusy}>Refresh pipeline</button>
      </header>
      <p className="mb-6 rounded-lg border border-teal-100 bg-teal-50 px-4 py-3 text-sm text-teal-950">AI recommendations support your review. Every hiring decision is made by a person. Scores use the current job pool and may change as applications are analyzed.</p>
      {notice && <p role="status" className="mb-4 rounded-lg bg-emerald-100 p-3 text-sm text-emerald-900">{notice}</p>}
      <section aria-label="Pending pool promotion" className="mb-6 rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div><h2 className="font-semibold">Review the pending pool</h2><p className="mt-1 text-sm text-slate-600">Preview the highest-scoring pending candidates before promoting them to Valid.</p></div>
          <div className="flex flex-wrap items-end gap-4"><label className="grid gap-2 text-sm font-medium">Promote top {promotionPercent}%<input aria-label="Promotion percentage" type="range" min="0" max="100" step="1" value={promotionPercent} disabled={promotionBusy} onChange={(event) => { setPromotionPercent(Number(event.target.value)); setPreview(null); previewRequest.current += 1; }} className="w-48 accent-teal-800" /></label><button type="button" className={control} onClick={previewPromotion} disabled={promotionBusy || saving}>{promotionBusy ? "Working…" : "Preview promotion"}</button></div>
        </div>
        {promotionError && <p role="alert" className="mt-4 text-sm text-red-800">{promotionError}</p>}
        {preview && <div className="mt-5 border-t border-slate-100 pt-4"><p className="text-sm font-medium">{preview.application_ids.length} of {preview.pending_count} pending candidates selected</p>{preview.candidates.length > 0 ? <ol className="my-3 flex flex-wrap gap-2">{preview.candidates.map((candidate, index) => <li key={candidate.id} className="rounded-lg bg-slate-100 px-3 py-2 text-sm">{index + 1}. {blind ? `Candidate ${candidate.id.slice(0, 8)}` : candidate.name} · {percent(candidate.score)}</li>)}</ol> : <p className="my-3 text-sm text-slate-500">No candidates selected. Adjust the percentage or label candidates Pending.</p>}<button type="button" className={primary} disabled={promotionBusy || !preview.application_ids.length} onClick={confirmPromotion}>Confirm promotion to Valid</button></div>}
      </section>
      <section aria-label="Pipeline" className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-5 border-b border-slate-200 p-5">
          <label className="flex items-center gap-2 text-sm">Status<select aria-label="Filter by status" value={status} onChange={(event) => { setLoading(true); setError(""); setStatus(event.target.value); }} className={control}><option value="">All statuses</option>{["submitted", "analyzing", "analyzed", "pending", "valid", "rejected", "intake_failed"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
          <label className="flex items-center gap-2 text-sm">Sort<select aria-label="Sort candidates" value={sort} onChange={(event) => { setLoading(true); setError(""); setSort(event.target.value as Sort); }} className={control}><option value="score_desc">Highest score</option><option value="score_asc">Lowest score</option><option value="created_desc">Newest first</option></select></label>
          <label className="ml-auto flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={blind} onChange={(event) => setBlind(event.target.checked)} className="h-4 w-4 accent-teal-800" />Blind mode</label>
        </div>
        {blind && <p className="border-b border-slate-100 px-5 py-3 text-xs text-slate-600">Blind review hides names, resume text, skill terms, explanations and audit details that may reveal identity. Turn it off to inspect source evidence.</p>}
        {error ? <p role="alert" className="p-6 text-red-800">{error} Use Refresh pipeline to retry.</p> : loading ? <p role="status" className="p-6 text-slate-500">Loading candidates…</p> : candidates.length === 0 ? <div className="p-12 text-center"><h2 className="font-semibold">No candidates in this view</h2><p className="mt-2 text-sm text-slate-500">Applications will appear here after submission. Try another status filter.</p></div> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr>{["Candidate", "Match score", "AI recommendation", "Must-haves", "Flags", "Status"].map((heading) => <th key={heading} scope="col" className="px-5 py-3 font-medium">{heading}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{candidates.map((candidate) => <tr key={candidate.id} className={candidate.id === selected ? "bg-teal-50" : "hover:bg-slate-50"}><td className="px-5 py-4"><button type="button" className="text-left font-semibold text-teal-900 underline-offset-4 hover:underline" disabled={saving || promotionBusy} onClick={() => selectCandidate(candidate.id)}>{blind ? `Candidate ${candidate.id.slice(0, 8)}` : candidate.name}</button></td><td className="px-5 py-4 font-semibold tabular-nums">{percent(candidate.score)}</td><td className="px-5 py-4">{candidate.recommendation ? <><span className="capitalize">{candidate.recommendation}</span><span className="mt-1 block text-xs text-slate-500">{percent(candidate.confidence)} confidence</span></> : <span className="text-slate-400">Awaiting analysis</span>}</td><td className="px-5 py-4 tabular-nums">{candidate.must_have_met}/{candidate.must_have_total}</td><td className="max-w-48 px-5 py-4">{candidate.flags.length ? candidate.flags.map((flag) => <span key={flag} className="mr-1 inline-block rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">{flag.replaceAll("_", " ")}</span>) : <span className="text-slate-400">None</span>}</td><td className="px-5 py-4"><Badge>{candidate.status.replaceAll("_", " ")}</Badge></td></tr>)}</tbody></table></div>}
      </section>
      {selected && <section aria-label="Candidate details" className="mt-6 rounded-xl border border-slate-200 bg-white p-5 sm:p-7">
        <div className="mb-5 flex items-center justify-between gap-4"><h2 className="text-xl font-semibold">{blind ? `Candidate ${selected.slice(0, 8)}` : detail?.name ?? "Candidate review"}</h2><button type="button" className={control} disabled={saving || promotionBusy} onClick={() => { setSelected(null); setDetail(null); }}>Close candidate</button></div>
        {detailError && <p role="alert" className="mb-4 text-sm text-red-800">{detailError}</p>}
        {detailLoading ? <p role="status">Loading candidate evidence…</p> : detail && <>
          <div className="mb-6 flex flex-wrap items-center gap-3"><Badge>{detail.status}</Badge><p className="text-sm text-slate-500">Match {percent(detail.score)} · AI {detail.recommendation ?? "awaiting analysis"} · {percent(detail.confidence)} confidence</p></div>
          {detail.flags.length > 0 && <div className="mb-5 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><strong>Review flags:</strong> {detail.flags.map((flag) => flag.replaceAll("_", " ")).join(", ")}</div>}
          <div className="grid gap-8 xl:grid-cols-2"><div>
            <h3 className="mb-4 font-semibold">Requirement checklist</h3>
            {detail.requirements.length ? <ul className="space-y-3">{detail.requirements.map((requirement) => <li key={requirement.id} className="rounded-lg border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><h4 className="text-sm font-medium">{requirement.text}</h4><Badge>{requirement.status.replaceAll("_", " ")}</Badge></div><p className="mt-1 text-xs text-slate-500">{requirement.kind.replaceAll("_", " ")}</p>{!blind && <p className="mt-3 text-sm leading-relaxed text-slate-600">{requirement.explanation || "No verified explanation available."}</p>}{citationButtons(requirement.chunk_ids, requirement.text)}</li>)}</ul> : <p className="text-sm text-slate-500">Requirement analysis is not available yet.</p>}
            <h3 className="mb-3 mt-7 font-semibold">Skill translation</h3>
            {blind ? <p className="text-sm text-slate-500">Skill terms are hidden during blind review.</p> : detail.skills.length ? <ul className="space-y-2">{detail.skills.map((skill, index) => <li key={`${skill.term}-${index}`} className="rounded-lg bg-slate-50 p-3 text-sm"><span className="font-medium">{skill.term}</span><span className="text-slate-400"> → </span>{skill.canonical ?? "Unmapped"}<span className="text-slate-400"> → </span>{skill.requirement_ids.map((id) => detail.requirements.find((requirement) => requirement.id === id)?.text ?? id).join("; ") || "No linked JD requirement"}{citationButtons(skill.chunk_ids, skill.term)}</li>)}</ul> : <p className="text-sm text-slate-500">No evidence-backed skills available.</p>}
          </div><div><h3 className="mb-4 font-semibold">Resume evidence</h3>{blind ? <p className="rounded-lg bg-slate-50 p-5 text-sm text-slate-500">Resume text is hidden during blind review.</p> : <div className="max-h-[40rem] space-y-3 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-4">{detail.chunks.length ? detail.chunks.map((chunk) => <article key={chunk.id} ref={(element) => { chunkRefs.current[chunk.id] = element; }} tabIndex={-1} data-testid={`chunk-${chunk.id}`} className={`rounded-lg border p-4 outline-none ${activeChunk === chunk.id ? "border-amber-400 bg-amber-100 ring-2 ring-amber-300" : "border-slate-200 bg-white"}`}><p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{chunk.section} · characters {chunk.char_start}–{chunk.char_end}</p><p className="whitespace-pre-wrap text-sm leading-relaxed">{activeChunk === chunk.id ? <mark className="bg-amber-200">{chunk.text}</mark> : chunk.text}</p></article>) : <p className="text-sm text-slate-500">Resume evidence will appear after intake.</p>}</div>}</div></div>
          <div className="mt-7 border-t border-slate-200 pt-6"><h3 className="font-semibold">Record your decision</h3><p className="mt-1 text-sm text-slate-500">Confirm or override the AI recommendation. Your action is saved to the audit log.</p><label className="mt-4 grid max-w-xl gap-2 text-sm">Reason (optional)<textarea className={control} value={reason} onChange={(event) => setReason(event.target.value)} maxLength={2000} disabled={saving} rows={2} /></label><div className="mt-3 flex flex-wrap gap-3">{(["valid", "pending", "rejected"] as const).map((label) => <button key={label} type="button" className={label === "valid" ? primary : control} disabled={saving || promotionBusy || !["analyzed", "pending", "valid", "rejected"].includes(detail.status)} onClick={() => labelCandidate(label)}>Label {label.charAt(0).toUpperCase() + label.slice(1)}</button>)}</div>{!["analyzed", "pending", "valid", "rejected"].includes(detail.status) && <p className="mt-3 text-xs text-slate-500">Decisions are available after analysis is complete.</p>}</div>
          <div className="mt-7 border-t border-slate-200 pt-6"><h3 className="mb-4 font-semibold">Audit history</h3>{detail.events.length ? <ol className="space-y-3">{detail.events.map((event) => <li key={event.id} className="border-l-2 border-teal-200 pl-4 text-sm"><p className="font-medium">{event.action.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-500">{event.actor} · {new Date(event.created_at).toLocaleString()}</p>{!blind && Object.keys(event.payload).length > 0 && <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-600">{JSON.stringify(event.payload, null, 2)}</pre>}</li>)}</ol> : <p className="text-sm text-slate-500">No audit events available.</p>}</div>
        </>}
      </section>}
    </div>
  </main>;
}
