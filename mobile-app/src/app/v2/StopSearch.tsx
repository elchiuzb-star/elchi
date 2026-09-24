/**
 * Free-text stop search (`GET /stops/search`) and the public referral code check.
 *
 * The referral check answers only "usable or not" (Q117, ADR-0023 §16): it never shows, guesses or hints who owns
 * the code, and it does not attribute anything - attribution is a separate, explicit step elsewhere.
 */
import { useEffect, useState } from "react";

import { checkReferralCode, searchStops, type StopDTO } from "../../api/v2/safety.api";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { ErrorNote, Field, InlineButton, Loading, cls } from "../ui/mobile";
import { translate } from "../../i18n";

export const STOP_QUERY_MIN = 2;
export const STOP_QUERY_MAX = 80;
const DEBOUNCE_MS = 300;

export function StopSearch(props: {
  onSelect: (stop: StopDTO) => void;
  regionId?: string;
  label?: string;
  limit?: number;
  /** Tests pass 0; the default waits for the person to stop typing. */
  debounceMs?: number;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StopDTO[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);
  const q = query.trim();

  useEffect(() => {
    if (q.length < STOP_QUERY_MIN) {
      setResults(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      searchStops({ q, region_id: props.regionId, limit: props.limit ?? 20 })
        .then((rows) => {
          if (cancelled) return;
          setResults(rows);
          setError(null);
        })
        .catch((cause) => {
          if (!cancelled) setError(cause);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, props.debounceMs ?? DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [q, props.regionId, props.limit, props.debounceMs, nonce]);

  return (
    <div className="flex flex-col gap-2">
      <Field
        label={props.label ?? translate("stopSearch.label")}
        value={query}
        onChange={(value) => setQuery(value.slice(0, STOP_QUERY_MAX))}
        placeholder={translate("stopSearch.placeholder")}
        hint={q.length > 0 && q.length < STOP_QUERY_MIN ? translate("stopSearch.minChars") : undefined}
      />
      {loading ? <Loading label={translate("stopSearch.searching")} /> : null}
      {!loading && error ? <ErrorNote message={v2ErrorMessage(error)} onRetry={() => setNonce((n) => n + 1)} /> : null}
      {!loading && !error && results && results.length === 0 ? (
        <p className="text-[13px] text-muted-foreground" data-testid="stops-empty">
          {translate("stopSearch.empty")}
        </p>
      ) : null}
      {!loading && !error && results && results.length > 0 ? (
        <ul className="flex flex-col gap-1.5" data-testid="stops-list">
          {results.map((stop) => (
            <li key={stop.id}>
              <button
                type="button"
                disabled={!stop.is_active}
                onClick={() => props.onSelect(stop)}
                className={cls(
                  "el-press w-full rounded-[10px] bg-background px-3 py-2 text-left disabled:opacity-60",
                )}
              >
                <span className="block text-[14px] font-medium text-foreground">{stop.name_uz}</span>
                <span className="block text-[12px] text-muted-foreground">
                  {stop.district.name_uz}
                  {stop.is_active ? "" : ` · ${translate("stopSearch.inactive")}`}
                </span>
                {stop.meeting_note ? (
                  <span className="block text-[11px] text-muted-foreground">{stop.meeting_note}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

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
        label={translate("stopSearch.referralLabel")}
        value={code}
        onChange={(value) => {
          setCode(value.slice(0, 64));
          setChecked(null);
        }}
        placeholder={translate("stopSearch.referralPlaceholder")}
      />
      <InlineButton tone="primary" disabled={!trimmed || busy} onClick={check}>
        {translate("stopSearch.referralCheck")}
      </InlineButton>
      <ErrorNote message={error ? v2ErrorMessage(error) : null} />
      {checked ? (
        <p
          data-testid="referral-result"
          className={cls("text-[13px]", checked.valid ? "text-success" : "text-muted-foreground")}
        >
          {checked.valid ? translate("stopSearch.referralValid") : translate("stopSearch.referralInvalid")}
        </p>
      ) : null}
    </div>
  );
}
