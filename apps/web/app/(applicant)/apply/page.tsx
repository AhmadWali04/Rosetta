import Link from "next/link";

import { AiDisclosure } from "../_components/AiDisclosure";
import ApplyForm from "./ApplyForm";

// F1.2/F1.3 — the form page. Server Component shell; the interactive form
// (file input, client-side validation, submit) lives in ApplyForm.tsx
// ("use client"), kept separate so it's testable in isolation.
export default function ApplyPage() {
  return (
    <main className="mx-auto min-h-screen max-w-2xl bg-white px-6 py-12">
      <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-700">
        ← Back to posting
      </Link>

      <h1 className="mt-4 text-2xl font-bold tracking-tight text-zinc-900">
        Apply — AI Intern, Applied &amp; Agentic AI
      </h1>

      <div className="mt-6">
        <AiDisclosure />
      </div>

      <div className="mt-8">
        <ApplyForm />
      </div>
    </main>
  );
}
