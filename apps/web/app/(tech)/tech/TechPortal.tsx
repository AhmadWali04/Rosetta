"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../../../lib/api";
import type { components } from "../../../lib/api-types";

type Candidate = components["schemas"]["PipelineCandidate"];
type Detail = components["schemas"]["CandidateDetail"];
const HEADERS = { "X-Role": "tech" };
export const JOB_ID = "job-ai-intern-procogia";
const control =
  "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-600 disabled:cursor-not-allowed disabled:opacity-50";
const primary = `${control} border-indigo-800 bg-indigo-800 text-white hover:bg-indigo-900`;
const danger = `${control} border-red-700 bg-red-700 text-white hover:bg-red-800`;

function percent(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function message(error: unknown, fallback: string) {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string")
    return error.detail;
  return fallback;
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
      {children}
    </span>
  );
}

export default function TechPortal() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let current = true;
    api
      .GET("/tech/applications", { headers: HEADERS, params: { query: { job_id: JOB_ID } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (!data) throw new Error(message(error, "Could not load the tech-review queue."));
        setCandidates(data);
      })
      .catch((err: unknown) => {
        if (current) setError(err instanceof Error ? err.message : "Could not load the queue.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [revision]);

  useEffect(() => {
    if (!selected) return;
    let current = true;
    api
      .GET("/tech/applications/{application_id}", {
        headers: HEADERS,
        params: { path: { application_id: selected } },
      })
      .then(({ data, error }) => {
        if (!current) return;
        if (!data) throw new Error(message(error, "Could not load this candidate."));
        setDetail(data);
      })
      .catch((err: unknown) => {
        if (current) setDetailError(err instanceof Error ? err.message : "Could not load this candidate.");
      })
      .finally(() => {
        if (current) setDetailLoading(false);
      });
    return () => {
      current = false;
    };
  }, [selected, revision]);

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    setDetailLoading(true);
    setDetailError("");
    setRevision((value) => value + 1);
  }, []);

  function selectCandidate(id: string) {
    if (id === selected || saving) return;
    setDetail(null);
    setDetailLoading(true);
    setDetailError("");
    setScores({});
    setComment("");
    setSelected(id);
  }

  async function decide(decisionValue: "invited" | "rejected") {
    if (!detail || saving) return;
    setSaving(true);
    setDetailError("");
    setNotice("");
    try {
      const overall =
        Object.values(scores).length > 0
          ? Object.values(scores).reduce((a, b) => a + b, 0) / Object.values(scores).length
          : undefined;
      const { error, response } = await api.POST("/tech/applications/{application_id}/decision", {
        headers: HEADERS,
        params: { path: { application_id: detail.id } },
        body: {
          decision: decisionValue,
          rubric: Object.entries(scores).map(([requirement_id, score]) => ({
            requirement_id,
            score,
          })),
          overall,
          comment: comment || undefined,
        },
      });
      if (!response.ok)
        throw new Error(message(error, "Could not save the decision. Refresh and try again."));
      setNotice(
        decisionValue === "invited"
          ? "Candidate invited to interview. Decision recorded in the audit log."
          : "Candidate declined. Decision recorded in the audit log."
      );
      setSelected(null);
      setDetail(null);
      refresh();
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Could not save the decision.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-screen-2xl px-5 py-8 sm:px-8">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-indigo-800">
              SkillBridge / Tech Lead workspace
            </p>
            <h1 className="text-3xl font-semibold tracking-tight">Tech review queue</h1>
            <p className="mt-2 text-sm text-slate-600">
              AI Intern, Applied &amp; Agentic AI · ProCogia — candidates HR has marked Valid
            </p>
          </div>
          <button type="button" className={control} onClick={refresh} disabled={loading || saving}>
            Refresh queue
          </button>
        </header>
        {notice && (
          <p role="status" className="mb-4 rounded-lg bg-emerald-100 p-3 text-sm text-emerald-900">
            {notice}
          </p>
        )}
        <section
          aria-label="Tech review queue"
          className="overflow-hidden rounded-xl border border-slate-200 bg-white"
        >
          {error ? (
            <p role="alert" className="p-6 text-red-800">
              {error} Use Refresh queue to retry.
            </p>
          ) : loading ? (
            <p role="status" className="p-6 text-slate-500">
              Loading queue…
            </p>
          ) : candidates.length === 0 ? (
            <div className="p-12 text-center">
              <h2 className="font-semibold">No candidates ready for tech review</h2>
              <p className="mt-2 text-sm text-slate-500">
                Candidates appear here once HR labels them Valid.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    {["Candidate", "Match score", "AI recommendation", "Must-haves"].map((heading) => (
                      <th key={heading} scope="col" className="px-5 py-3 font-medium">
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {candidates.map((candidate) => (
                    <tr
                      key={candidate.id}
                      className={candidate.id === selected ? "bg-indigo-50" : "hover:bg-slate-50"}
                    >
                      <td className="px-5 py-4">
                        <button
                          type="button"
                          className="text-left font-semibold text-indigo-900 underline-offset-4 hover:underline"
                          disabled={saving}
                          onClick={() => selectCandidate(candidate.id)}
                        >
                          {candidate.name}
                        </button>
                      </td>
                      <td className="px-5 py-4 font-semibold tabular-nums">
                        {percent(candidate.score)}
                      </td>
                      <td className="px-5 py-4 capitalize">
                        {candidate.recommendation ?? "—"}
                      </td>
                      <td className="px-5 py-4 tabular-nums">
                        {candidate.must_have_met}/{candidate.must_have_total}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {selected && (
          <section
            aria-label="Candidate profile"
            className="mt-6 rounded-xl border border-slate-200 bg-white p-5 sm:p-7"
          >
            <div className="mb-5 flex items-center justify-between gap-4">
              <h2 className="text-xl font-semibold">{detail?.name ?? "Candidate profile"}</h2>
              <button
                type="button"
                className={control}
                disabled={saving}
                onClick={() => {
                  setSelected(null);
                  setDetail(null);
                }}
              >
                Close candidate
              </button>
            </div>
            {detailError && <p role="alert" className="mb-4 text-sm text-red-800">{detailError}</p>}
            {detailLoading ? (
              <p role="status">Loading candidate evidence…</p>
            ) : (
              detail && (
                <>
                  <div className="mb-6 flex flex-wrap items-center gap-3">
                    <Badge>{detail.status}</Badge>
                    <p className="text-sm text-slate-500">
                      Match {percent(detail.score)} · AI {detail.recommendation ?? "—"} ·{" "}
                      {percent(detail.confidence)} confidence
                    </p>
                  </div>
                  <div className="grid gap-8 xl:grid-cols-2">
                    <div>
                      <h3 className="mb-4 font-semibold">Requirement checklist &amp; rubric</h3>
                      <ul className="space-y-3">
                        {detail.requirements.map((requirement) => (
                          <li key={requirement.id} className="rounded-lg border border-slate-200 p-4">
                            <div className="flex items-start justify-between gap-3">
                              <h4 className="text-sm font-medium">{requirement.text}</h4>
                              <Badge>{requirement.status.replaceAll("_", " ")}</Badge>
                            </div>
                            <p className="mt-1 text-xs text-slate-500">
                              {requirement.kind.replaceAll("_", " ")}
                            </p>
                            <p className="mt-3 text-sm leading-relaxed text-slate-600">
                              {requirement.explanation || "No verified explanation available."}
                            </p>
                            <label className="mt-3 flex items-center gap-2 text-sm font-medium">
                              Rubric score (1-5)
                              <select
                                aria-label={`Rubric score for ${requirement.text}`}
                                className={control}
                                value={scores[requirement.id] ?? ""}
                                disabled={saving}
                                onChange={(event) =>
                                  setScores((prev) => ({
                                    ...prev,
                                    [requirement.id]: Number(event.target.value),
                                  }))
                                }
                              >
                                <option value="" disabled>
                                  —
                                </option>
                                {[1, 2, 3, 4, 5].map((n) => (
                                  <option key={n} value={n}>
                                    {n}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h3 className="mb-4 font-semibold">Resume evidence</h3>
                      <div className="max-h-[32rem] space-y-3 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-4">
                        {detail.chunks.length ? (
                          detail.chunks.map((chunk) => (
                            <article key={chunk.id} className="rounded-lg border border-slate-200 bg-white p-4">
                              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                                {chunk.section}
                              </p>
                              <p className="whitespace-pre-wrap text-sm leading-relaxed">{chunk.text}</p>
                            </article>
                          ))
                        ) : (
                          <p className="text-sm text-slate-500">No resume evidence available.</p>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="mt-7 border-t border-slate-200 pt-6">
                    <h3 className="font-semibold">Record your decision</h3>
                    <p className="mt-1 text-sm text-slate-500">
                      Your rubric and comment are saved; this is the only action that moves a candidate
                      out of tech review.
                    </p>
                    <label className="mt-4 grid max-w-xl gap-2 text-sm">
                      Comment {detail.status === "valid" ? "(required to decline)" : ""}
                      <textarea
                        className={control}
                        value={comment}
                        onChange={(event) => setComment(event.target.value)}
                        maxLength={2000}
                        disabled={saving}
                        rows={2}
                      />
                    </label>
                    <div className="mt-3 flex flex-wrap gap-3">
                      <button
                        type="button"
                        className={primary}
                        disabled={saving || detail.status !== "valid"}
                        onClick={() => decide("invited")}
                      >
                        Invite to interview
                      </button>
                      <button
                        type="button"
                        className={danger}
                        disabled={saving || detail.status !== "valid" || !comment}
                        onClick={() => decide("rejected")}
                      >
                        Decline
                      </button>
                    </div>
                    {detail.status !== "valid" && (
                      <p className="mt-3 text-xs text-slate-500">
                        This candidate already has a tech-review decision recorded ({detail.status}).
                      </p>
                    )}
                  </div>
                  <div className="mt-7 border-t border-slate-200 pt-6">
                    <h3 className="mb-4 font-semibold">Audit history</h3>
                    {detail.events.length ? (
                      <ol className="space-y-3">
                        {detail.events.map((event) => (
                          <li key={event.id} className="border-l-2 border-indigo-200 pl-4 text-sm">
                            <p className="font-medium">{event.action.replaceAll("_", " ")}</p>
                            <p className="mt-1 text-xs text-slate-500">
                              {event.actor} · {new Date(event.created_at).toLocaleString()}
                            </p>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="text-sm text-slate-500">No audit events available.</p>
                    )}
                  </div>
                </>
              )
            )}
          </section>
        )}
      </div>
    </main>
  );
}
