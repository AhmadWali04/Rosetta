"use client";

import { useRouter } from "next/navigation";
import { useState, type ChangeEvent, type FormEvent } from "react";

// Fixed seed job id (apps/api/scripts/seed.py).
export const JOB_ID = "job-ai-intern-procogia";

// Mirrors the backend's authoritative validation (PRD F1.2: PDF/DOCX, ≤5MB)
// for UX only — the backend remains the source of truth and re-validates.
const MAX_RESUME_BYTES = 5 * 1024 * 1024;
const ALLOWED_RESUME_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const ALLOWED_RESUME_EXTENSIONS = [".pdf", ".docx"];

export function validateResumeFile(file: File): string | null {
  const name = file.name.toLowerCase();
  const extensionOk = ALLOWED_RESUME_EXTENSIONS.some((ext) => name.endsWith(ext));
  // Some browsers/OSes report an empty `type` for valid files, so a known
  // extension alone is accepted too; an unknown extension with no usable
  // type is rejected.
  const typeOk = file.type !== "" && ALLOWED_RESUME_MIME_TYPES.includes(file.type);
  if (!extensionOk && !typeOk) {
    return "Resume must be a PDF or DOCX file.";
  }
  if (file.size > MAX_RESUME_BYTES) {
    return "Resume must be 5MB or smaller.";
  }
  return null;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function ApplyForm() {
  const router = useRouter();
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [resumeSelected, setResumeSelected] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function handleResumeChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (!file) {
      setResumeSelected(false);
      setResumeError(null);
      return;
    }
    setResumeError(validateResumeFile(file));
    setResumeSelected(true);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);

    if (!resumeSelected || resumeError) {
      setResumeError((current) => current ?? "Please attach a PDF or DOCX resume.");
      return;
    }

    // Built from the native <form>: every named input (including the file
    // input named "resume") is already captured here.
    const formData = new FormData(event.currentTarget);
    formData.set("job_id", JOB_ID);

    setSubmitting(true);
    try {
      // Deliberately plain `fetch`, not the typed lib/api.ts client:
      // openapi-fetch's typed body doesn't comfortably express multipart
      // FormData, and this is a one-off call.
      const response = await fetch(`${API_BASE_URL}/applications`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setSubmitError(
          body?.detail ??
            "Something went wrong submitting your application. Please try again."
        );
        setSubmitting(false);
        return;
      }

      const data = await response.json();
      router.push(`/applications/${data.id}`);
    } catch {
      setSubmitError(
        "Could not reach the server. Please check your connection and try again."
      );
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6" noValidate>
      <div>
        <label htmlFor="name" className="block text-sm font-medium text-zinc-900">
          Full name
        </label>
        <input
          id="name"
          name="name"
          type="text"
          required
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
        />
      </div>

      <div>
        <label htmlFor="email" className="block text-sm font-medium text-zinc-900">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
        />
      </div>

      <div>
        <label
          htmlFor="github_url"
          className="block text-sm font-medium text-zinc-900"
        >
          GitHub URL (optional)
        </label>
        <input
          id="github_url"
          name="github_url"
          type="url"
          placeholder="https://github.com/your-handle"
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
        />
      </div>

      <div>
        <label
          htmlFor="linkedin_url"
          className="block text-sm font-medium text-zinc-900"
        >
          LinkedIn URL (optional)
        </label>
        <input
          id="linkedin_url"
          name="linkedin_url"
          type="url"
          placeholder="https://linkedin.com/in/your-handle"
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
        />
      </div>

      <div>
        <label
          htmlFor="portfolio_url"
          className="block text-sm font-medium text-zinc-900"
        >
          Portfolio URL (optional)
        </label>
        <input
          id="portfolio_url"
          name="portfolio_url"
          type="url"
          placeholder="https://your-site.dev"
          className="mt-1 w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
        />
      </div>

      <div>
        <label htmlFor="resume" className="block text-sm font-medium text-zinc-900">
          Resume (PDF or DOCX, max 5MB)
        </label>
        <input
          id="resume"
          name="resume"
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={handleResumeChange}
          required
          className="mt-1 w-full text-sm text-zinc-900"
        />
        {resumeError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {resumeError}
          </p>
        )}
      </div>

      {submitError && (
        <p role="alert" className="text-sm text-red-600">
          {submitError}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="inline-flex items-center rounded-md bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-zinc-700 disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit application"}
      </button>
    </form>
  );
}
