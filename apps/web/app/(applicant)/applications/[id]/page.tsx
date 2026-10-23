import Link from "next/link";
import { notFound } from "next/navigation";

import { api } from "@/lib/api";

// Live, per-request fetch keyed by the dynamic `id` param — opt out of
// Next.js 16 Cache Components prerendering (see app/(applicant)/page.tsx
// for the same pattern/reasoning).
export const instant = false;

// Confirmation screen the applicant lands on after a successful submit
// (ApplyForm.tsx redirects here with the id the API returned).
export default async function ApplicationConfirmationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const { data: application, error } = await api.GET(
    "/applications/{application_id}",
    {
      params: { path: { application_id: id } },
      cache: "no-store",
    }
  );

  if (error || !application) {
    notFound();
  }

  return (
    <main className="mx-auto min-h-screen max-w-xl bg-white px-6 py-16 text-center">
      <h1 className="text-2xl font-bold tracking-tight text-zinc-900">
        Thanks — your application has been received
      </h1>
      <p className="mt-3 text-zinc-600">
        We&apos;ll follow up by email at{" "}
        <span className="font-medium text-zinc-900">{application.email}</span>.
      </p>

      <dl className="mt-8 rounded-lg border border-zinc-200 p-6 text-left">
        <dt className="text-sm font-medium text-zinc-500">Application ID</dt>
        <dd className="mt-1 font-mono text-sm text-zinc-900">
          {application.id}
        </dd>
        <dt className="mt-4 text-sm font-medium text-zinc-500">Status</dt>
        <dd className="mt-1 text-sm capitalize text-zinc-900">
          {application.status}
        </dd>
      </dl>

      <Link
        href="/"
        className="mt-8 inline-block text-sm text-zinc-500 hover:text-zinc-700"
      >
        ← Back to posting
      </Link>
    </main>
  );
}
