import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { components } from "../../../lib/api-types";
import CopilotPanel from "./CopilotPanel";

vi.mock("../../../lib/api", () => ({ API_BASE_URL: "http://localhost:8000" }));
type Result = components["schemas"]["CopilotResult"];
type Event = components["schemas"]["CopilotEvent"];
const citation: components["schemas"]["CopilotCitation"] = {
  chunk_id: "chunk-1", application_id: "candidate-1", text: "Built a RAG pipeline.",
  section: "experience", char_start: 0, char_end: 21,
};
const baseResult: Result = {
  run_id: "run-1", route: "verify", claims: [{ text: "Built a RAG pipeline 🔎", chunk_ids: ["chunk-1"] }],
  citations: [citation], explanation: "Uncited candidate prose must stay hidden.", confidence: 0.8,
  warnings: [], steps: ["supervisor", "evidence_verifier", "grounding_check"], retries: 0,
  needs_confirmation: false, proposal: null,
};
const props = { jobId: "job-1", candidateId: "candidate-1", blind: false, onCitation: vi.fn(), onStatusChanged: vi.fn() };
let fetchMock: ReturnType<typeof vi.fn>;

function event(result: Result | null, status: Event["status"] = "completed", name: Event["event"] = "result"): Event {
  return { event: name, run_id: "run-1", status, result, error: null };
}

function response(events: Event[], splitEvery = 7): Response {
  const content = events.map((item) => `event: ${item.event}\r\ndata: ${JSON.stringify(item)}\r\n\r\n`).join("");
  const bytes = new TextEncoder().encode(content);
  const body = new ReadableStream<Uint8Array>({ start(controller) {
    for (let index = 0; index < bytes.length; index += splitEvery) controller.enqueue(bytes.slice(index, index + splitEvery));
    controller.close();
  } });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

async function ask() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Your question"), "Verify RAG experience");
  await user.click(screen.getByRole("button", { name: "Ask copilot" }));
  return user;
}

beforeEach(() => {
  vi.resetAllMocks();
  fetchMock = vi.fn().mockResolvedValue(response([event(null, "queued", "queued"), event(null, "running", "progress"), event(baseResult)]));
  vi.stubGlobal("fetch", fetchMock);
});

it("decodes split UTF-8/SSE frames and passes the complete grounded citation to the viewer", async () => {
  render(<CopilotPanel {...props} />);
  const user = await ask();
  expect(await screen.findByText("Built a RAG pipeline 🔎")).toBeInTheDocument();
  expect(screen.queryByText(baseResult.explanation)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "View source 1 for claim 1" }));
  expect(props.onCitation).toHaveBeenCalledWith(citation);
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/copilot", expect.objectContaining({
    method: "POST", headers: { "X-Role": "hr", "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: "job-1", scope: "candidate:candidate-1", message: "Verify RAG experience" }),
  }));
  expect(props.onStatusChanged).not.toHaveBeenCalled();
});

it("displays verification warnings and suppresses unresolved candidate claims", async () => {
  fetchMock.mockResolvedValue(response([event({ ...baseResult, confidence: 0.3, warnings: ["Could not verify the claim from the resume."], claims: [{ text: "Unsupported candidate fact", chunk_ids: ["missing"] }], steps: ["evidence_verifier", "deep_verify", "grounding_check"], retries: 2 })]));
  render(<CopilotPanel {...props} />);
  await ask();
  expect(await screen.findByText("Could not verify the claim from the resume.")).toBeInTheDocument();
  expect(screen.queryByText("Unsupported candidate fact")).not.toBeInTheDocument();
  expect(screen.getByText(/Some claims were hidden/)).toBeInTheDocument();
  expect(screen.getByText("30% confidence")).toBeInTheDocument();
  expect(screen.getByText("deep verify")).toBeInTheDocument();
});

