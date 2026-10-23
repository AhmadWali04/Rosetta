import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../../lib/api-types";
import HrPortal, { JOB_ID } from "./HrPortal";

const mocks = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
vi.mock("../../../lib/api", () => ({ api: mocks }));

type Candidate = components["schemas"]["PipelineCandidate"];
type Detail = components["schemas"]["CandidateDetail"];
const candidate: Candidate = {
  id: "candidate-1", job_id: JOB_ID, name: "Jordan Applicant", status: "analyzed",
  vector_status: "indexed", created_at: "2026-10-23T12:00:00", score: 0.82,
  recommendation: "advance", confidence: 0.9, must_have_met: 1, must_have_total: 1, flags: [],
};
const detail: Detail = {
  ...candidate,
  skills: [{ term: "FastAPI", canonical: "Python backend", requirement_ids: ["req-1"], chunk_ids: ["chunk-1"] }],
  requirements: [{ id: "req-1", text: "Build APIs", kind: "must_have", status: "met", explanation: "Built a production API.", chunk_ids: ["chunk-1"] }],
  chunks: [{ id: "chunk-1", section: "experience", text: "Jordan built an API at School University.", char_start: 0, char_end: 48 }],
  events: [{ id: "event-1", actor: "system", action: "intake_complete", payload: { name: "Jordan Applicant" }, created_at: "2026-10-23T12:00:00" }],
};

beforeEach(() => {
  vi.resetAllMocks();
  mocks.GET.mockImplementation(async (path: string) => ({ data: path.includes("{application_id}") ? detail : [candidate] }));
  mocks.PATCH.mockResolvedValue({ data: candidate, response: { ok: true } });
  mocks.POST.mockImplementation(async (path: string) => path.endsWith("/preview") ? {
    data: { job_id: JOB_ID, percent: 25, pending_count: 4, application_ids: [candidate.id], candidates: [candidate] },
  } : { response: { ok: true } });
});

