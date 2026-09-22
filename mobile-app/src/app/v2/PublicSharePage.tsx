/**
 * O3: the page an outsider opens from a shared link (§20.2). No authentication, no identity, no tracking of them.
 *
 * It shows what the share text promised - route, window, price, whether the listing is still open - and invites the
 * viewer into the app, where they sign in with OTP before they can offer anything. An unknown, revoked or expired
 * link is a plain "not found": the page never reveals that a token once existed.
 */
import { publicListingPage, type PublicListingPageDTO } from "../../api/v2/bookings.api";
import { formatMinor, formatWindow, priceBasisLabel } from "../../utils/v2Format";
import { Badge, COLORS, Card, ErrorNote, Loading, PrimaryButton, Row, ScreenBody } from "../ui/mobile";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { useAsync } from "./useAsync";

export function PublicSharePage({ token, onOpenApp }: { token: string; onOpenApp: () => void }) {
  const page = useAsync<PublicListingPageDTO>(() => publicListingPage(token), [token]);

  if (page.loading) {
    return (
      <ScreenBody>
        <Loading />
      </ScreenBody>
    );
  }
  if (!page.data) {
    return (
      <ScreenBody>
        <ErrorNote message={page.error ? v2ErrorMessage(page.error) : null} onRetry={page.reload} />
        <span style={{ fontSize: 14, color: COLORS.muted }}>
          Havola eskirgan bo'lishi mumkin. E'lon egasidan yangi havola so'rang.
        </span>
      </ScreenBody>
    );
  }

  const item = page.data;
  return (
    <ScreenBody>
      <Card>
        <div className="flex items-center justify-between gap-2">
          <strong>
            {item.origin_stop_name} → {item.destination_stop_name}
          </strong>
          <Badge text={item.status_open ? "Ochiq" : "Yopiq"} tone={item.status_open ? "ok" : "neutral"} />
        </div>
        <Row label="Xizmat" value={item.service_type === "passenger" ? "Yo'lovchi" : "Pochta"} />
        <Row label="Sana" value={item.departure_date} />
        <Row label="Vaqt oynasi" value={formatWindow(item.departure_window_start, item.departure_window_end)} />
        <Row label="Narx birligi" value={priceBasisLabel(item.price_basis)} />
        <Row label="Jami" value={formatMinor(item.total_minor, item.currency)} strong />
      </Card>

      <Card>
        <span style={{ fontSize: 14, color: COLORS.muted }}>
          {item.status_open
            ? "Taklif berish uchun ilovaga kiring: telefon raqamingiz SMS kod bilan tasdiqlanadi. Bron ilova ichida saqlanadi."
            : "Bu e'lon hozir yangi taklif qabul qilmayapti."}
        </span>
        <PrimaryButton onClick={onOpenApp} disabled={!item.status_open}>Ilovani ochish</PrimaryButton>
      </Card>

      <span style={{ fontSize: 12, color: COLORS.muted }}>
        Bu sahifada e'lon egasining ismi va telefoni ko'rsatilmaydi.
      </span>
    </ScreenBody>
  );
}
