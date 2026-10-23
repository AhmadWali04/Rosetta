import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ApplyForm, { JOB_ID } from "./ApplyForm";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

function makeFile(name: string, type: string, sizeBytes: number): File {
  return new File([new Uint8Array(sizeBytes)], name, { type });
}

beforeEach(() => {
  pushMock.mockReset();
  vi.unstubAllGlobals();
});

describe("ApplyForm client-side validation", () => {
  it("rejects a non-PDF/DOCX file with a visible error", async () => {
    // applyAccept: false — the input's `accept` attribute makes real browser
    // file pickers (and user-event, by default) filter out a .txt file
    // before it's even selected. We want to exercise our own
    // validateResumeFile() defense-in-depth, which still matters for
    // browsers/flows that don't enforce `accept` (e.g. drag-and-drop).
    const user = userEvent.setup({ applyAccept: false });
    render(<ApplyForm />);

    const input = screen.getByLabelText(/resume/i);
    await user.upload(input, makeFile("resume.txt", "text/plain", 1024));

    expect(await screen.findByRole("alert")).toHaveTextContent(/pdf or docx/i);
  });

  it("rejects an oversized PDF file with a visible error", async () => {
    const user = userEvent.setup();
    render(<ApplyForm />);

    const input = screen.getByLabelText(/resume/i);
    await user.upload(
      input,
      makeFile("resume.pdf", "application/pdf", 6 * 1024 * 1024)
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/5mb/i);
  });

  it("accepts a valid small PDF file with no error", async () => {
    const user = userEvent.setup();
    render(<ApplyForm />);

    const input = screen.getByLabelText(/resume/i);
    await user.upload(input, makeFile("resume.pdf", "application/pdf", 2048));

    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ApplyForm submit flow", () => {
  it("sends the right FormData fields and navigates to the confirmation page on success", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "app-123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ApplyForm />);

    await user.type(screen.getByLabelText(/full name/i), "Jordan Doe");
    await user.type(screen.getByLabelText(/^email$/i), "jordan@example.com");
    await user.upload(
      screen.getByLabelText(/resume/i),
      makeFile("resume.pdf", "application/pdf", 2048)
    );
    await user.click(screen.getByRole("button", { name: /submit application/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/applications");
    expect(init.method).toBe("POST");

    const body = init.body as FormData;
    expect(body.get("job_id")).toBe(JOB_ID);
    expect(body.get("name")).toBe("Jordan Doe");
    expect(body.get("email")).toBe("jordan@example.com");
    expect(body.get("resume")).toBeInstanceOf(File);

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/applications/app-123"));
  });

  it("shows a visible error and does not navigate when the API call fails", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Email already applied to this job." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ApplyForm />);

    await user.type(screen.getByLabelText(/full name/i), "Jordan Doe");
    await user.type(screen.getByLabelText(/^email$/i), "jordan@example.com");
    await user.upload(
      screen.getByLabelText(/resume/i),
      makeFile("resume.pdf", "application/pdf", 2048)
    );
    await user.click(screen.getByRole("button", { name: /submit application/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /already applied/i
    );
    expect(pushMock).not.toHaveBeenCalled();
  });
});
