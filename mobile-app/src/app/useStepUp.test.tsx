/**
 * The shared MFA step-up helper (ADR-0021): a `step_up_required` refusal turns into a code prompt, the proof is sent,
 * and the very same work (same closure, same idempotency key) is replayed; any other refusal passes through untouched.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/v2/mfa.api", async (importOriginal) => ({ ...(await importOriginal<object>()), stepUp: vi.fn() }));

import * as mfa from "../api/v2/mfa.api";
import { ApiError } from "../types/api";
import { isStepUpCancelled, isStepUpRequired, useStepUp } from "./useStepUp";

const m = <T,>(fn: T) => fn as unknown as ReturnType<typeof vi.fn>;
const stepUpError = () => new ApiError(403, { code: "FORBIDDEN", message: "x", details: { reason: "step_up_required" } });

function Harness({ work }: { work: () => Promise<string> }) {
  const stepUp = useStepUp();
  const [result, setResult] = useState("");
  return (
    <div>
      <button
        type="button"
        onClick={() =>
          stepUp.run(work).then(
            (value) => setResult(`ok:${value}`),
            (error) => setResult(isStepUpCancelled(error) ? "cancelled" : `error:${(error as Error).message}`),
          )
        }
      >
        go
      </button>
      {stepUp.prompt}
      <output>{result}</output>
    </div>
  );
}

beforeEach(() => vi.clearAllMocks());

describe("useStepUp", () => {
  it("recognises only the step-up refusal", () => {
    expect(isStepUpRequired(stepUpError())).toBe(true);
    expect(isStepUpRequired(new ApiError(403, { code: "FORBIDDEN", message: "x" }))).toBe(false);
    expect(isStepUpRequired(new Error("x"))).toBe(false);
  });

  it("asks for a code, proves it and replays the same work", async () => {
    const work = vi.fn().mockRejectedValueOnce(stepUpError()).mockResolvedValueOnce("done");
    m(mfa.stepUp).mockResolvedValue({});
    render(<Harness work={work} />);
    fireEvent.click(screen.getByText("go"));
    const input = await screen.findByPlaceholderText("123456");
    fireEvent.change(input, { target: { value: "65 43 21" } });
    expect((input as HTMLInputElement).value).toBe("654321");
    fireEvent.click(screen.getByRole("button", { name: "Tasdiqlash va davom etish" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("ok:done"));
    expect(mfa.stepUp).toHaveBeenCalledWith("654321");
    expect(work).toHaveBeenCalledTimes(2);
  });

  it("keeps the prompt open on a wrong code and rejects with StepUpCancelled on cancel", async () => {
    const work = vi.fn().mockRejectedValue(stepUpError());
    m(mfa.stepUp).mockRejectedValue(new ApiError(400, { code: "MFA_CODE_INVALID", message: "Kod noto'g'ri" }));
    render(<Harness work={work} />);
    fireEvent.click(screen.getByText("go"));
    fireEvent.change(await screen.findByPlaceholderText("123456"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Tasdiqlash va davom etish" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(work).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Bekor qilish" })));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("cancelled"));
    expect(screen.queryByPlaceholderText("123456")).toBeNull();
  });

  it("passes any other refusal through without a prompt", async () => {
    const work = vi.fn().mockRejectedValue(new Error("boom"));
    render(<Harness work={work} />);
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("error:boom"));
    expect(screen.queryByPlaceholderText("123456")).toBeNull();
  });
});
