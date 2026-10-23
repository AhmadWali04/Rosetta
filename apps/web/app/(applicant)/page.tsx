import Link from "next/link";
import { notFound } from "next/navigation";

import { api } from "@/lib/api";

import { AiDisclosure } from "./_components/AiDisclosure";

// Fixed seed job id (apps/api/scripts/seed.py). SkillBridge v1 only serves
// this one posting (PRD §3 non-goals).
const JOB_ID = "job-ai-intern-procogia";

// `jobs` has no location/employment_type/dates columns in
// apps/api/app/db/models.py, so GET /jobs/{id} can't return them yet.
// Hardcoded here to match the real seeded posting (data/seed/job.json)
// until those columns + serialization land — see PROGRESS.md.
const JOB_LOCATION = "Vancouver, British Columbia, Canada (on-site, 5 days/week)";
const JOB_DATES = "December 2026 – April 2027";
const JOB_EMPLOYMENT_TYPE = "Internship (Student Work Placement Program)";

// `JobOut.requirements` is typed as `Record<string, unknown>[]` in the
// generated api-types.ts because the API schema (apps/api/app/routes/
// schemas.py) declares it as a loose `list[dict]` passing through the
// `jobs.requirements` JSON column as-is, not a nested Pydantic model. The
// actual shape (written by apps/api/scripts/seed.py from data/seed/job.json)
// is always {text, kind, weight} — narrowed here once rather than casting
// at every call site.
type Requirement = { text: string; kind: "must_have" | "nice_to_have"; weight: number };

// This page does a live, uncached fetch (see below) — Next.js 16's Cache
// Components build otherwise wants it prerendered or wrapped in Suspense.
// Opt this route out of prerendering instead: it's a live job posting, not
// static content, so a blocking server render on every request is correct.
export const instant = false;

// F1.1 — Server Component, fetched live at request time (not build time):
// this is the one seeded job and it's cheap to fetch, so "always current"
// beats any staleness risk from caching a build-time snapshot.
export default async function JobPostingPage() {
  const { data: job, error } = await api.GET("/jobs/{job_id}", {
    params: { path: { job_id: JOB_ID } },
    cache: "no-store",
  });

  if (error || !job) {
    notFound();
  }

  const requirements = job.requirements as unknown as Requirement[];
  const mustHaves = requirements.filter((r) => r.kind === "must_have");
  const niceToHaves = requirements.filter((r) => r.kind === "nice_to_have");

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <header className="mb-8 border-b border-zinc-200 pb-8">
        <h1 className="text-3xl font-bold tracking-tight text-zinc-900">
          {job.title}
        </h1>
        <dl className="mt-4 grid grid-cols-1 gap-3 text-sm text-zinc-600 sm:grid-cols-3">
          <div>
            <dt className="font-medium text-zinc-500">Location</dt>
            <dd className="mt-0.5">{JOB_LOCATION}</dd>
          </div>
          <div>
            <dt className="font-medium text-zinc-500">Dates</dt>
            <dd className="mt-0.5">{JOB_DATES}</dd>
          </div>
          <div>
            <dt className="font-medium text-zinc-500">Type</dt>
            <dd className="mt-0.5">{JOB_EMPLOYMENT_TYPE}</dd>
          </div>
        </dl>
        <div className="mt-6">
          <Link
            href="/apply"
            className="inline-flex items-center rounded-md bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-zinc-700"
          >
            Apply now
          </Link>
        </div>
      </header>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-zinc-900">About the role</h2>
        <p className="mt-3 whitespace-pre-line leading-relaxed text-zinc-700">
          {job.raw_jd}
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-zinc-900">
          Must-have requirements
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-zinc-700">
          {mustHaves.map((r) => (
            <li key={r.text}>{r.text}</li>
          ))}
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-zinc-900">
          Nice to have
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-zinc-700">
          {niceToHaves.map((r) => (
            <li key={r.text}>{r.text}</li>
          ))}
        </ul>
      </section>

      <AiDisclosure />

      <div className="mt-8">
        <Link
          href="/apply"
          className="inline-flex items-center rounded-md bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-zinc-700"
        >
          Apply now
        </Link>
      </div>
    </main>
  );
}
