/**
 * The public referral code check.
 *
 * The referral check answers only "usable or not" (Q117, ADR-0023 §16): it never shows, guesses or hints who owns
 * the code, and it does not attribute anything - attribution is a separate, explicit step elsewhere.
 */
import { useEffect, useState } from "react";

import { checkReferralCode } from "../../api/v2/safety.api";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { ErrorNote, Field, InlineButton, Loading, cls } from "../ui/mobile";
import { translate } from "../../i18n";

export function ReferralCodeCheck(props: { initialCode?: string; onValid?: (code: string) => void }) {
  const [code, setCode] = useState(props.initialCode ?? "");
  const [checked, setChecked] = useState<{ code: string; valid: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const trimmed = code.trim();

  async function check() {
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    setChecked(null);
    try {
      const result = await checkReferralCode(trimmed);
      setChecked({ code: trimmed, valid: result.valid });
      if (result.valid) props.onValid?.(trimmed);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Field
        label={translate("referralCheck.Label")}
        value={code}
        onChange={(value) => {
          setCode(value.slice(0, 64));
          setChecked(null);
        }}
        placeholder={translate("referralCheck.Placeholder")}
      />
      <InlineButton tone="primary" disabled={!trimmed || busy} onClick={check}>
        {translate("referralCheck.Check")}
      </InlineButton>
      <ErrorNote message={error ? v2ErrorMessage(error) : null} />
      {checked ? (
        <p
          data-testid="referral-result"
          className={cls("text-[13px]", checked.valid ? "text-success" : "text-muted-foreground")}
        >
          {checked.valid ? translate("referralCheck.Valid") : translate("referralCheck.Invalid")}
        </p>
      ) : null}
    </div>
  );
}
