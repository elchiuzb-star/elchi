/**
 * MFA step-up for privileged admin commands (ADR-0021).
 *
 * Money, flag and promo commands may answer `403 FORBIDDEN` with `details.reason = "step_up_required"`: the server
 * wants a fresh authenticator code before it acts. This hook turns that refusal into a prompt and a retry, so a
 * panel does not have to know the flow.
 *
 * Usage (stable API, shared by chunk B and chunk C panels):
 *
 *   const stepUp = useStepUp();
 *   const key = newIdempotencyKey();                     // one key per confirmed user action
 *   try {
 *     await stepUp.run(() => someCommand(id, body, key)); // the SAME closure (and key) is replayed after the code
 *   } catch (error) {
 *     if (isStepUpCancelled(error)) return;              // the person closed the prompt: nothing happened
 *     showError(error);                                  // any other refusal, unchanged
 *   }
 *   ...
 *   {stepUp.prompt}                                      // render where the MFA block belongs (null when idle)
 *
 * `run` resolves only when the work finally succeeds. While the code is being asked for, the promise stays pending,
 * so the caller's own "busy" flag keeps its buttons disabled and nobody can submit the action twice. The work is
 * replayed with the key it was first sent with, which is what makes the retry safe (ADR-0005).
 *
 * The file is `.ts` so it can be imported from plain helpers too; the prompt is built with `createElement`.
 */
import { createElement, useCallback, useRef, useState, type ReactNode } from "react";

import { stepUp as proveStepUp } from "../api/v2/mfa.api";
import { translate } from "../i18n";
import { ApiError } from "../types/api";
import { v2ErrorMessage } from "../utils/v2Errors";

/** `true` for the server's "prove your factor first" refusal (ADR-0021, identity/mfa.py `require_step_up`). */
export function isStepUpRequired(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.code !== "FORBIDDEN") return false;
  const details = error.details;
  return typeof details === "object" && details !== null && (details as { reason?: unknown }).reason === "step_up_required";
}

/** Thrown from `run` when the person closes the code prompt instead of entering a code. Nothing was executed. */
export class StepUpCancelled extends Error {
  constructor() {
    super("step_up_cancelled");
    this.name = "StepUpCancelled";
  }
}

export function isStepUpCancelled(error: unknown): boolean {
  return error instanceof StepUpCancelled;
}

type Waiting = {
  work: () => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
};

export type StepUpController = {
  /** Runs `work`; on `step_up_required` asks for a code, proves it and replays the same `work`. */
  run: <T>(work: () => Promise<T>) => Promise<T>;
  /** A code is being asked for. */
  waiting: boolean;
  /** The step-up call or the replay is in flight. */
  busy: boolean;
  /** The MFA block, or null when no code is needed. */
  prompt: ReactNode;
  /** Closes the prompt; the pending `run` rejects with `StepUpCancelled`. */
  cancel: () => void;
};

export function useStepUp(): StepUpController {
  const waitingRef = useRef<Waiting | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = useCallback(() => {
    waitingRef.current = null;
    setWaiting(false);
    setCode("");
    setError(null);
    setBusy(false);
  }, []);

  const run = useCallback(<T,>(work: () => Promise<T>): Promise<T> => {
    return work().catch((cause: unknown) => {
      if (!isStepUpRequired(cause)) throw cause;
      return new Promise<T>((resolve, reject) => {
        // A second step-up while one is open replaces nothing: the first prompt still owns the code.
        if (waitingRef.current) {
          reject(cause);
          return;
        }
        waitingRef.current = { work, resolve: resolve as (value: unknown) => void, reject };
        setError(null);
        setCode("");
        setWaiting(true);
      });
    });
  }, []);

  const cancel = useCallback(() => {
    const current = waitingRef.current;
    close();
    current?.reject(new StepUpCancelled());
  }, [close]);

  const submit = useCallback(async () => {
    const current = waitingRef.current;
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await proveStepUp(code.trim());
    } catch (cause) {
      setError(v2ErrorMessage(cause));
      setBusy(false);
      return;
    }
    try {
      const value = await current.work();
      close();
      current.resolve(value);
    } catch (cause) {
      if (isStepUpRequired(cause)) {
        // The proof did not stick (clock skew, another tab): keep asking rather than failing the action.
        setError(translate("admin.stepUp.again"));
        setCode("");
        setBusy(false);
        return;
      }
      close();
      current.reject(cause);
    }
  }, [code, close]);

  const prompt: ReactNode = waiting
    ? createElement(
        "div",
        {
          role: "dialog",
          "aria-label": translate("admin.stepUp.title"),
          className: "space-y-2 rounded-[12px] border border-warning/40 bg-warning/8 p-3",
        },
        createElement("p", { className: "text-sm font-semibold text-foreground" }, translate("admin.stepUp.title")),
        createElement("p", { className: "text-xs text-muted-foreground" }, translate("admin.stepUp.text")),
        createElement(
          "label",
          { className: "block space-y-1" },
          createElement("span", { className: "text-xs font-medium text-muted-foreground" }, translate("admin.stepUp.codeLabel")),
          createElement("input", {
            value: code,
            onChange: (event: { target: { value: string } }) => setCode(event.target.value.replace(/\D/g, "").slice(0, 8)),
            inputMode: "numeric",
            autoComplete: "one-time-code",
            placeholder: "123456",
            className: "h-10 w-40 rounded-[10px] border border-input bg-card px-3 text-sm tracking-widest text-foreground",
          }),
        ),
        error ? createElement("p", { role: "alert", className: "text-sm text-destructive" }, error) : null,
        createElement(
          "div",
          { className: "flex flex-wrap gap-2" },
          createElement(
            "button",
            {
              type: "button",
              disabled: busy || code.trim().length < 6,
              onClick: () => void submit(),
              className: "h-9 rounded-[10px] bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50",
            },
            translate("admin.stepUp.submit"),
          ),
          createElement(
            "button",
            {
              type: "button",
              disabled: busy,
              onClick: cancel,
              className: "h-9 rounded-[10px] border border-border bg-card px-3 text-sm font-medium text-foreground disabled:opacity-50",
            },
            translate("common.cancel"),
          ),
        ),
        createElement("p", { className: "text-xs text-muted-foreground" }, translate("admin.stepUp.noFactor")),
      )
    : null;

  return { run, waiting, busy, prompt, cancel };
}
