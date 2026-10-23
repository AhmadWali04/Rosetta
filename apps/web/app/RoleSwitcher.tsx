"use client";

import { usePathname, useRouter } from "next/navigation";

export default function RoleSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const role = pathname.startsWith("/hr") ? "hr" : "applicant";

  return (
    <nav aria-label="Portal navigation" className="border-b border-zinc-200 bg-white px-6 py-3">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
        <span className="text-sm font-semibold tracking-tight text-zinc-900">SkillBridge</span>
        <label className="flex items-center gap-3 text-sm text-zinc-600">
          Demo role
          <select
            aria-label="Demo role"
            value={role}
            onChange={(event) => router.push(event.target.value === "hr" ? "/hr" : "/")}
            className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-zinc-900"
          >
            <option value="applicant">Applicant</option>
            <option value="hr">HR</option>
            <option value="tech" disabled>Tech Lead (coming in M4)</option>
          </select>
        </label>
      </div>
    </nav>
  );
}