it("shows taxonomy explanations without inventing candidate evidence", async () => {
  fetchMock.mockResolvedValue(response([event({ ...baseResult, route: "explain", claims: [], citations: [], explanation: "RAG retrieves relevant documents before generating an answer." })]));
  render(<CopilotPanel {...props} />);
  await ask();
  expect(await screen.findByText("RAG retrieves relevant documents before generating an answer.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /View source/ })).not.toBeInTheDocument();
});

it.each(["similar", "verify"])("handles peer citations according to the %s route", async (route) => {
  const peerCitation = { ...citation, chunk_id: "peer-chunk", application_id: "candidate-2" };
  fetchMock.mockResolvedValue(response([event({ ...baseResult, route, citations: [peerCitation], claims: [{ text: "Peer built a comparable pipeline.", chunk_ids: [peerCitation.chunk_id] }] })]));
  render(<CopilotPanel {...props} />);
  const user = await ask();
  await screen.findByText(`Agent: ${route}`);
  if (route === "similar") {
    expect(screen.getByText("Peer built a comparable pipeline.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View source 1 for claim 1" }));
    expect(props.onCitation).toHaveBeenCalledWith(peerCitation);
  } else {
    expect(screen.queryByText("Peer built a comparable pipeline.")).not.toBeInTheDocument();
    expect(screen.getByText("No grounded candidate claims could be verified from the available evidence.")).toBeInTheDocument();
  }
});

it.each([true, false])("requires an explicit human confirmation choice (%s)", async (approve) => {
  const proposed: Result = { ...baseResult, route: "update_status", claims: [], citations: [], explanation: "", needs_confirmation: true, proposal: { application_id: "candidate-1", status: "pending", reason: "HR requested further review" } };
  const outcome = approve ? "The HR-confirmed status change was recorded in the audit log." : "Status change cancelled; no candidate status was changed.";
  fetchMock.mockResolvedValueOnce(response([event(proposed, "awaiting_confirmation")]))
    .mockResolvedValueOnce(response([event({ ...proposed, explanation: outcome, needs_confirmation: false, proposal: null }, "completed")]));
  render(<CopilotPanel {...props} />);
  const user = await ask();
  await screen.findByRole("button", { name: "Confirm status change" });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(props.onStatusChanged).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: approve ? "Confirm status change" : "Cancel proposed change" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock).toHaveBeenLastCalledWith("http://localhost:8000/copilot/run-1/confirm", expect.objectContaining({ body: JSON.stringify({ approve }) }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm status change" })).not.toBeInTheDocument());
  expect(screen.getByText(outcome)).toBeInTheDocument();
  expect(screen.queryByText("No grounded candidate claims could be verified from the available evidence.")).not.toBeInTheDocument();
  expect(props.onStatusChanged).toHaveBeenCalledTimes(approve ? 1 : 0);
});

it("clears context and aborts a late result when the selected candidate changes", async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockReturnValueOnce(new Promise<Response>((done) => { resolve = done; }));
  const { rerender } = render(<CopilotPanel {...props} />);
  await ask();
  const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
  rerender(<CopilotPanel {...props} candidateId="candidate-2" />);
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(response([event(baseResult)])); });
  expect(screen.queryByText("Built a RAG pipeline 🔎")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Your question")).toHaveValue("");
  expect(props.onCitation).not.toHaveBeenCalled();
  expect(props.onStatusChanged).not.toHaveBeenCalled();
});

it("clears results on scope changes and suppresses all chat content in blind mode", async () => {
  const { rerender } = render(<CopilotPanel {...props} />);
  const user = await ask();
  await screen.findByText("Built a RAG pipeline 🔎");
  await user.selectOptions(screen.getByLabelText("Copilot scope"), "pool");
  expect(screen.queryByText("Built a RAG pipeline 🔎")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Your question")).toHaveValue("");
  rerender(<CopilotPanel {...props} blind />);
  expect(screen.queryByLabelText("Your question")).not.toBeInTheDocument();
  expect(screen.getByText(/Copilot is paused in blind mode/)).toBeInTheDocument();
});

it("sends pool scope when no candidate is selected", async () => {
  render(<CopilotPanel {...props} candidateId={null} />);
  await ask();
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).scope).toBe("pool");
  expect(screen.getByRole("option", { name: "Selected candidate" })).toBeDisabled();
});

it("reports an incomplete stream while retaining the queued run ID", async () => {
  fetchMock.mockResolvedValue(response([event(null, "queued", "queued")]));
  render(<CopilotPanel {...props} />);
  await ask();
  expect(await screen.findByRole("alert")).toHaveTextContent("event stream ended before a result");
  expect(screen.getByText("Run run-1")).toBeInTheDocument();
});

it("recovers a durable result with a read-only status request after a disconnected stream", async () => {
  fetchMock.mockResolvedValueOnce(response([event(null, "queued", "queued")]))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      id: "run-1", job_id: "job-1", scope: "candidate:candidate-1", message: "Verify RAG experience",
      status: "completed", result: baseResult, error: null, created_at: "2026-10-23T12:00:00",
    }), { headers: { "Content-Type": "application/json" } }));
  render(<CopilotPanel {...props} />);
  const user = await ask();
  await screen.findByRole("alert");
  await user.click(screen.getByRole("button", { name: "Check run status" }));
  expect(await screen.findByText("Built a RAG pipeline 🔎")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenLastCalledWith("http://localhost:8000/copilot/run-1", expect.objectContaining({ headers: { "X-Role": "hr" } }));
  expect(fetchMock.mock.calls[1][1]).not.toHaveProperty("method", "POST");
  expect(props.onStatusChanged).not.toHaveBeenCalled();
});

it.each(["malformed", "http", "server"])("shows a recoverable %s failure", async (kind) => {
  if (kind === "malformed") fetchMock.mockResolvedValue(new Response("event: result\ndata: nope\n\n", { headers: { "Content-Type": "text/event-stream" } }));
  if (kind === "http") fetchMock.mockResolvedValue(new Response("Denied", { status: 403 }));
  if (kind === "server") fetchMock.mockResolvedValue(response([{ ...event(null, "failed", "error"), error: "Could not verify this request." }]));
  render(<CopilotPanel {...props} />);
  await ask();
  expect(await screen.findByRole("alert")).toHaveTextContent(kind === "malformed" ? "malformed event data" : kind === "http" ? "403" : "Could not verify this request.");
  expect(screen.getByRole("button", { name: "Ask copilot" })).toBeEnabled();
});