describe("HR pipeline", () => {
  it("requests server filtering and score sorting with the HR role", async () => {
    const user = userEvent.setup();
    render(<HrPortal />);
    await screen.findByRole("button", { name: candidate.name });
    await user.selectOptions(screen.getByLabelText("Filter by status"), "pending");
    await user.selectOptions(screen.getByLabelText("Sort candidates"), "score_asc");
    await waitFor(() => expect(mocks.GET).toHaveBeenLastCalledWith("/hr/applications", expect.objectContaining({
      headers: { "X-Role": "hr" }, params: { query: { job_id: JOB_ID, status: "pending", sort: "score_asc" } },
    })));
  });

  it("opens grounded evidence and highlights the source chunk", async () => {
    const user = userEvent.setup();
    render(<HrPortal />);
    await user.click(await screen.findByRole("button", { name: candidate.name }));
    await user.click(await screen.findByRole("button", { name: "View evidence 1 for Build APIs" }));
    const chunk = screen.getByTestId("chunk-chunk-1");
    expect(chunk.querySelector("mark")).toHaveTextContent("Jordan built an API");
    expect(chunk).toHaveFocus();
    expect(screen.getByText("Built a production API.")).toBeInTheDocument();
  });

  it("hides identity-bearing details when blind mode is enabled", async () => {
    const user = userEvent.setup();
    render(<HrPortal />);
    await user.click(await screen.findByRole("button", { name: candidate.name }));
    await screen.findByText("Jordan built an API at School University.");
    await user.click(screen.getByRole("checkbox", { name: "Blind mode" }));
    expect(screen.queryByText(candidate.name)).not.toBeInTheDocument();
    expect(screen.queryByText("Jordan built an API at School University.")).not.toBeInTheDocument();
    expect(screen.queryByText("Built a production API.")).not.toBeInTheDocument();
    expect(screen.queryByText("FastAPI")).not.toBeInTheDocument();
    expect(screen.queryByText(/"name":/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View evidence 1 for Build APIs" })).toBeDisabled();
  });

  it("records an explicit manual decision with its reason", async () => {
    const user = userEvent.setup();
    render(<HrPortal />);
    await user.click(await screen.findByRole("button", { name: candidate.name }));
    await user.type(await screen.findByLabelText("Reason (optional)"), "Needs a screening call");
    await user.click(screen.getByRole("button", { name: "Label Pending" }));
    await waitFor(() => expect(mocks.PATCH).toHaveBeenCalledWith("/applications/{application_id}/status", {
      headers: { "X-Role": "hr" }, params: { path: { application_id: candidate.id } },
      body: { status: "pending", reason: "Needs a screening call" },
    }));
    expect(await screen.findByText(/Candidate labelled pending/)).toBeInTheDocument();
  });

  it("keeps a pending label request attached to the selected candidate", async () => {
    const user = userEvent.setup();
    const second: Candidate = { ...candidate, id: "candidate-2", name: "Alex Applicant" };
    mocks.GET.mockImplementation(async (path: string) => ({ data: path.includes("{application_id}") ? detail : [candidate, second] }));
    let rejectLabel!: (reason: Error) => void;
    mocks.PATCH.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectLabel = reject; }));
    render(<HrPortal />);
    await user.click(await screen.findByRole("button", { name: candidate.name }));
    await user.click(await screen.findByRole("button", { name: "Label Pending" }));
    const secondButton = screen.getByRole("button", { name: second.name });
    const closeButton = screen.getByRole("button", { name: "Close candidate" });
    expect(secondButton).toBeDisabled();
    expect(closeButton).toBeDisabled();
    await user.click(secondButton);
    await user.click(closeButton);
    rejectLabel(new Error("Label request failed"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Label request failed");
    expect(within(screen.getByRole("region", { name: "Candidate details" })).getByRole("heading", { name: candidate.name })).toBeInTheDocument();
    expect(secondButton).toBeEnabled();
    expect(closeButton).toBeEnabled();
    expect(mocks.GET).not.toHaveBeenCalledWith("/hr/applications/{application_id}", expect.objectContaining({ params: { path: { application_id: second.id } } }));
  });

  it("previews without mutation, invalidates changed percentages, and confirms exact IDs", async () => {
    const user = userEvent.setup();
    render(<HrPortal />);
    await screen.findByRole("button", { name: candidate.name });
    await user.click(screen.getByRole("button", { name: "Preview promotion" }));
    await screen.findByRole("button", { name: "Confirm promotion to Valid" });
    expect(mocks.POST).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("slider", { name: "Promotion percentage" }), { target: { value: "50" } });
    expect(screen.queryByRole("button", { name: "Confirm promotion to Valid" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview promotion" }));
    await user.click(await screen.findByRole("button", { name: "Confirm promotion to Valid" }));
    expect(mocks.POST).toHaveBeenLastCalledWith("/pools/{job_id}/promote", {
      headers: { "X-Role": "hr" }, params: { path: { job_id: JOB_ID } }, body: { percent: 25, application_ids: [candidate.id] },
    });
  });

  it("clears a stale promotion preview and displays the server error", async () => {
    const user = userEvent.setup();
    mocks.POST.mockImplementation(async (path: string) => path.endsWith("/preview") ? {
      data: { job_id: JOB_ID, percent: 25, pending_count: 4, application_ids: [candidate.id], candidates: [candidate] },
    } : { response: { ok: false, status: 409 }, error: { detail: "Pool changed. Preview again." } });
    render(<HrPortal />);
    await screen.findByRole("button", { name: candidate.name });
    await user.click(screen.getByRole("button", { name: "Preview promotion" }));
    await user.click(await screen.findByRole("button", { name: "Confirm promotion to Valid" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Pool changed. Preview again.");
    expect(screen.queryByRole("button", { name: "Confirm promotion to Valid" })).not.toBeInTheDocument();
  });

  it("shows a retryable API failure and handles an empty pipeline", async () => {
    mocks.GET.mockRejectedValueOnce(new Error("API offline"));
    const user = userEvent.setup();
    render(<HrPortal />);
    expect(await screen.findByRole("alert")).toHaveTextContent("API offline");
    mocks.GET.mockResolvedValue({ data: [] });
    await user.click(screen.getByRole("button", { name: "Refresh pipeline" }));
    expect(await screen.findByText("No candidates in this view")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Pipeline" })).queryByRole("table")).not.toBeInTheDocument();
  });
});
