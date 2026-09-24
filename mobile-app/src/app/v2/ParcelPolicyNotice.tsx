/**
 * §5.2: what may not be sent, as the confirmed policy version lists it.
 *
 * `approved=false` means the list is not published yet - never "everything is allowed". Each rule is shown with the
 * legal basis and source the server returns; nothing is added or guessed on the client.
 */
import { parcelPolicy, type ParcelPolicyDTO, type ParcelPolicyItemDTO } from "../../api/v2/safety.api";
import { translate } from "../../i18n";
import type { MessageKey } from "../../i18n/messages";
import { formatDate } from "../../utils/v2Format";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { Card, ErrorNote, SkeletonCard, WarningNote } from "../ui/mobile";
import { useAsync } from "./useAsync";

// The label is a dictionary key, looked up at render time so it follows a language switch.
const CATEGORIES: Array<[ParcelPolicyItemDTO["category"], MessageKey]> = [
  ["prohibited", "parcelPolicy.category.prohibited"],
  ["restricted", "parcelPolicy.category.restricted"],
  ["business_declined", "parcelPolicy.category.business_declined"],
];

const APPLIES_TO: Record<string, string> = {
  get parcel() { return translate("parcelPolicy.appliesTo.parcel"); },
  get passenger_baggage() { return translate("parcelPolicy.appliesTo.passenger_baggage"); },
  get all() { return translate("parcelPolicy.appliesTo.all"); },
};

function PolicyItem({ item }: { item: ParcelPolicyItemDTO }) {
  const source = [item.legal_basis, item.source_ref].filter(Boolean).join(" · ");
  return (
    <li className="rounded-[10px] bg-background px-3 py-2" data-testid="policy-item">
      <p className="text-[14px] font-medium text-foreground">{item.title}</p>
      <p className="text-[12px] leading-5 text-muted-foreground">{item.description}</p>
      <p className="text-[11px] text-muted-foreground">{APPLIES_TO[item.applies_to ?? "parcel"] ?? item.applies_to}</p>
      {source ? (
        <p className="text-[11px] text-muted-foreground">
          {item.source_checked_on
            ? translate("parcelPolicy.sourceChecked", { source, date: item.source_checked_on })
            : translate("parcelPolicy.source", { source })}
        </p>
      ) : null}
    </li>
  );
}

export function ParcelPolicyView({ policy }: { policy: ParcelPolicyDTO }) {
  const items = policy.items ?? [];
  if (!policy.approved) {
    return (
      <Card>
        <strong className="text-[15px]">{translate("parcelPolicy.title")}</strong>
        <WarningNote>{policy.notice}</WarningNote>
        <p className="text-[12px] leading-5 text-muted-foreground" data-testid="policy-unconfirmed">
          {translate("parcelPolicy.unconfirmed")}
        </p>
      </Card>
    );
  }
  return (
    <Card>
      <strong className="text-[15px]">{translate("parcelPolicy.title")}</strong>
      <p className="text-[12px] leading-5 text-muted-foreground">{policy.notice}</p>
      {policy.label || policy.effective_from ? (
        <p className="text-[11px] text-muted-foreground">
          {[policy.label, policy.effective_from ? translate("parcelPolicy.effectiveFrom", { date: formatDate(policy.effective_from) }) : null].filter(Boolean).join(" · ")}
        </p>
      ) : null}
      {items.length === 0 ? (
        <p className="text-[12px] leading-5 text-muted-foreground" data-testid="policy-empty">
          {translate("parcelPolicy.empty")}
        </p>
      ) : (
        CATEGORIES.map(([category, label]) => {
          const group = items.filter((item) => item.category === category);
          if (!group.length) return null;
          return (
            <section key={category} className="flex flex-col gap-1.5">
              <p className="text-[12px] font-semibold text-secondary-foreground">{translate(label)}</p>
              <ul className="flex flex-col gap-1.5">
                {group.map((item) => (
                  <PolicyItem key={item.code} item={item} />
                ))}
              </ul>
            </section>
          );
        })
      )}
    </Card>
  );
}

export function ParcelPolicyNotice() {
  const state = useAsync<ParcelPolicyDTO>(() => parcelPolicy(), []);
  if (state.loading) return <SkeletonCard lines={3} />;
  if (!state.data) {
    return (
      <Card>
        <ErrorNote message={v2ErrorMessage(state.error)} onRetry={state.reload} />
        <p className="text-[12px] leading-5 text-muted-foreground">
          {translate("parcelPolicy.loadFailed")}
        </p>
      </Card>
    );
  }
  return <ParcelPolicyView policy={state.data} />;
}
