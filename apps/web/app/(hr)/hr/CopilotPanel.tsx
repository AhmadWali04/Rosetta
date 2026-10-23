"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../../../lib/api";
import type { components } from "../../../lib/api-types";

type Citation = components["schemas"]["CopilotCitation"];
type CopilotEvent = components["schemas"]["CopilotEvent"];
type Result = components["schemas"]["CopilotResult"];
type Request = components["schemas"]["CopilotRequest"];
type Confirmation = components["schemas"]["CopilotConfirmation"];
type Run = components["schemas"]["CopilotRunOut"];

type Props = {
  jobId: string;
  candidateId: string | null;
  blind: boolean;
  onCitation: (citation: Citation) => void;
  onStatusChanged: () => void;
};

const control = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-teal-600 disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${control} border-teal-800 bg-teal-800 text-white hover:bg-teal-900`;
const headers = { "X-Role": "hr", "Content-Type": "application/json" };

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isCitation(value: unknown): value is Citation {
  return object(value)
    && ["chunk_id", "application_id", "text", "section"].every((key) => typeof value[key] === "string")
    && typeof value.char_start === "number" && typeof value.char_end === "number";
}

function isResult(value: unknown): value is Result {
  if (!object(value)) return false;
  return typeof value.run_id === "string" && typeof value.route === "string"
    && Array.isArray(value.claims)
    && value.claims.every((claim) => object(claim) && typeof claim.text === "string" && strings(claim.chunk_ids))
    && Array.isArray(value.citations) && value.citations.every(isCitation)
    && typeof value.explanation === "string" && typeof value.confidence === "number"
    && Number.isFinite(value.confidence) && strings(value.warnings) && strings(value.steps)
    && typeof value.retries === "number" && typeof value.needs_confirmation === "boolean"
    && (value.proposal === null || (object(value.proposal)
      && typeof value.proposal.application_id === "string"
      && typeof value.proposal.status === "string" && typeof value.proposal.reason === "string"));
}

function readEvent(value: unknown): CopilotEvent {
  if (!object(value) || !["queued", "progress", "result", "error"].includes(String(value.event))
    || typeof value.run_id !== "string" || typeof value.status !== "string"
    || !(value.result === null || isResult(value.result))
    || !(value.error === null || typeof value.error === "string")) {
    throw new Error("The copilot returned an invalid event. Check the run status before retrying.");
  }
  return value as CopilotEvent;
}

function isRun(value: unknown): value is Run {
  return object(value)
    && ["id", "job_id", "scope", "message", "status", "created_at"].every((key) => typeof value[key] === "string")
    && (value.result === null || isResult(value.result))
    && (value.error === null || typeof value.error === "string");
}

/** Network chunks may split both event boundaries and UTF-8 characters. */
async function readStream(response: Response, accept: (event: CopilotEvent) => void, signal: AbortSignal) {
  if (!response.body) throw new Error("The copilot response did not contain an event stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  function frame(text: string) {
    const lines = text.split(/\r?\n/);
    const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
    if (!data) return;
    let payload: unknown;
    try { payload = JSON.parse(data); }
    catch { throw new Error("The copilot returned malformed event data."); }
    const event = readEvent(payload);
    const name = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    if (name && name !== event.event) throw new Error("The copilot returned an inconsistent event.");
    if (!signal.aborted) accept(event);
  }
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (buffer.length > 2_000_000) throw new Error("The copilot event exceeded the supported size.");
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        frame(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary[0].length);
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
      if (done) {
        if (buffer.trim()) frame(buffer);
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

/** Context changes unmount the conversation and remove candidate information. */
export default function CopilotPanel(props: Props) {
  return <section aria-label="Recruiter copilot" className="mt-6 rounded-xl border border-slate-200 bg-white p-5 sm:p-7">
    <div className="mb-4"><p className="text-xs font-semibold uppercase tracking-widest text-teal-800">Evidence first</p><h2 className="mt-1 text-xl font-semibold">Recruiter copilot</h2><p className="mt-2 text-sm text-slate-600">Ask about evidence, compare candidates, or prepare screening questions. Status changes require your confirmation.</p></div>
    {props.blind ? <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">Copilot is paused in blind mode because answers and source text may reveal identity.</p>
      : <Conversation key={`${props.jobId}:${props.candidateId ?? "pool"}`} {...props} />}
  </section>;
}

function Conversation({ jobId, candidateId, onCitation, onStatusChanged }: Props) {
  const [scope, setScope] = useState<"candidate" | "pool">(candidateId ? "candidate" : "pool");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const active = useRef<AbortController | null>(null);
  const requestId = useRef(0);
  const awaitingStatusRefresh = useRef(false);

  useEffect(() => () => { active.current?.abort(); requestId.current += 1; }, []);

  function resetScope(value: "candidate" | "pool") {
    active.current?.abort();
    requestId.current += 1;
    setScope(value);
    setMessage("");
    setBusy(false);
    setProgress([]);
    setResult(null);
    setRunId(null);
    setError("");
    setStatus("");
    awaitingStatusRefresh.current = false;
  }

  async function stream(path: string, body: Request | Confirmation, approval = false) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    awaitingStatusRefresh.current = approval;
    let terminal = false;
    let notified = false;
    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "POST", headers, body: JSON.stringify(body), signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Copilot request failed (${response.status}). Check the run status before retrying.`);
      if (!response.headers.get("content-type")?.includes("text/event-stream")) throw new Error("The copilot did not return an event stream.");
      await readStream(response, (event) => {
        if (id !== requestId.current || controller.signal.aborted) return;
        setRunId(event.run_id);
        setStatus(event.status);
        if (event.event === "progress") setProgress((steps) => [...steps, event.status]);
        if (event.event === "error") {
          terminal = true;
          setError(event.error || "The copilot could not complete this run.");
        }
        if (event.event === "result") {
          terminal = true;
          setResult(event.result ?? null);
          if (approval && event.status === "completed" && !event.result?.needs_confirmation && !notified) {
            notified = true;
            awaitingStatusRefresh.current = false;
            onStatusChanged();
          }
        }
      }, controller.signal);
      if (!terminal && !controller.signal.aborted && id === requestId.current) throw new Error("The event stream ended before a result. Check the run status before retrying.");
    } catch (err) {
      if (!controller.signal.aborted && id === requestId.current) setError(err instanceof Error ? err.message : "Could not connect to the copilot.");
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  async function ask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !message.trim()) return;
    const body: Request = { job_id: jobId, scope: scope === "candidate" && candidateId ? `candidate:${candidateId}` : "pool", message: message.trim() };
    setResult(null);
    setRunId(null);
    setProgress([]);
    setStatus("Starting");
    await stream("/copilot", body);
  }

  function confirm(approve: boolean) {
    if (busy || !result?.needs_confirmation || !runId) return;
    const body: Confirmation = { approve };
    void stream(`/copilot/${encodeURIComponent(runId)}/confirm`, body, approve);
  }

  async function checkRun() {
    if (!runId || busy) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/copilot/${encodeURIComponent(runId)}`, { headers: { "X-Role": "hr" }, signal: controller.signal });
      if (!response.ok) throw new Error(`Could not check the run (${response.status}).`);
      const run: unknown = await response.json();
      if (id !== requestId.current || controller.signal.aborted) return;
      const expectedScope = scope === "candidate" && candidateId ? `candidate:${candidateId}` : "pool";
      if (!isRun(run) || run.id !== runId || run.job_id !== jobId || run.scope !== expectedScope) throw new Error("The copilot returned an invalid run status.");
      setStatus(run.status);
      setResult(run.result);
      if (run.error) setError(run.error);
      if (run.status === "completed" && awaitingStatusRefresh.current && !run.result?.needs_confirmation) {
        awaitingStatusRefresh.current = false;
        onStatusChanged();
      }
    } catch (err) {
      if (id === requestId.current && !controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not check the run.");
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  const validCitations = result?.citations?.filter((citation) => scope !== "candidate" || result.route === "similar" || citation.application_id === candidateId) ?? [];
  const groundedClaims = result?.claims?.filter((claim) => (claim.chunk_ids?.length ?? 0) > 0 && (claim.chunk_ids ?? []).every((id) => validCitations.some((citation) => citation.chunk_id === id))) ?? [];
  const warnings = result?.warnings ?? [];
  const steps = result?.steps ?? [];
  const droppedClaims = (result?.claims?.length ?? 0) - groundedClaims.length;

  return <div>
    <form onSubmit={ask}>
      <label className="mb-3 flex flex-wrap items-center gap-3 text-sm font-medium">Ask about<select className={control} value={scope} onChange={(event) => resetScope(event.target.value as "candidate" | "pool")} aria-label="Copilot scope"><option value="pool">Entire candidate pool</option><option value="candidate" disabled={!candidateId}>Selected candidate</option></select></label>
      <label className="grid gap-2 text-sm font-medium">Your question<textarea className={control} rows={3} value={message} maxLength={4000} onChange={(event) => setMessage(event.target.value)} placeholder={scope === "candidate" ? "Does this candidate have evidence of building RAG systems?" : "Compare candidates on evaluation experience."} disabled={busy} /></label>
      <div className="mt-3 flex flex-wrap items-center gap-3"><button className={primary} type="submit" disabled={busy || !message.trim()}>{busy ? "Working…" : "Ask copilot"}</button>{busy && <button className={control} type="button" onClick={() => { active.current?.abort(); requestId.current += 1; setBusy(false); setStatus("Stopped listening. The server run may still be processing."); }}>Stop listening</button>}<p role="status" className="text-xs text-slate-500">{status.replaceAll("_", " ")}</p></div>
      {runId && <div className="mt-3 flex flex-wrap items-center gap-3"><p className="text-xs text-slate-500">Run {runId}</p><button type="button" className={control} disabled={busy} onClick={checkRun}>Check run status</button></div>}
    </form>
    {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {progress.length > 0 && <details className="mt-4 text-sm text-slate-500" open={busy}><summary className="cursor-pointer font-medium">Run progress</summary><ol className="mt-2 list-inside list-decimal space-y-1">{progress.map((step, index) => <li key={`${step}-${index}`}>{step.replaceAll("_", " ")}</li>)}</ol></details>}
    {result && <div className="mt-5 border-t border-slate-200 pt-5">
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-slate-500"><span className="rounded-full bg-teal-50 px-3 py-1 font-medium text-teal-900">Agent: {result.route.replaceAll("_", " ")}</span><span>{Math.round(result.confidence * 100)}% confidence</span><span>{result.retries} grounding retries</span></div>
      {["explain", "update_status"].includes(result.route) && result.explanation && <p className="mb-4 text-sm leading-relaxed text-slate-700">{result.explanation}</p>}
      {!["explain", "update_status"].includes(result.route) && !groundedClaims.length && !result.needs_confirmation && <p className="mb-4 text-sm text-slate-600">No grounded candidate claims could be verified from the available evidence.</p>}
      {groundedClaims.length > 0 && <ul className="space-y-4">{groundedClaims.map((claim, index) => <li key={index} className="rounded-lg border border-slate-200 p-4"><p className="text-sm leading-relaxed">{claim.text}</p><div className="mt-3 flex flex-wrap gap-2">{(claim.chunk_ids ?? []).map((id, sourceIndex) => { const citation = validCitations.find((item) => item.chunk_id === id)!; return <button key={id} type="button" className="rounded border border-teal-200 bg-teal-50 px-2 py-1 text-xs font-medium text-teal-900" onClick={() => onCitation(citation)} aria-label={`View source ${sourceIndex + 1} for claim ${index + 1}`}>↗ {citation.section} evidence {sourceIndex + 1}</button>; })}</div></li>)}</ul>}
      {droppedClaims > 0 && <p className="mt-3 text-sm text-amber-800">Some claims were hidden because their resume evidence could not be resolved.</p>}
      {warnings.length > 0 && <ul aria-label="Copilot warnings" className="mt-4 space-y-2 rounded-lg bg-amber-50 p-4 text-sm text-amber-900">{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
      {steps.length > 0 && <details className="mt-4 text-sm text-slate-500"><summary className="cursor-pointer font-medium">Agent route and verification steps</summary><ol className="mt-2 list-inside list-decimal space-y-1">{steps.map((step, index) => <li key={`${step}-${index}`}>{step.replaceAll("_", " ")}</li>)}</ol></details>}
      {result.needs_confirmation && result.proposal && <div className="mt-5 rounded-lg border border-amber-300 bg-amber-50 p-4"><h3 className="text-sm font-semibold">Confirm the proposed status change</h3><p className="mt-2 text-sm">Set candidate {result.proposal.application_id} to <strong>{result.proposal.status}</strong>.</p><p className="mt-2 text-sm text-slate-600">{result.proposal.reason}</p><div className="mt-4 flex gap-3"><button type="button" className={primary} disabled={busy} onClick={() => confirm(true)}>Confirm status change</button><button type="button" className={control} disabled={busy} onClick={() => confirm(false)}>Cancel proposed change</button></div></div>}
    </div>}
  </div>;
}
