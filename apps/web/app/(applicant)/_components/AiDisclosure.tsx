/**
 * F1.3 — exact required copy, shown on both the posting (page.tsx) and the
 * apply form (apply/page.tsx). Server-renderable, no interactivity needed.
 */
export function AiDisclosure() {
  return (
    <p className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      Applications are screened with AI assistance; all decisions are made by
      people.
    </p>
  );
}
