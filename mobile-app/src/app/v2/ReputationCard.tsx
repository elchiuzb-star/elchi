/**
 * S2: a person's reputation for one service, exactly as the server returns it.
 *
 * No invented rating (§8.2, AC36): without ratings the card says "hali baholanmagan" and shows no stars and no
 * number. The card does not claim anything the DTO does not carry (e.g. document checks).
 */
import { userReputation, type ReputationDTO, type ServiceType } from "../../api/v2/safety.api";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { Badge, Card, ErrorNote, Row, SkeletonCard } from "../ui/mobile";
import { useAsync } from "./useAsync";
import { translate } from "../../i18n";

export function formatRating(value: number): string {
  return value.toFixed(1).replace(".", ",");
}

export function ReputationView({ reputation }: { reputation: ReputationDTO }) {
  const rated = reputation.rating_count > 0 && reputation.average_rating !== null && reputation.average_rating !== undefined;
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <strong className="text-[15px]">{translate("reputation.title")}</strong>
        {rated ? (
          <span className="text-[15px] font-semibold text-foreground" data-testid="rating-value">
            ★ {formatRating(reputation.average_rating as number)}
          </span>
        ) : (
          <Badge text={translate("reputation.new")} tone="neutral" />
        )}
      </div>
      {rated ? (
        <Row label={translate("reputation.ratingCount")} value={translate("reputation.count", { count: reputation.rating_count })} />
      ) : (
        <p className="text-[13px] text-muted-foreground" data-testid="rating-none">{translate("reputation.notRated")}</p>
      )}
      <Row label={translate("reputation.completedBookings")} value={translate("reputation.count", { count: reputation.completed_bookings })} />
      {reputation.completed_trips > 0 ? <Row label={translate("reputation.completedTrips")} value={translate("reputation.count", { count: reputation.completed_trips })} /> : null}
    </Card>
  );
}

export function ReputationCard(props: { userId: string; serviceType: ServiceType }) {
  const state = useAsync<ReputationDTO>(() => userReputation(props.userId, props.serviceType), [props.userId, props.serviceType]);
  if (state.loading) return <SkeletonCard lines={2} />;
  if (!state.data) return <ErrorNote message={v2ErrorMessage(state.error)} onRetry={state.reload} />;
  return <ReputationView reputation={state.data} />;
}
