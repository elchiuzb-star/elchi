import { useEffect, useMemo, useRef, useState } from "react";
import type { ElementType, ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Bell,
  Camera,
  Check,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  FileText,
  Headphones,
  Home,
  LocateFixed,
  Loader2,
  MapPin,
  Menu,
  Navigation,
  LogOut,
  Package,
  Phone,
  RefreshCw,
  Send,
  Shield,
  Star,
  Tag,
  Truck,
  Upload,
  User,
  X,
} from "./ui/icons";

import {
  AppearancePicker,
  BarChart,
  ChoiceCard,
  cls,
  CodeField,
  ConfirmSheet,
  ElchiLogo,
  EmptyState,
  FaqItem,
  Field,
  GhostButton,
  IconTile,
  JourneySpine,
  PhoneField,
  PrimaryButton,
  ProfileActionRow,
  SecondaryButton,
  SectionLabel,
  SegmentedControl,
  SkeletonCard,
  StatusBadge,
  StepDots,
  TopBar,
  statusLabel,
} from "./ui/mobile";
import { ClientMapCanvas } from "../components/maps/ClientMapCanvas";
import { MapAddressPicker } from "../components/maps/MapAddressPicker";
import { RegionSelector } from "../components/location/RegionSelector";
import { GeoDistrictSelector } from "../components/location/GeoDistrictSelector";
import { loadStopOptions, type StopOption } from "../components/location/stops";
import { MapPointPicker, type MarkedPoint } from "../components/location/MapPointPicker";
import { AppSidebar, SidebarButton, clientSidebarItems } from "../components/nav/AppSidebar";
import { SeatPicker, type SeatId } from "../components/passenger/SeatPicker";
import { reverseGeocode } from "../api/geo.api";
import { RouteMap } from "./v2/RouteMap";
import {
  AcceptConsentPanel,
  BonusConsentPanel,
  BonusScreen,
  NoDiscountNote,
  PromoMoneyCard,
  StaleConfirmation,
} from "./v2/PromoScreens";
import { proofCodeHint } from "./proofCodes";
import {
  NO_CONSENT,
  actionKey,
  amendmentCashNote,
  cashDueMinor,
  consentBody,
  driverAckRequested,
  finishAction,
  needsRequote,
  pendingCode,
  type ConsentChoice,
} from "./promo";
import { isOffline } from "../utils/v2Errors";
import {
  acceptProposal,
  cancelListing,
  counterProposal,
  createListing,
  effectiveFlags,
  getListing,
  listCorridorDistricts,
  listDistricts,
  listRegions,
  listingMatches,
  listCorridorRoutes,
  listCorridorStops,
  listCorridors,
  listListingOffers,
  listListingProposals,
  offersFeed,
  previewDirection,
  withdrawProposal,
  listMyListings,
  publishListing,
  getProposal,
  patchListing,
  pauseListing,
  rejectProposal,
  resumeListing,
  type CorridorDTO,
  type DirectionPreviewDTO,
  type EffectiveFlagsDTO,
  type CorridorDistrictDTO,
  type DistrictDTO,
  type ListingCreate,
  type AnyBooking,
  type BookingClientDTO,
  type BookingDTO,
  type FeedItemDTO,
  type ListingDTO,
  type ListingOfferDTO,
  type MapPointDTO,
  type MatchDTO,
  type MediaRefDTO,
  type StopRefDTO,
  type ProposalThreadDTO,
  type RegionDTO,
  type RouteVersionDTO,
  type StopDTO,
} from "../api/v2/marketplace.api";
import { newIdempotencyKey } from "../api/v2/http";
import { LOCALES, translate, translateDynamic } from "../i18n";
import { useLocale } from "../i18n/react";
import { negotiationActions, turnLabel, type ActorSide } from "./auction";
import { alternativeReason, splitFeedGroups } from "./feedGroups";
import { offerableServices, type OfferService } from "./tripOffers";
import {
  CANCEL_REASONS,
  canCancelBooking,
  canOpenDispute,
  canRate,
  canReissueCode,
  cancelBlockedByReview,
  cancelRefusalKey,
  counterpartSide,
  disputeTypesFor,
  intentOfBooking,
  reissueWait,
  waitParts,
  type BookingSide,
} from "./bookingControls";
import { formFromListing, ownerListingActions, planListingPatch, windowEditable, type ListingEditForm } from "./listingEdit";
import { inboxBody, inboxTitle, parseInboxLink, unreadCount } from "./inbox";
import { bidTotalMinor, bpsPercent } from "./commissionPreview";
import { TripIntentEditor, TripIntentFitNotes, TripIntentSummary, type IntentEditForm } from "./v2/TripIntentPanel";
import { BlockPanel, MyReportsList, ReportForm } from "./v2/BlockAndReportPanel";
import { ShareLinkPanel, TrackingGrantPanel } from "./v2/TrackingSharePanel";
import { ReputationCard } from "./v2/ReputationCard";
import { ParcelPolicyNotice } from "./v2/ParcelPolicyNotice";
import { DriverTripDetail } from "./v2/DriverTripDetail";
import { StopSearch } from "./v2/StopSearch";
import { bookingCounterparty, canShareListing, canShareTracking, routesThroughStop } from "./safetyMounts";
import {
  closeTripIntent,
  createTripIntent,
  editTripIntent,
  getTripIntent,
  listTripIntents,
  reopenTripIntent,
  tripIntentFit,
  type TripIntentCreate,
  type TripIntentDTO,
  type TripIntentFitDTO,
  type TripIntentUpdate,
} from "../api/v2/tripIntents.api";
import {
  fitBlocks,
  intentSummary,
  isExpired,
  offersAffectedText,
  parcelDiffers,
  parcelInput,
  pickActive,
  prefillBid,
  priceLine,
  readActiveIntentId,
  updateBody,
  writeActiveIntentId,
} from "./tripIntent";
import {
  createTrip,
  createVehicle,
  listMyProposals,
  listMyTrips,
  listMyVehicles,
  bookingAction,
  commissionQuote,
  type CommissionQuoteDTO,
  createTopup,
  listTopups,
  requestsFeed,
  submitProposal,
  tripAction,
  wallet as fetchWallet,
  walletTransactions,
  type LedgerLineDTO,
  type TopupDTO,
  type TripDTO,
  type VehicleDTO,
  type WalletDTO,
} from "../api/v2/driver.api";
import {
  addDisputeEvidence,
  createSavedSearch,
  createSupportTicket,
  deleteSavedSearch,
  getDispute,
  markNotificationRead,
  myDisputes,
  notifications as fetchNotifications,
  type NotificationDTO,
  mySupportTickets,
  openDispute,
  rateBooking,
  savedSearches,
  supportContacts as fetchSupportContacts,
  type DisputeDTO,
  type SavedSearchDTO,
  type SupportContactsDTO,
  type SupportTicketDTO,
} from "../api/v2/client-extras.api";
import {
  acceptAmendment,
  cancelBooking,
  reissueBookingCode,
  type ProofKind,
  confirmAmendmentPromo,
  decideAmendment,
  decideCashReceipt,
  getBooking,
  listAmendments,
  proposeAmendment,
  type AmendmentDTO,
  getBookingCodes,
  getBookingTracking,
  getChatState,
  listMessages,
  listMyBookings,
  reportCashReceipt,
  sendMessage,
  type BookingCodesDTO,
  type BookingTrackingDTO,
  type CashReceiptDTO,
  type ChatMessageCreate,
  type ChatMessageDTO,
  type ChatThreadDTO,
} from "../api/v2/bookings.api";
import { ReadOnlyOrderMap } from "../components/maps/ReadOnlyOrderMap";
import { useAuth } from "../auth/AuthContext";
import { getCities } from "../api/cities.api";
import { getDistricts } from "../api/districts.api";
import { uploadFile } from "../api/files.api";
import {
  cancelClientOrder,
  confirmClientOrder,
  getClientOrder,
  listClientOrderBids,
  listClientOrders,
  openClientDispute,
  rateClientOrder,
  selectDriver,
} from "../api/client-orders.api";
import { getClientProfile, updateClientProfile } from "../api/client-profile.api";
import {
  getDriverProfile,
  listDriverDocuments,
  setDriverAvailability,
  submitDriverDocument,
  updateDriverProfile,
} from "../api/driver.api";
import type { City, District } from "../types/city";
import type { Bid } from "../types/bid";
import type { ClientOrder, CreateOrderPayload, OrderStatus } from "../types/order";
import type { DriverDocument, DriverDocumentType, DriverFeedOrder, DriverProfile, DriverRoute } from "../types/driver";
import type { MobileRole } from "../types/auth";
import { formatUzs } from "../utils/money";
import { normalizeUzPhone } from "../utils/phone";
import { getErrorMessage } from "../utils/errors";
import { createMapsDirectionsUrl, createMapsSearchUrl, hasLocation } from "../utils/maps";
import { formatAddressRegion, formatAddressTitle } from "../utils/address";

type Screen =
  | "splash"
  | "onboarding"
  | "role"
  | "phone"
  | "otp"
  | "client-home"
  | "client-location-selector"
  | "client-district-selector"
  | "client-point-picker"
  | "client-route-summary"
  | "client-order-address"
  | "client-order-parcel"
  | "client-order-photo"
  | "client-order-review"
  | "client-success"
  | "client-orders"
  | "client-offers"
  | "client-offer-bid"
  | "client-intent-edit"
  | "client-proposals"
  | "client-bonus"
  | "driver-bonus"
  | "client-order-detail"
  | "client-listing-detail"
  | "client-listing-bids"
  | "client-booking-detail"
  | "driver-proposals"
  | "booking-rating"
  | "booking-dispute"
  | "booking-chat"
  | "booking-amendment"
  | "listing-edit"
  | "dispute-detail"
  | "driver-saved-searches"
  | "my-disputes"
  | "support"
  | "settings"
  | "listing-matches"
  | "booking-tracking"
  | "client-bids"
  | "client-confirm"
  | "client-rating"
  | "client-dispute"
  | "client-notifications"
  | "driver-notifications"
  | "client-profile"
  | "driver-home"
  | "driver-profile-form"
  | "driver-documents"
  | "driver-routes"
  | "driver-trip-detail"
  | "safety-center"
  | "driver-add-route"
  | "driver-offer-create"
  | "driver-feed"
  | "driver-bid"
  | "driver-orders"
  | "driver-order-detail"
  | "driver-income"
  | "driver-profile";

type OrderDetail = ClientOrder & {
  from_city?: City;
  to_city?: City;
  from_district?: District | null;
  to_district?: District | null;
  pickup_address?: string;
  dropoff_address?: string;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  sender_phone?: string;
  receiver_phone?: string;
  comment?: string | null;
  assigned_driver?: {
    full_name?: string | null;
    phone?: string | null;
    car_model?: string | null;
    plate_number?: string | null;
    rating?: number | string | null;
  } | null;
};

type DriverOrderDetail = DriverFeedOrder & {
  pickup_address?: string;
  dropoff_address?: string;
  pickup_lat?: number | string | null;
  pickup_lng?: number | string | null;
  dropoff_lat?: number | string | null;
  dropoff_lng?: number | string | null;
  sender_phone?: string;
  receiver_phone?: string;
  final_price?: number | string | null;
  comment?: string | null;
};

type ConfirmAction =
  | { type: "select-driver"; bid: Bid }
  | { type: "confirm-delivery" }
  | { type: "cancel-order" };














const driverVerificationLabels: Record<string, string> = {
  get new() { return translate("app.driverVerification.new"); },
  get pending() { return translate("app.driverVerification.pending"); },
  get approved() { return translate("status.approved"); },
  get rejected() { return translate("status.rejected"); },
  get blocked() { return translate("app.driverVerification.blocked"); },
};

/**
 * A `[value, label]` pair whose label is read from the dictionary each time it is used, so the module-level
 * option lists below follow a language switch without changing how their callers destructure them.
 */
function labelledPair(value: string, key: Parameters<typeof translate>[0]): [string, string] {
  const pair: [string, string] = [value, ""];
  Object.defineProperty(pair, 1, { get: () => translate(key), enumerable: true });
  return pair;
}

/**
 * How many digits the code has.
 *
 * The backend decides it (`ELCHI_OTP_LENGTH`; Q137: 4 digits) and refuses a code of any other length, so the
 * screen must not hard-code its own number - it reads the same setting and falls back to the decided 4.
 */
const OTP_LENGTH = Number(import.meta.env.VITE_OTP_LENGTH) || 4;

/** How long the resend link stays hidden, from the reference client. Long enough that the SMS usually wins. */
const RESEND_SECONDS = 59;

/** Shown at the bottom of settings. Set at build time; `pilot` when nothing was injected. */
const APP_VERSION = import.meta.env.VITE_APP_VERSION || "pilot";

const emptyOrder: CreateOrderPayload = {
  from_city_id: 0,
  to_city_id: 0,
  from_district_id: null,
  to_district_id: null,
  pickup_address: "",
  dropoff_address: "",
  pickup_lat: null,
  pickup_lng: null,
  dropoff_lat: null,
  dropoff_lng: null,
  sender_phone: "",
  receiver_phone: "",
  cargo_photo_url: "",
  comment: "",
};


/**
 * One end of the direction the person is composing.
 *
 * Q88: an end is a verified stop **or** a place marked on the map, never both - `corridorId` is filled once a
 * stop pins the end to a corridor. The district and region travel along as the labels the person chose them
 * by, not as anything the matcher decides on.
 */
type DirectionEnd = {
  region: RegionDTO | null;
  district: DistrictDTO | null;
  stop: StopDTO | null;
  point: MarkedPoint | null;
  corridorId: string;
};

const emptyDirectionEnd: DirectionEnd = { region: null, district: null, stop: null, point: null, corridorId: "" };

/** Q68: the parcel kinds the contract allows, in the words the app uses for them. */
const PARCEL_TYPES: Array<[string, string]> = [
  labelledPair("documents", "app.parcelType.documents"),
  labelledPair("box", "app.parcelType.box"),
  labelledPair("bag", "app.parcelType.bag"),
  labelledPair("electronics", "app.parcelType.electronics"),
  labelledPair("clothing", "app.parcelType.clothing"),
  labelledPair("other", "app.parcelType.other"),
];

/**
 * Where the picker's map should open for the end being edited.
 *
 * District first, then region, then nothing. The region step is what makes Tashkent city work: there the city
 * *is* the direction unit (wave 10), so no district is ever chosen and without its own centre the map opened
 * on the whole country. `null` falls back to the country view, which is the honest answer when the catalogue
 * has no coordinate - better than opening confidently on the wrong town.
 */
/**
 * Where the map should open for this end, and how closely the catalogue knows that point.
 *
 * The district centre is the town itself and only 99 of the 170 districts have one - the catalogue keeps a
 * hand-checked coordinate or nothing at all, never a guess (migration 0081). For the rest the provincial
 * capital is the best honest answer: the right province, but not the right town, which is why the caller
 * zooms out for it.
 */
function mapCentreFor(end: DirectionEnd): { lat: number; lng: number; scope: "district" | "region" } | null {
  const district = end.district;
  if (district?.center_lat != null && district?.center_lng != null) {
    return { lat: district.center_lat, lng: district.center_lng, scope: "district" };
  }
  const region = end.region;
  if (region?.center_lat != null && region?.center_lng != null) {
    // A region that needs no district *is* the local unit (Tashkent city), so its centre is as precise as a
    // district's and earns the same close zoom. For the others the centre is the provincial capital, which
    // may be a hundred kilometres from the district chosen - that one has to open wide.
    return {
      lat: region.center_lat,
      lng: region.center_lng,
      scope: region.requires_district ? "region" : "district",
    };
  }
  return null;
}

/** How an end reads on screen: the marked address if there is one, else the names it was chosen by. */
function directionEndLabel(end: DirectionEnd): string {
  if (end.point) {
    return (
      end.point.address?.trim() || [end.district?.name_uz, end.region?.name_uz].filter(Boolean).join(", ")
    );
  }
  if (end.stop) return [end.stop.name_uz, end.stop.district.name_uz].filter(Boolean).join(", ");
  if (end.district) return [end.district.name_uz, end.region?.name_uz].filter(Boolean).join(", ");
  return end.region?.name_uz ?? "";
}

function formatWindowInput(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "-"
    : parsed.toLocaleString("uz-UZ", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function localInputToIso(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
}

/** Soum in, minor units out (1 so'm = 100 tiyin). Anything that is not a positive number is 0, never NaN. */
/** P8 accept body; `promo_consent` only when the person explicitly ticked the bonus (Q104). */
function acceptBody(
  versionId: string,
  termsVersion: number,
  promo: { passenger_bonus_minor: number; cash_due_minor: number } | undefined,
  driverAck?: { cash_to_collect_minor: number; commission_charged_minor: number },
) {
  // Q123: the accepting driver sends the numbers its card showed; a different server result is refused, never applied
  return {
    proposal_version_id: versionId,
    expected_listing_terms_version: termsVersion,
    ...(promo ? { promo_consent: promo } : {}),
    ...(driverAck ? { promo_driver_ack: driverAck } : {}),
  };
}

function soumToMinor(value: string): number {
  const parsed = Number(value.replace(/\s/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) * 100 : 0;
}

/**
 * `bookings.rules.STARTED_STATUSES`: once the service has started the fare is due, so the cash record opens.
 * Kept in step with the server set - a narrower list would hide the button in exactly the awkward cases
 * (failed delivery, return) where the two people most need to agree on what was paid.
 */
const CASH_RECORDABLE: Record<string, string[]> = {
  parcel: ["picked_up", "in_transit", "delivered", "delivery_failed", "return_required", "returned", "completed"],
  passenger: ["onboard", "arrived", "completed"],
};

/** The passenger ladder, for a booking this client did not create but a driver may still be carrying. */
const PASSENGER_PROGRESS: Array<[string, string]> = [
  labelledPair("confirmed", "status.confirmed"),
  labelledPair("awaiting_pickup", "app.progress.driverAtStop"),
  labelledPair("onboard", "status.in_transit"),
  labelledPair("completed", "app.progress.completed"),
];

const PARCEL_PROGRESS: Array<[string, string]> = [
  labelledPair("confirmed", "status.confirmed"),
  labelledPair("awaiting_pickup", "app.progress.driverAtStop"),
  labelledPair("picked_up", "app.progress.parcelPickedUp"),
  labelledPair("in_transit", "status.in_transit"),
  labelledPair("delivered", "status.delivered"),
  labelledPair("completed", "app.progress.completed"),
];

/** §17.1: the documents a driver has to upload before staff can verify them. */
const DRIVER_DOCUMENT_TYPES: DriverDocumentType[] = ["passport", "selfie", "license", "car_document", "car_photo"];

/**
 * Product vocabulary, resolved at render time.
 *
 * Each of these was a constant `Record<string, string>` of Uzbek text, which also meant the words were fixed
 * when the module loaded - so a language change could never reach them. Asking the dictionary per call is what
 * makes a screen actually change language, and the `?? value` fallback is exactly what the call sites already
 * did: an unknown code shows as itself rather than as a blank.
 */
function matchLabel(value: string): string {
  return translateDynamic(`match.${value}`) ?? value;
}

function confirmedStopsNote(): string {
  return translate("match.confirmedStopsNote");
}

/** Q98: how many *people* opened this listing. Zero is shown in words, because "0" next to a listing reads
    as a failure to load, while "nobody has looked yet" is the sentence the owner can act on. */
function viewCountLabel(count: number): string {
  return count > 0 ? `${count} ${translate("listing.viewsSuffix")}` : translate("listing.viewsNone");
}

/** Why a suggestion is only a suggestion: the clock or the map. Null when the server gave no reason we
    can put into words - the card then carries the plain "Muqobil" badge and nothing invented. */
function alternativeReasonLabel(reasons: readonly string[]): string | null {
  const reason = alternativeReason(reasons);
  return reason ? translateDynamic(`match.reason.${reason}`) ?? reason : null;
}

function vehicleStatusLabel(value: string): string {
  return translateDynamic(`vehicleStatus.${value}`) ?? value;
}

/** The server takes an amendment only before the service starts (bookings.rules.PRE_SERVICE_STATUSES). */
/** An amount inside a sentence never breaks between its digits ("76 000 so'm" stays one piece). */
function nbsp(text: string): string {
  return text.replace(/ /g, " ");
}

const AMENDABLE_STATUSES = ["confirmed", "awaiting_pickup"];

function proofCodeLabel(value: string): string {
  return translateDynamic(`proofCode.${value}`) ?? value;
}

function trackingWindowText(reason: string): string {
  return translateDynamic(`trackingWindow.${reason}`) ?? translate("error.TRACKING_WINDOW_NOT_OPEN");
}

function trackingFreshnessLabel(value: string): string {
  return translateDynamic(`trackingFreshness.${value}`) ?? value;
}

function proposalStatusLabel(value: string): string {
  return translateDynamic(`proposalStatus.${value}`) ?? value;
}

function disputeTypeLabel(value: string): string {
  return translateDynamic(`disputeType.${value}`) ?? value;
}

/** S9/S10: what a participant can raise, as options for a picker. `commission` is the driver's only (Q16). */
function disputeTypeOptions(side: BookingSide): Array<[string, string]> {
  return disputeTypesFor(side).map((type) => [type, disputeTypeLabel(type)]);
}

/** A reissue refusal as a sentence: the wait the server named, and how many tries are left (Q75). */
function reissueWaitText(wait: { retryAfterS: number; reissuesLeft: number | null }): string {
  const parts = waitParts(wait.retryAfterS);
  const when = parts.hours > 0
    ? translate("reissue.waitHours", { hours: parts.hours, minutes: parts.minutes })
    : translate("reissue.waitMinutes", { minutes: parts.minutes, seconds: parts.seconds });
  return wait.reissuesLeft === null ? when : `${when} ${translate("reissue.left", { count: wait.reissuesLeft })}`;
}

function disputeStatusLabel(value: string): string {
  return translateDynamic(`disputeStatus.${value}`) ?? value;
}

function disputeResolutionLabel(value: string): string {
  return translateDynamic(`disputeResolution.${value}`) ?? value;
}

function tripStatusLabel(value: string): string {
  return translateDynamic(`tripStatus.${value}`) ?? value;
}

function listingStatusLabel(value: string): string {
  return translateDynamic(`listingStatus.${value}`) ?? value;
}

function docTypeLabel(value: string): string {
  return translateDynamic(`docType.${value}`) ?? value;
}

/** The codes the contract accepts; taken from the generated schema so a renamed code fails the build. */
type QuickReply = NonNullable<ChatMessageCreate["quick_reply_code"]>;

/** §16: a quick reply is a fixed sentence both sides can read; the code is what travels, not the text. */
function quickReplyLabel(code: string): string {
  return translateDynamic(`quickReply.${code}`) ?? code;
}

/**
 * The quick replies worth offering in a *booking* chat, per side.
 *
 * `price_agreed` is left out on purpose. The booking exists because a price was already accepted, so a
 * button that re-agrees to it only invites the haggling the proposal flow is there to hold - and a quick
 * reply can never change agreed terms anyway (§16), so it would be a button that means nothing.
 */
function quickRepliesFor(side: "client" | "driver"): QuickReply[] {
  return side === "driver"
    ? ["arriving_in_5_min", "at_stop", "clarify_stop"]
    : ["at_stop", "clarify_stop"];
}

/** What has to be in the frame for this slot, so "Pasport" is not the only thing the driver has to go on. */
function docTypeHint(value: string): string {
  return translateDynamic(`docHint.${value}`) ?? "";
}

/** U6: the trust *group* behind a competing offer. Never rendered without its count - "Yangi haydovchi" with
    zero ratings is the truth about a new driver, an invented 4.5 is not (§8.2). */
function ratingBucketLabel(value: string | null | undefined): string | null {
  return value ? translateDynamic(`ratingBucket.${value}`) ?? value : null;
}

/** The coarse class the server derives from the seat count; never the make or model (Q43). */
function vehicleClassLabel(value: string): string {
  return translateDynamic(`vehicleClass.${value}`) ?? value;
}

/** T9: the driver's next trip command, and the words for it. */
function tripNextAction(status: string): [string, string] | undefined {
  const action: Record<string, "start_boarding" | "depart" | "complete"> = {
    planned: "start_boarding",
    boarding: "depart",
    in_progress: "complete",
  };
  const next = action[status];
  return next ? [next, translate(`tripAction.${next}`)] : undefined;
}

function cityName(city: unknown): string {
  if (!city) return "-";
  if (typeof city === "string") return city;
  if (typeof city === "object" && "name_uz" in city) return String((city as City).name_uz);
  return "-";
}

function districtName(district: unknown): string | null {
  if (!district) return null;
  if (typeof district === "string") return district;
  if (typeof district === "object" && "name_uz" in district) return String((district as District).name_uz);
  return null;
}

/**
 * The catalogue district whose centre is closest to a coordinate.
 *
 * Plain great-circle distance over the centres - the catalogue has no boundaries for most districts, so this
 * is the honest approximation and it is used for one thing only: pre-filling the direction after the person
 * pressed "locate". The point that is stored is always their own coordinate, never the district's centre.
 */
function nearestDistrict(districts: DistrictDTO[], point: { lat: number; lng: number }): DistrictDTO | null {
  let best: DistrictDTO | null = null;
  let bestKm = Infinity;
  for (const district of districts) {
    if (district.center_lat == null || district.center_lng == null) continue;
    const km = haversineKm(point, { lat: Number(district.center_lat), lng: Number(district.center_lng) });
    if (km < bestKm) {
      bestKm = km;
      best = district;
    }
  }
  return best;
}

/** `datetime-local` wants local wall-clock text, and this is "now" in exactly that shape. */
function localNowInputValue(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

/**
 * A departure window worth suggesting: tomorrow morning, open for the working day.
 *
 * Typing a date into `datetime-local` by hand is where this screen lost people - a half-typed value reads
 * as empty and "31.11" is not a date at all. A suggestion that is obviously editable removes the step
 * without deciding anything: the person still sets the window they want, and the server still checks it.
 */
function suggestedDepartureWindow(): { start: string; end: string } {
  const start = new Date();
  start.setDate(start.getDate() + 1);
  start.setHours(9, 0, 0, 0);
  const end = new Date(start);
  end.setHours(18, 0, 0, 0);
  const asInput = (value: Date) =>
    new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  return { start: asInput(start), end: asInput(end) };
}

/** Distance for a person, not for a log: whole kilometres, and metres only when it is under one. */
function formatKm(metres: number): string {
  if (!Number.isFinite(metres) || metres <= 0) return translate("app.distance.km", { value: 0 });
  return metres < 1000
    ? translate("app.distance.m", { value: Math.round(metres) })
    : translate("app.distance.km", { value: Math.round(metres / 1000) });
}

/**
 * Driving time as "4 soat 10 daqiqa".
 *
 * Rounded to five minutes, because the underlying number is a routing estimate over a synthetic geometry
 * and a minute-precise figure would claim an accuracy it does not have.
 */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "-";
  const rounded = Math.round(seconds / 300) * 300;
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.round((rounded % 3600) / 60);
  if (hours && minutes) return translate("app.duration.hoursMinutes", { hours, minutes });
  if (hours) return translate("app.duration.hours", { hours });
  return translate("app.duration.minutes", { minutes: Math.max(5, minutes) });
}

/**
 * The address without its leading country part.
 *
 * Yandex writes "Oʻzbekiston, Toshkent, Mirzo Ulugʻbek tumani, ...". The country is the one thing everyone
 * on this screen already knows, and it was crowding out the part that identifies the place.
 */
function withoutCountry(address: string): string {
  const parts = address.split(",").map((part) => part.trim()).filter(Boolean);
  const first = (parts[0] ?? "").toLowerCase().replace(/[ʻ'’`]/g, "'");
  if (first === "o'zbekiston" || first === "uzbekistan" || first === "узбекистан") parts.shift();
  return parts.join(", ");
}

/** A marked place the geocoder could not name still has coordinates, and those are exactly as true. */
function coordinateLabel(lat: number, lng: number): string {
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

function haversineKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const radiusKm = 6371;
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * radiusKm * Math.asin(Math.sqrt(h));
}

function districtCenter(district: District | null | undefined): { lat: number; lng: number } | null {
  const lat = district?.center_lat === null || district?.center_lat === undefined ? NaN : Number(district.center_lat);
  const lng = district?.center_lng === null || district?.center_lng === undefined ? NaN : Number(district.center_lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng };
}

function nullableNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

/** The label a commission bar sits under: a day inside a week, a month inside half a year. */
function incomeBucketKey(at: Date, period: "daily" | "monthly"): string {
  return period === "daily"
    ? at.toLocaleDateString("uz-UZ", { day: "2-digit", month: "short" })
    : at.toLocaleDateString("uz-UZ", { month: "short" });
}

function shortDate(value?: string): string {
  if (!value) return "";
  return new Date(value).toLocaleDateString("uz-UZ", { day: "2-digit", month: "short" });
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("uz-UZ", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toLocalDateTimeInputValue(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function moneyNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

/**
 * When this trip can be at the request's pickup stop, inside the window the client asked for.
 *
 * The trip's planned arrival is the honest anchor: the driver offers the half hour around it, not the client's
 * whole window. `null` means the trip simply does not serve that stop in time, and nothing is offered.
 */
function proposalPickupWindow(
  trip: TripDTO | undefined,
  request: FeedItemDTO,
): { start: string; end: string } | null {
  if (!trip) return null;
  // Q88: a point-ended request has no stop to anchor on. The server derives the window from the projection
  // when the proposal is sent, so the screen simply offers the client's own window and lets the server refuse.
  const originStopId = request.listing.origin_stop?.id;
  if (!originStopId) {
    return { start: request.listing.departure_window_start, end: request.listing.departure_window_end };
  }
  const at = trip.stops.find((stop) => stop.stop.id === originStopId);
  if (!at) return null;
  const arrival = new Date(at.eta_arrival_at ?? at.planned_arrival_at).getTime();
  const askedFrom = new Date(request.listing.departure_window_start).getTime();
  const askedTo = new Date(request.listing.departure_window_end).getTime();
  const start = Math.max(askedFrom, arrival - 30 * 60 * 1000);
  const end = Math.min(askedTo, arrival + 30 * 60 * 1000);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return { start: new Date(start).toISOString(), end: new Date(end).toISOString() };
}

/**
 * The departure window a driver's trip offer advertises for one of its stops.
 *
 * The anchor is the same one the driver's own proposals use: when the car is planned to be at that stop, plus
 * or minus half an hour. That is not a cosmetic choice - a client answering this offer sends exactly this
 * window back, and the server checks it against the trip's real ETA at that stop. An invented window would be
 * published and then refused at the first proposal.
 */
function offerWindowForTrip(trip: TripDTO | undefined, originStopId: string): { start: string; end: string } | null {
  const at = trip?.stops.find((stop) => stop.stop.id === originStopId);
  if (!at) return null;
  const arrival = new Date(at.eta_arrival_at ?? at.planned_arrival_at).getTime();
  if (!Number.isFinite(arrival)) return null;
  return {
    start: new Date(arrival - 30 * 60 * 1000).toISOString(),
    end: new Date(arrival + 30 * 60 * 1000).toISOString(),
  };
}

function StatusTimeline({ status }: { status: OrderStatus }) {
  const steps: { status: OrderStatus; label: string }[] = [
    { status: "published", label: translate("app.orderStatus.published") },
    { status: "bidding", label: translate("status.bidding") },
    { status: "accepted", label: translate("app.orderStatus.accepted") },
    { status: "picked_up", label: translate("status.picked_up") },
    { status: "in_transit", label: translate("status.in_transit") },
    { status: "delivered", label: translate("status.delivered") },
    { status: "confirmed", label: translate("status.confirmed") },
  ];
  const index = steps.findIndex((step) => step.status === status);
  const activeIndex = index >= 0 ? index : 0;
  // The same caravan thread as the direction picker, now carrying progress: a bead per stage, the current one
  // a pulsing azure ring, the last one the seal. A column of identical dots said nothing about where the
  // parcel actually is.
  return (
    <div className="rounded-[14px] border border-border bg-card p-4">
      <p className="mb-3 text-[13px] font-semibold text-foreground">{translate("app.orderStatus.title")}</p>
      <JourneySpine steps={steps.map((step) => ({ key: step.status, label: step.label }))} current={activeIndex} />
    </div>
  );
}

function CitySelect(props: { label: string; cities: City[]; value: number; onChange: (value: number) => void }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[14px] font-medium text-secondary-foreground">{props.label}</span>
      <select
        value={props.value || ""}
        onChange={(event) => props.onChange(Number(event.target.value))}
        className="h-[52px] rounded-[12px] border border-border bg-card px-4 text-[15px] text-foreground outline-none"
      >
        <option value="">{translate("app.citySelect.placeholder")}</option>
        {props.cities.map((city) => (
          <option key={city.id} value={city.id}>
            {city.name_uz}
          </option>
        ))}
      </select>
    </label>
  );
}

function PickSelect(props: {
  label: string;
  value: string;
  placeholder: string;
  options: Array<[string, string]>;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[14px] font-medium text-secondary-foreground">{props.label}</span>
      <select
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
        className="h-[52px] rounded-[12px] border border-border bg-card px-4 text-[15px] text-foreground outline-none disabled:bg-muted"
      >
        <option value="">{props.placeholder}</option>
        {props.options.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * The beaded segment that joins the two ends of a direction.
 *
 * Ported from the reference client's caravan thread: the two places a person picks are one journey, and two
 * unconnected rows with a grey rule between them say the opposite. The bead column is centred on the node
 * column of the rows above and below it, so the line reads as continuous.
 */
function DirectionLink() {
  return (
    <div className="flex items-stretch" aria-hidden="true">
      <span className="flex w-[60px] shrink-0 justify-center">
        <span
          className="w-0.5"
          style={{
            minHeight: 18,
            background: "repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 8px)",
            opacity: 0.65,
          }}
        />
      </span>
      <span className="flex-1 self-center border-t border-border" />
    </div>
  );
}

/**
 * One end of a direction.
 *
 * `node` decides the marker, and the two are deliberately different shapes rather than two colours of the
 * same circle: the origin is a hollow azure ring, the destination a filled seal with one sharp corner
 * pointing at the place. That difference survives greyscale and a glance.
 */
function LocationPointRow(props: {
  label: string;
  address: string;
  /**
   * What to show on the bold line instead of the address's own first part.
   *
   * A Yandex address starts with the country, so every row read "Oʻzbekiston" - the same word twice, above
   * the one piece of information the row exists to carry. The chosen region is what belongs there.
   */
  title?: string;
  hasPoint: boolean;
  onClick: () => void;
  node: "origin" | "destination";
}) {
  const title = props.title || formatAddressTitle(props.address);
  // With an explicit title the whole address is detail; without one, the first part is already the title.
  const region = props.title ? withoutCountry(props.address) : formatAddressRegion(props.address);
  const marked = props.hasPoint;

  return (
    <button
      type="button"
      onClick={props.onClick}
      className="el-press flex min-h-[64px] w-full items-center gap-3 bg-card px-4 py-3.5 text-left"
    >
      <span className="flex w-11 shrink-0 justify-center">
        {props.node === "origin" ? (
          <span
            className="h-4 w-4 rounded-full border-[3px]"
            style={{
              borderColor: marked ? "var(--feruza)" : "color-mix(in srgb, var(--foreground) 22%, var(--background))",
              background: "var(--card)",
              boxShadow: marked ? "0 0 0 4px color-mix(in srgb, var(--feruza) 14%, transparent)" : "none",
            }}
          />
        ) : (
          <span
            className="h-[18px] w-[18px]"
            style={{
              background: marked ? "var(--primary)" : "var(--card)",
              border: marked ? "none" : "2px solid color-mix(in srgb, var(--foreground) 22%, var(--background))",
              borderRadius: "50% 50% 50% 3px",
              transform: "rotate(45deg)",
              boxShadow: marked ? "0 0 0 4px color-mix(in srgb, var(--primary) 16%, transparent)" : "none",
            }}
          />
        )}
      </span>
      {/* Two lines at most, and the second only when it says something. An empty row asks its question and
          stops - "Joyni belgilang, manzil avtomatik yoziladi" under every unfilled row was three lines of
          instruction repeated twice on one screen. */}
      <span className="min-w-0 flex-1">
        <span
          className={cls(
            "block break-words text-[16px] leading-6",
            marked ? "font-semibold text-foreground" : "font-medium text-muted-foreground",
          )}
        >
          {title || props.label}
        </span>
        {marked && region && <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">{region}</span>}
      </span>
      <ChevronRight size={18} className="shrink-0 text-muted-foreground" />
    </button>
  );
}

function LocationSelectorRow(props: { city: City; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="el-press flex min-h-[70px] w-full items-center gap-3 border-b border-border px-5 text-left last:border-b-0"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <MapPin size={20} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[16px] font-semibold text-foreground">{props.city.name_uz}</span>
        <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">{props.city.region}</span>
      </span>
      <ChevronRight size={19} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
    </button>
  );
}

function DistrictSelectorRow(props: { district: District; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="el-press flex min-h-[64px] w-full items-center gap-3 border-b border-border px-5 text-left last:border-b-0"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent text-primary">
        <MapPin size={19} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[16px] font-semibold text-foreground">{props.district.name_uz}</span>
        {props.district.name_ru && <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">{props.district.name_ru}</span>}
      </span>
      <ChevronRight size={19} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
    </button>
  );
}

function RouteSummaryRow(props: {
  label: string;
  address: string;
  /** Shown when the geocoder had no name for the place: the coordinates, which are exactly as true. */
  fallback?: string;
  city?: string;
  district?: string | null;
  onEdit: () => void;
  icon: ElementType;
}) {
  const Icon = props.icon;
  const title = formatAddressTitle(props.address) || props.fallback;
  const region = formatAddressRegion(props.address) || props.city;

  return (
    <div className="flex gap-3 border-b border-border px-4 py-4 last:border-b-0">
      <span className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-foreground">
        <Icon size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-muted-foreground">{props.label}</p>
        <p className="mt-1 break-words text-[16px] font-semibold leading-6 text-foreground">
          {title || translate("app.route.noAddress")}
        </p>
        <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{[region, props.district].filter(Boolean).join(" / ") || "-"}</p>
      </div>
      <button
        type="button"
        onClick={props.onEdit}
        className="el-press h-9 shrink-0 rounded-full bg-muted px-3 text-[13px] font-semibold text-secondary-foreground"
      >
        {translate("app.route.change")}
      </button>
    </div>
  );
}

function OrderCard({ order, onClick }: { order: ClientOrder | DriverFeedOrder; onClick?: () => void }) {
  const fromDistrictLabel = districtName("from_district" in order ? order.from_district : undefined);
  const toDistrictLabel = districtName("to_district" in order ? order.to_district : undefined);
  return (
    <button onClick={onClick} className="el-press w-full rounded-[16px] border border-border bg-card p-4 text-left">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
          <MapPin size={14} color="var(--primary)" />
          {[cityName(order.from_city), fromDistrictLabel].filter(Boolean).join(", ")} {"->"} {[cityName(order.to_city), toDistrictLabel].filter(Boolean).join(", ")}
        </span>
        <StatusBadge status={order.status} />
      </div>
      <div className="flex items-center justify-between text-[13px] text-muted-foreground">
        <span>{shortDate(order.created_at)}</span>
        <span className="font-semibold text-foreground">{formatUzs(("final_price" in order ? order.final_price : null) ?? order.suggested_price)}</span>
      </div>
      {"bids_count" in order && (
        <p className="mt-2 text-[12px] text-muted-foreground">{translate("app.orderCard.bids", { count: order.bids_count ?? 0 })}</p>
      )}
    </button>
  );
}

/**
 * A private upload the server said this viewer may see (`MediaRefDTO`).
 *
 * The link is short-lived and the bucket is not public, so three things matter here: the image is never
 * addressed by its storage key, an expired or broken link offers a retry that re-reads the resource (which
 * mints a fresh URL), and a missing photo is shown as a plain note rather than a broken frame.
 */
function ParcelPhoto({
  photo,
  label,
  onRefresh,
}: {
  photo: MediaRefDTO | null | undefined;
  label: string;
  onRefresh: () => void;
}) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const [full, setFull] = useState(false);
  // One automatic re-read per link. A client clock running ahead would otherwise ask for a fresh URL, get one
  // it still considers expired, and loop.
  const refreshedFor = useRef<string | null>(null);

  useEffect(() => {
    setState("loading");
  }, [photo?.url]);

  // A link that has already expired never loads: re-read before showing a broken frame.
  useEffect(() => {
    if (!photo) return;
    const remaining = new Date(photo.expires_at).getTime() - Date.now();
    if (remaining <= 0) {
      if (refreshedFor.current !== photo.url) {
        refreshedFor.current = photo.url;
        onRefresh();
      }
      return;
    }
    const timer = window.setTimeout(() => {
      refreshedFor.current = photo.url;
      onRefresh();
    }, Math.min(remaining, 2_147_483_000));
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photo?.url, photo?.expires_at]);

  return (
    <div className="rounded-[14px] border border-border bg-card p-4">
      <p className="text-[12px] text-muted-foreground">{label}</p>
      {!photo ? (
        <p className="mt-1 text-[14px] font-medium text-foreground">{translate("app.photo.none")}</p>
      ) : (
        <>
          <button
            type="button"
            onClick={() => state === "ready" && setFull(true)}
            className="el-press relative mt-2 block h-[180px] w-full overflow-hidden rounded-[12px] bg-muted"
            aria-label={translate("app.photo.zoom")}
          >
            {state !== "ready" && (
              <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[13px] text-muted-foreground">
                <Package size={26} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
                {state === "loading" ? translate("app.photo.loading") : translate("app.photo.failed")}
              </span>
            )}
            <img
              src={photo.url}
              alt={translate("app.photo.alt")}
              onLoad={() => setState("ready")}
              onError={() => setState("failed")}
              className={cls("h-full w-full object-cover", state === "ready" ? "opacity-100" : "opacity-0")}
            />
          </button>
          {state === "failed" && (
            <button
              type="button"
              onClick={onRefresh}
              className="el-press mt-2 h-10 w-full rounded-[10px] bg-accent text-[14px] font-semibold text-primary"
            >
              {translate("app.photo.reload")}
            </button>
          )}
        </>
      )}
      {full && photo && (
        <div
          role="presentation"
          onClick={() => setFull(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
        >
          <img src={photo.url} alt={translate("app.photo.alt")} className="max-h-full max-w-full object-contain" />
          <button
            type="button"
            onClick={() => setFull(false)}
            aria-label={translate("common.close")}
            className="el-press absolute right-5 top-5 flex h-10 w-10 items-center justify-center rounded-full bg-card/90"
          >
            <X size={20} />
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * "Naqd to'lov qaydi" - a record that cash changed hands between two people, not a payment ELCHI took.
 *
 * The pilot's fare is paid in cash directly to the driver (§9): nothing here moves a balance, the amount is the
 * agreed fare, and the wording never claims that ELCHI received or settled anything. One side records the
 * handover, the other confirms it or contests it, and a contested one goes to the operator queue (Q78).
 */
function CashAcknowledgement({
  booking,
  side,
  busy,
  amount,
  onAmountChange,
  onReport,
  onDecide,
}: {
  booking: { cash_status: string; total_minor: number; currency: string; version: number; cash_receipt?: CashReceiptDTO | null;
    promo?: Parameters<typeof cashDueMinor>[0]["promo"] };
  side: "client" | "driver";
  busy: boolean;
  amount: string;
  onAmountChange: (value: string) => void;
  onReport: () => void;
  onDecide: (decision: "acknowledge" | "contest") => void;
}) {
  const receipt = booking.cash_receipt ?? null;
  const mineAlready = receipt !== null && receipt.reported_by_side === side;
  return (
    <div className="rounded-[16px] border border-border bg-card p-4">
      <p className="text-[15px] font-semibold text-foreground">{translate("app.cash.title")}</p>
      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
        {translate("app.cash.explainer")}
      </p>
      <p className="mt-2 text-[13px] text-muted-foreground">
        {booking.promo ? translate("app.cash.dueLabel") : translate("app.cash.agreedLabel")}:{" "}
        <span className="font-semibold text-foreground">{formatUzs(cashDueMinor(booking) / 100)}</span>
      </p>

      {booking.cash_status === "unpaid" && (
        <div className="mt-3 space-y-3">
          <Field
            label={side === "driver" ? translate("app.cash.receivedField") : translate("app.cash.givenField")}
            type="number"
            value={amount}
            placeholder={String(Math.round(cashDueMinor(booking) / 100))}
            onChange={onAmountChange}
          />
          <PrimaryButton disabled={busy || !Number(amount)} onClick={onReport}>
            {side === "driver" ? translate("app.cash.markReceived") : translate("app.cash.markGiven")}
          </PrimaryButton>
        </div>
      )}

      {booking.cash_status === "reported_paid" && receipt && (
        <div className="mt-3">
          <p className="text-[13px] text-secondary-foreground">
            {translate(mineAlready ? "app.cash.reportedByMe" : "app.cash.reportedByOther", {
              amount: formatUzs(receipt.amount_minor / 100),
              date: formatDateTime(receipt.reported_at),
            })}
          </p>
          {mineAlready ? (
            <p className="mt-2 text-[12px] leading-5 text-muted-foreground">{translate("app.cash.awaitingOther")}</p>
          ) : (
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => onDecide("acknowledge")}
                className="el-press h-11 flex-1 rounded-[12px] bg-primary text-[14px] font-semibold text-primary-foreground disabled:bg-slate-400"
              >
                {translate("app.cash.acknowledge")}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => onDecide("contest")}
                className="el-press h-11 flex-1 rounded-[12px] bg-destructive/10 text-[14px] font-semibold text-destructive"
              >
                {translate("app.cash.contest")}
              </button>
            </div>
          )}
        </div>
      )}

      {booking.cash_status === "acknowledged" && (
        <p className="mt-3 text-[13px] font-semibold text-success">{translate("app.cash.bothConfirmed")}</p>
      )}
      {booking.cash_status === "contested" && (
        <p className="mt-3 text-[13px] font-semibold text-destructive">
          {translate("app.cash.contested")}
        </p>
      )}
    </div>
  );
}

/**
 * What to call one end of a direction (Q88).
 *
 * An end is either a verified stop or a place the client marked on the map, never both. The reverse-geocoded
 * address is the friendlier name for a marked place, so it wins when there is one; a district is the fallback
 * because "Samarqand (fixture)" still tells the person where this is, and a bare coordinate does not.
 */
/**
 * What a list shows while its answer is still in flight.
 *
 * Before this, a loading list rendered its empty state - the screen said "there are no offers yet" about an
 * answer it had not received. Three placeholder cards say the honest thing instead: something is coming, and
 * this is the shape it will have.
 */
function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: rows }).map((_, index) => (
        <SkeletonCard key={index} />
      ))}
    </div>
  );
}

/** The name a driver saved a direction end by - never the opaque id the API returns. */
function savedEndLabel(districtId: string | null | undefined, stopId: string | null | undefined, names: Record<string, string>): string {
  if (districtId) return names[districtId] ?? translate("app.savedEnd.district");
  if (stopId) return translate("app.savedEnd.stop");
  return "-";
}

function endLabel(
  stop: StopRefDTO | null | undefined,
  point: MapPointDTO | null | undefined,
  fallback = translate("app.endLabel.mapPlace"),
): string {
  if (stop) return stop.name_uz;
  if (!point) return fallback;
  return point.address?.trim() || point.district?.name_uz || fallback;
}

/** `Olib ketish bekati` reads wrong for a marked place; the row says what the end actually is. */
function endRowLabel(stop: StopRefDTO | null | undefined, stopWord: string, pointWord: string): string {
  return stop ? stopWord : pointWord;
}

/**
 * The one place that says why a driver cannot take work yet, and what to do about it (D16, §17.1).
 *
 * `rejected` and `blocked` are not "keep waiting" - nothing the driver uploads changes them, so those two
 * send the person to support instead of back to the upload screen.
 */
function DriverVerificationGate({
  status,
  onProfile,
  onDocuments,
  onSupport,
}: {
  status: string | undefined;
  onProfile: () => void;
  onDocuments: () => void;
  onSupport: () => void;
}) {
  const decided = status === "rejected" || status === "blocked";
  return (
    <div className="rounded-[16px] border border-warning/40 bg-warning/10 p-4">
      <p className="text-[15px] font-semibold text-foreground">{translate("app.driverGate.title")}</p>
      <p className="mt-1 text-[13px] text-muted-foreground">
        {translate("app.driverGate.status", {
          status: driverVerificationLabels[status ?? "new"] ?? status ?? translate("app.driverVerification.new"),
        })}
      </p>
      <p className="mt-2 text-[13px] leading-6 text-muted-foreground">
        {decided
          ? translate("app.driverGate.decided")
          : translate("app.driverGate.pending")}
      </p>
      <div className="mt-3 space-y-2">
        {decided ? (
          <PrimaryButton onClick={onSupport}>{translate("app.driverGate.support")}</PrimaryButton>
        ) : (
          <>
            <PrimaryButton onClick={onDocuments}>{translate("app.driverGate.documents")}</PrimaryButton>
            <SecondaryButton onClick={onProfile}>{translate("app.driverGate.profile")}</SecondaryButton>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Q40 / ADR-0019: the open board of what the other drivers are currently asking for this request.
 *
 * ELCHI is a two-sided auction (Q90), and an auction only finds a price when the bidders can see the book.
 * Without this panel every driver bids into the dark: the cheap offer nobody can undercut and the expensive
 * one nobody can beat both look the same from the inside. So the board is shown on the bid screen itself,
 * next to the field where the number is typed.
 *
 * Everything here is what the server already anonymised: a label that is stable inside this listing but is
 * not derived from any id, the price, the pickup window, the coarse vehicle class, the seat count and the
 * trust bucket with its count. No name, photo, plate, phone or make/model ever reaches this component - the
 * DTO has no field to carry them (R2, Q43).
 */
function RivalOfferBoard({ offers, unavailable }: { offers: ListingOfferDTO[]; unavailable: boolean }) {
  if (unavailable) return null;
  const rivals = offers.filter((offer) => !offer.is_mine);
  const mine = offers.find((offer) => offer.is_mine);
  // Cheapest first: that is the number a new bid actually has to answer.
  const sorted = [...rivals].sort((a, b) => a.total_minor - b.total_minor);
  return (
    <div className="rounded-[14px] border border-border bg-background p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[14px] font-semibold text-foreground">{translate("app.rivalBoard.title")}</p>
        <span className="text-[12px] text-muted-foreground">{translate("app.rivalBoard.count", { count: rivals.length })}</span>
      </div>
      {sorted.length === 0 ? (
        <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
          {translate("app.rivalBoard.empty")}
        </p>
      ) : (
        <>
          <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
            {translate("app.rivalBoard.cheapest")}{" "}<span className="font-semibold text-foreground">{formatUzs(sorted[0].total_minor / 100)}</span>
          </p>
          <ul className="mt-3 space-y-2">
            {sorted.map((offer) => {
              const bucket = ratingBucketLabel(offer.rating_bucket);
              return (
                <li key={`${offer.label}-${offer.revision}`} className="rounded-[12px] bg-card p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-semibold text-foreground">{offer.label}</p>
                      <p className="mt-0.5 text-[12px] text-muted-foreground">
                        {translate("app.rivalBoard.vehicleSeats", {
                          vehicle: vehicleClassLabel(offer.vehicle_class),
                          seats: offer.seat_capacity,
                        })}
                      </p>
                      <p className="mt-0.5 text-[12px] text-muted-foreground">
                        {shortDate(offer.pickup_window_start)} - {shortDate(offer.pickup_window_end)}
                      </p>
                      {bucket && (
                        // U6: the group and the count are one sentence; the count alone says how much it is worth.
                        <p className="mt-0.5 text-[12px] text-muted-foreground">
                          {translate("app.rivalBoard.ratings", { bucket, count: offer.rating_count })}
                        </p>
                      )}
                      {offer.response_pending && (
                        <p className="mt-0.5 text-[12px] text-warning">{translate("app.rivalBoard.countered")}</p>
                      )}
                    </div>
                    <span className="shrink-0 text-[15px] font-bold text-primary">
                      {formatUzs(offer.total_minor / 100)}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {mine && (
        <p className="mt-3 rounded-[12px] bg-accent px-3 py-2 text-[12px] leading-5 text-primary">
          {translate("app.rivalBoard.mine", { price: formatUzs(mine.total_minor / 100) })}
        </p>
      )}
    </div>
  );
}

function ListingCard({ listing, onClick }: { listing: ListingDTO; onClick?: () => void }) {
  return (
    <button onClick={onClick} className="el-press w-full rounded-[16px] border border-border bg-card p-4 text-left">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
          <MapPin size={14} color="var(--primary)" />
          {endLabel(listing.origin_stop, listing.origin_point)} {"->"} {endLabel(listing.destination_stop, listing.destination_point)}
        </span>
        <StatusBadge status={listing.status} />
      </div>
      <div className="flex items-center justify-between text-[13px] text-muted-foreground">
        <span>{shortDate(listing.departure_window_start)}</span>
        <span>{viewCountLabel(listing.view_count)}</span>
        <span className="font-semibold text-foreground">{formatUzs(listing.total_minor / 100)}</span>
      </div>
    </button>
  );
}

function BottomNav({
  role,
  active,
  go,
  unread = 0,
}: {
  role: MobileRole;
  active: Screen;
  go: (screen: Screen) => void;
  /** Unread inbox items, shown as a dot on the bell. In-app is the only channel (Q82), so it has to be seen. */
  unread?: number;
}) {
  const tabs =
    role === "client"
      ? [
          ["client-home", Home, translate("app.nav.home")],
          ["client-orders", Package, translate("app.nav.orders")],
          ["client-notifications", Bell, translate("app.nav.messages")],
          ["client-profile", User, translate("app.nav.profile")],
        ]
      : [
          ["driver-home", Home, translate("app.nav.home")],
          ["driver-routes", Navigation, translate("app.nav.routes")],
          ["driver-feed", Package, translate("app.nav.matches")],
          ["driver-orders", Package, translate("app.nav.orders")],
          ["driver-profile", User, translate("app.nav.profile")],
        ];
  return (
    <nav className="flex h-[72px] shrink-0 border-t border-border bg-card">
      {tabs.map(([id, Icon, label]) => (
        <button key={id as string} onClick={() => go(id as Screen)} className="el-press relative flex flex-1 flex-col items-center justify-center gap-1">
          {Icon === Bell && unread > 0 && (
            <span className="absolute right-[calc(50%-16px)] top-3 h-2 w-2 rounded-full bg-destructive" aria-hidden="true" />
          )}
          <Icon size={22} color={active === id ? "var(--primary)" : "color-mix(in srgb, var(--foreground) 42%, var(--background))"} />
          <span className={cls("text-[10px] font-medium", active === id ? "text-primary" : "text-slate-400")}>{label as string}</span>
        </button>
      ))}
    </nav>
  );
}

export function ConnectedApp() {
  const auth = useAuth();
  // Subscribing re-renders every screen in the chosen language; the text itself is looked up at render time.
  const [locale, setLocale] = useLocale();
  const [screen, setScreen] = useState<Screen>("splash");
  const [selectedRole, setSelectedRole] = useState<MobileRole>("client");
  const [phone, setPhone] = useState("+998");
  const [otp, setOtp] = useState("");
  const [resendIn, setResendIn] = useState(RESEND_SECONDS);
  const [supportInfo, setSupportInfo] = useState<SupportContactsDTO | null>(null);
  const [supportTickets, setSupportTickets] = useState<SupportTicketDTO[]>([]);
  const [supportMessage, setSupportMessage] = useState("");
  const [incomePeriod, setIncomePeriod] = useState<"daily" | "monthly">("daily");
  const [onboardingStep, setOnboardingStep] = useState(0);
  const [cities, setCities] = useState<City[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [orderForm, setOrderForm] = useState<CreateOrderPayload>(emptyOrder);
  const [selectedFromCity, setSelectedFromCity] = useState<City | null>(null);
  const [selectedToCity, setSelectedToCity] = useState<City | null>(null);
  const [selectedFromDistrict, setSelectedFromDistrict] = useState<District | null>(null);
  const [selectedToDistrict, setSelectedToDistrict] = useState<District | null>(null);
  // Stage-2 direction: the same two rows on the home sheet, now on the geo catalogue.
  const [pickupEnd, setPickupEnd] = useState<DirectionEnd>(emptyDirectionEnd);
  const [dropoffEnd, setDropoffEnd] = useState<DirectionEnd>(emptyDirectionEnd);
  const [routeVersion, setRouteVersion] = useState<RouteVersionDTO | null>(null);
  const [routeDistricts, setRouteDistricts] = useState<CorridorDistrictDTO[]>([]);
  const [corridorStops, setCorridorStops] = useState<StopDTO[]>([]);
  /** Verified stops for the end being marked, offered on the map as a shortcut (Q88). */
  const [stopOptions, setStopOptions] = useState<StopOption[]>([]);
  const [listingForm, setListingForm] = useState({
    windowStart: "",
    windowEnd: "",
    unitPrice: "",
    parcelType: "box",
    weightKg: "",
    lengthCm: "",
    widthCm: "",
    heightCm: "",
    senderName: "",
    receiverName: "",
  });
  const [listingWarnings, setListingWarnings] = useState<string[]>([]);
  // Q88/Q89: which service the home sheet is composing, and what the server said about the two marked places.
  const [serviceMode, setServiceMode] = useState<"parcel" | "passenger">("parcel");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  /** Set while the browser is answering the locate button, so the button can say so. */
  const [locating, setLocating] = useState(false);
  const [preview, setPreview] = useState<DirectionPreviewDTO | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  /**
   * Which seats the person marked on the cabin picture. The *count* is what the listing carries
   * (`seat_count`); the seats themselves are how the count is chosen, and `SeatPicker` says so on screen.
   */
  const [selectedSeats, setSelectedSeats] = useState<SeatId[]>(["rear-right"]);
  const seatCount = selectedSeats.length;
  const [myListings, setMyListings] = useState<ListingDTO[]>([]);
  const [proposalTotal, setProposalTotal] = useState(0);
  const [listingDetail, setListingDetail] = useState<ListingDTO | null>(null);
  const [listingThreads, setListingThreads] = useState<ProposalThreadDTO[]>([]);
  // Stage-2 driver side: trips replace the v1 saved routes, and the feed answers on verified stops.
  const [directionOwner, setDirectionOwner] = useState<"client" | "driver">("client");
  const [trips, setTrips] = useState<TripDTO[]>([]);
  const [vehicles, setVehicles] = useState<VehicleDTO[]>([]);
  const [corridors, setCorridors] = useState<CorridorDTO[]>([]);
  const [tripRoutes, setTripRoutes] = useState<RouteVersionDTO[]>([]);
  const [tripForm, setTripForm] = useState({
    vehicleId: "",
    corridorId: "",
    routeId: "",
    startAt: "",
    seats: 4,
    cargoKg: "20",
    cargoLitres: "100",
  });
  const [requestFeed, setRequestFeed] = useState<FeedItemDTO[]>([]);
  /** `meta.match_scope` of the last feed answer - what the matching was actually able to measure. */
  const [matchScope, setMatchScope] = useState<string | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<FeedItemDTO | null>(null);
  const [proposalTripId, setProposalTripId] = useState("");
  /** §17.1: what the driver has already sent per slot, so each row can say where its review stands. */
  const [driverDocuments, setDriverDocuments] = useState<DriverDocument[]>([]);
  /** Q40/ADR-0019: the anonymous board of the other drivers' current offers on the request being bid on.
      An auction the bidders cannot see is a sealed envelope, so this is what makes the price move. */
  const [rivalOffers, setRivalOffers] = useState<ListingOfferDTO[]>([]);
  /** The board is a side panel, not the bid itself: a 404 (flag off, corridor closed) must not block bidding. */
  const [rivalOffersError, setRivalOffersError] = useState(false);
  // Q92: the driver is an author too, not only an answerer. These hold the trip offer being published and the
  // offers already on the market, so a trip card can show what it is advertised as.
  const [driverServiceMode, setDriverServiceMode] = useState<"parcel" | "passenger">("parcel");
  const [myOffers, setMyOffers] = useState<ListingDTO[]>([]);
  const [offerForm, setOfferForm] = useState({
    tripId: "",
    serviceType: "passenger" as "passenger" | "parcel",
    originStopId: "",
    destinationStopId: "",
    price: "",
  });
  // Q92, client side: the driver trip offers this client can answer, and the one they are answering.
  const [offerFeed, setOfferFeed] = useState<FeedItemDTO[]>([]);
  const [selectedOffer, setSelectedOffer] = useState<FeedItemDTO | null>(null);
  const [offerBid, setOfferBid] = useState({
    price: "",
    seats: 1,
    parcelType: "box",
    weightKg: "",
    lengthCm: "",
    widthCm: "",
    heightCm: "",
    receiverName: "",
    receiverPhone: "",
  });
  // ADR-0025: the saved request that fills every driver's offer screen. Private to this account, never published.
  const [activeIntent, setActiveIntent] = useState<TripIntentDTO | null>(null);
  const [myIntents, setMyIntents] = useState<TripIntentDTO[]>([]);
  const [intentLoading, setIntentLoading] = useState(false);
  const [intentError, setIntentError] = useState<string | null>(null);
  const [intentFit, setIntentFit] = useState<TripIntentFitDTO | null>(null);
  const [intentFitLoading, setIntentFitLoading] = useState(false);
  /** "new" makes the route summary start another request; "edit" sends its places into the active one. */
  const [intentDraftMode, setIntentDraftMode] = useState<"new" | "edit">("new");
  /** A material edit waiting for the client to accept that N open offers close (409 TRIP_INTENT_OFFERS_AFFECTED). */
  const [intentEditPending, setIntentEditPending] = useState<
    { body: Record<string, unknown>; openOffers: number; then: Screen } | null
  >(null);
  const [driverBookings, setDriverBookings] = useState<AnyBooking[]>([]);
  const [driverBooking, setDriverBooking] = useState<BookingDTO | null>(null);
  const [proofCode, setProofCode] = useState("");
  const [walletState, setWalletState] = useState<WalletDTO | null>(null);
  const [topups, setTopups] = useState<TopupDTO[]>([]);
  const [topupAmount, setTopupAmount] = useState("");
  const [walletLines, setWalletLines] = useState<LedgerLineDTO[]>([]);
  const [clientBookings, setClientBookings] = useState<AnyBooking[]>([]);
  const [clientBooking, setClientBooking] = useState<BookingClientDTO | null>(null);
  const [bookingCodes, setBookingCodes] = useState<BookingCodesDTO | null>(null);
  // One booking is "open" at a time on the chat/tracking/cash screens; which side is looking decides what the
  // server returns, so the id and the role travel together.
  const [openBooking, setOpenBooking] = useState<{ id: string; side: "client" | "driver" } | null>(null);
  /** B9: the open and settled amendments of the booking on screen, newest first. */
  /** M3: the directions this driver asked to be told about. */
  const [saved, setSaved] = useState<SavedSearchDTO[]>([]);
  const [districtNames, setDistrictNames] = useState<Record<string, string>>({});
  /** M2: what can serve the listing currently open, ranked by the server (§8.2). */
  const [matches, setMatches] = useState<MatchDTO[]>([]);
  const [matchesFor, setMatchesFor] = useState<{ id: string; kind: string } | null>(null);
  /** S6: the note being attached to an open dispute, keyed by dispute id. */
  const [evidenceNote, setEvidenceNote] = useState<{ id: string; note: string } | null>(null);
  const [amendments, setAmendments] = useState<AmendmentDTO[]>([]);
  const [amendmentForm, setAmendmentForm] = useState({ quantity: "", unitPrice: "", reason: "" });
  const [chatMessages, setChatMessages] = useState<ChatMessageDTO[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [chatFailed, setChatFailed] = useState<string | null>(null);
  const [chatWarnings, setChatWarnings] = useState<string[]>([]);
  const [chatHasMore, setChatHasMore] = useState(false);
  /** N6: whether this conversation still takes messages. Null until the screen has asked the server. */
  const [chatState, setChatState] = useState<ChatThreadDTO | null>(null);
  const [tracking, setTracking] = useState<BookingTrackingDTO | null>(null);
  const [trackingError, setTrackingError] = useState("");
  const [cashAmount, setCashAmount] = useState("");
  const [bookingDisputes, setBookingDisputes] = useState<DisputeDTO[]>([]);
  const [disputeType, setDisputeType] = useState("service");
  const [flags, setFlags] = useState<EffectiveFlagsDTO["flags"] | null>(null);
  // One counter form at a time; `pending` is the guard against a second submit of the same revision.
  const [counterFor, setCounterFor] = useState<string | null>(null);
  const [counterPrice, setCounterPrice] = useState("");
  const [counterPending, setCounterPending] = useState(false);
  /** Referral stage 5: the person's explicit bonus choice for the counter / offer being written (never pre-ticked). */
  const [counterConsent, setCounterConsent] = useState<ConsentChoice>(NO_CONSENT);
  const [offerConsent, setOfferConsent] = useState<ConsentChoice>(NO_CONSENT);
  const [consentRefresh, setConsentRefresh] = useState(0);
  const [acceptConsent, setAcceptConsent] = useState<Record<string, ConsentChoice>>({});
  /** A client-authored change to a discounted booking: the server's new numbers, waiting for an explicit yes. */
  const [amendConsentAsk, setAmendConsentAsk] = useState<{ passenger_discount_minor: number; cash_due_minor: number; fare_minor?: number } | null>(null);
  // Q125: the driver's own new cash/commission, shown and confirmed before its change is sent
  const [amendAckAsk, setAmendAckAsk] = useState<{ cash_to_collect_minor: number; commission_charged_minor: number } | null>(null);
  const [myProposals, setMyProposals] = useState<ProposalThreadDTO[]>([]);
  const [orders, setOrders] = useState<ClientOrder[]>([]);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [bids, setBids] = useState<Bid[]>([]);
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [rating, setRating] = useState(5);
  const [ratingComment, setRatingComment] = useState("");
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [disputeReason, setDisputeReason] = useState("Haydovchi kelmadi");
  const [disputeComment, setDisputeComment] = useState("");
  const [clientName, setClientName] = useState("");
  const [driverProfile, setDriverProfile] = useState<DriverProfile | null>(null);
  const [driverForm, setDriverForm] = useState({ full_name: "", car_model: "", car_color: "", plate_number: "" });
  const [driverSeats, setDriverSeats] = useState(4);
  const [driverCargoKg, setDriverCargoKg] = useState("20");
  const [driverCargoLitres, setDriverCargoLitres] = useState("100");
  const [bidPrice, setBidPrice] = useState("");
  const [notifications, setNotifications] = useState<NotificationDTO[]>([]);
  /** B3: the cancel sheet of one booking - which side is asking, and against which version. */
  const [cancelAsk, setCancelAsk] = useState<{ bookingId: string; side: BookingSide; version: number } | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelComment, setCancelComment] = useState("");
  /** A cancel refusal in words (Q7/Q19: a pending no-show review), kept apart from the generic error banner. */
  const [cancelRefusal, setCancelRefusal] = useState<string | null>(null);
  /** B5a: the last reissue answer per code kind - the new code's note, or the server's wait (Q75). */
  const [reissueNotice, setReissueNotice] = useState<{ kind: string; text: string; ok: boolean } | null>(null);
  /** S5: the dispute opened from "Nizolarim". */
  const [disputeDetail, setDisputeDetail] = useState<DisputeDTO | null>(null);
  /** L3: the owner's edit of one listing, and whether the Q20 warning was already shown for it. */
  const [listingEdit, setListingEdit] = useState<
    { listing: ListingDTO; form: ListingEditForm; back: Screen; confirming: boolean; openOffers: number | null } | null
  >(null);
  /** W11: the driver's commission estimate for the bid being typed (driver only, Q16). */
  const [feeQuote, setFeeQuote] = useState<{ quote: CommissionQuoteDTO; totalMinor: number } | null>(null);
  const [feeQuoteFailed, setFeeQuoteFailed] = useState(false);
  const [locationSelectorMode, setLocationSelectorMode] = useState<"pickup" | "dropoff">("pickup");
  const [districtQuery, setDistrictQuery] = useState("");
  const [districtCity, setDistrictCity] = useState<City | null>(null);
  const [districtMode, setDistrictMode] = useState<"client-pickup" | "client-dropoff" | "driver-from" | "driver-to">("client-pickup");
  const [mapPicker, setMapPicker] = useState<"pickup" | "dropoff" | null>(null);
  const [readOnlyMap, setReadOnlyMap] = useState<{
    pickupLat?: number | string | null;
    pickupLng?: number | string | null;
    dropoffLat?: number | string | null;
    dropoffLng?: number | string | null;
    destinationLat?: number | string | null;
    destinationLng?: number | string | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  // The trip the driver opened from "Yo'nalishlarim" (DriverTripDetail loads it itself).
  const [openTripId, setOpenTripId] = useState<string | null>(null);
  // Trip planning: a stop found by name narrows the corridor's routes to the ones through it.
  const [routeStopFilter, setRouteStopFilter] = useState<{ id: string; name: string } | null>(null);

  const go = (next: Screen) => {
    setError("");
    setMessage("");
    setScreen(next);
  };

  /**
   * Referral stage 5: a money-bearing action keeps one Idempotency-Key until it definitively succeeds or fails, so a
   * retry after a timeout, a second tap or reopening the app replays the first answer instead of acting twice.
   */
  async function oncePerAction<T>(scope: string, work: (key: string) => Promise<T>): Promise<T> {
    const key = actionKey(scope, newIdempotencyKey);
    try {
      const result = await work(key);
      finishAction(scope);
      return result;
    } catch (cause) {
      if (!isOffline(cause)) finishAction(scope); // an answer came back: the next try is a new action
      throw cause;
    }
  }

  /** A bonus refusal re-reads the numbers and asks again (Q104): the old tick is not reused. */
  function requoteOn(cause: unknown): void {
    if (needsRequote(cause as { code?: string })) {
      setCounterConsent((choice) => ({ ...choice, useBonus: false }));
      setOfferConsent((choice) => ({ ...choice, useBonus: false }));
      setAcceptConsent({});
      setConsentRefresh((n) => n + 1);
    }
  }

  /** Rethrows after re-asking for the bonus consent when the server refused the numbers (Q104). */
  function requoteAndThrow(cause: unknown): never {
    requoteOn(cause);
    throw cause;
  }

  const run = async (work: () => Promise<void>, success?: string) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
      if (success) setMessage(success);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void getCities({ limit: 100 }).then(setCities).catch(() => setCities([]));
  }, []);

  /**
   * The resend countdown.
   *
   * It only runs while the code screen is open, and it restarts whenever that screen is entered - so coming
   * back after a wrong number does not leave the person staring at a link that is already spent, and leaving
   * the screen does not keep a timer alive behind it.
   */
  useEffect(() => {
    if (screen !== "otp") return;
    setResendIn(RESEND_SECONDS);
  }, [screen]);

  useEffect(() => {
    if (screen !== "otp" || resendIn <= 0) return;
    const id = window.setInterval(() => setResendIn((left) => (left > 0 ? left - 1 : 0)), 1000);
    return () => window.clearInterval(id);
  }, [screen, resendIn]);


  useEffect(() => {
    if (auth.isLoading) return;
    const authScreens = ["splash", "onboarding", "role", "phone", "otp"];
    if (!auth.isAuthenticated) {
      if (!authScreens.includes(screen)) {
        go("role");
      }
      return;
    }
    if (auth.user?.role && !["client", "driver"].includes(auth.user.role)) {
      void run(async () => {
        await auth.logout();
        go("role");
      }, translate("app.toast.roleUnsupported"));
      return;
    }
    if (authScreens.includes(screen)) {
      go(auth.user?.role === "driver" ? "driver-home" : "client-home");
    }
  }, [auth.isAuthenticated, auth.isLoading, auth.user?.role, screen]);

  // ADR-0025: on every sign-in the saved request is re-read for *this* account; nothing of the previous one stays.
  useEffect(() => {
    setActiveIntent(null);
    setMyIntents([]);
    setIntentFit(null);
    setIntentError(null);
    if (auth.user?.role !== "client" || !auth.user?.id) return;
    void loadIntents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.user?.id, auth.user?.role]);

  useEffect(() => {
    if (auth.user?.role !== "client" || !auth.user.phone || orderForm.sender_phone) return;
    setOrderForm((current) => ({ ...current, sender_phone: auth.user?.phone ?? current.sender_phone }));
  }, [auth.user?.phone, auth.user?.role, orderForm.sender_phone]);

  const fromCity = useMemo(
    () => selectedFromCity ?? cities.find((city) => city.id === orderForm.from_city_id),
    [cities, orderForm.from_city_id, selectedFromCity],
  );
  const toCity = useMemo(
    () => selectedToCity ?? cities.find((city) => city.id === orderForm.to_city_id),
    [cities, orderForm.to_city_id, selectedToCity],
  );
  const fromDistrict = useMemo(
    () => selectedFromDistrict ?? districts.find((district) => district.id === orderForm.from_district_id),
    [districts, orderForm.from_district_id, selectedFromDistrict],
  );
  const toDistrict = useMemo(
    () => selectedToDistrict ?? districts.find((district) => district.id === orderForm.to_district_id),
    [districts, orderForm.to_district_id, selectedToDistrict],
  );
  const filteredDistricts = useMemo(() => {
    const query = districtQuery.trim().toLowerCase();
    if (!query) return districts;
    return districts.filter((district) =>
      [district.name_uz, district.name_ru].some((value) => String(value ?? "").toLowerCase().includes(query)),
    );
  }, [districtQuery, districts]);

  function openLocationSelector(mode: "pickup" | "dropoff", owner: "client" | "driver" = "client") {
    setLocationSelectorMode(mode);
    setDirectionOwner(owner);
    go("client-location-selector");
  }

  /**
   * The v2 district catalogue, read once and kept.
   *
   * Two callers need it for the same reason - to name the district a coordinate falls in: the locate button
   * and `markPoint` for a region that has no district step.
   */
  const geoDistrictCache = useRef<DistrictDTO[] | null>(null);
  async function loadGeoDistricts(): Promise<DistrictDTO[]> {
    if (geoDistrictCache.current) return geoDistrictCache.current;
    const rows = await listDistricts({ limit: 500 }).catch(() => [] as DistrictDTO[]);
    if (rows.length) geoDistrictCache.current = rows;
    return rows;
  }

  const activeEnd = locationSelectorMode === "pickup" ? pickupEnd : dropoffEnd;
  const otherEnd = locationSelectorMode === "pickup" ? dropoffEnd : pickupEnd;

  function applyEnd(end: DirectionEnd) {
    if (locationSelectorMode === "pickup") {
      setPickupEnd(end);
      setOrderForm((current) => ({
        ...current,
        pickup_address: end.stop || end.point ? directionEndLabel(end) : "",
        pickup_lat: end.point?.lat ?? end.stop?.point.lat ?? null,
        pickup_lng: end.point?.lng ?? end.stop?.point.lng ?? null,
      }));
    } else {
      setDropoffEnd(end);
      setOrderForm((current) => ({
        ...current,
        dropoff_address: end.stop || end.point ? directionEndLabel(end) : "",
        dropoff_lat: end.point?.lat ?? end.stop?.point.lat ?? null,
        dropoff_lng: end.point?.lng ?? end.stop?.point.lng ?? null,
      }));
    }
  }

  /**
   * Step 1: the region.
   *
   * Tashkent city is its own unit (wave 10), so `requires_district` decides whether step 2 is asked at all -
   * and when it is not, the next screen is the **map**, not a list of stops. Sending a person who chose
   * "Toshkent shahri" to a stop catalogue was the old stop-first model: Q88 replaced it, because a place is
   * marked on a map and only six of the country's districts have a verified stop to offer.
   */
  function selectRegionForLocation(region: RegionDTO) {
    applyEnd({ region, district: null, stop: null, point: null, corridorId: "" });
    setDistrictMode(locationSelectorMode === "pickup" ? "client-pickup" : "client-dropoff");
    go(region.requires_district ? "client-district-selector" : "client-point-picker");
  }

  /** Step 2. The map is the last step (Q88): a place, not a stop from a catalogue. */
  function selectGeoDistrict(district: DistrictDTO) {
    applyEnd({ ...activeEnd, district, stop: null, point: null, corridorId: "" });
    go("client-point-picker");
  }

  /**
   * Step 3: the place itself. Whether it can be served is the server's answer, asked right after.
   *
   * The district is resolved here when the region never asked for one. Tashkent city is the case that
   * matters: `requires_district` is false there (wave 10), so step 2 is skipped and the end reached the
   * home screen with `district: null` - and `previewDirection` needs a district id at both ends, so the
   * effect returned early, no preview was ever fetched, and "Yo'nalishni ko'rish" stayed grey with nothing
   * on screen to explain why. The nearest catalogue district to the marked place is the honest answer, and
   * it is only trustworthy because the catalogue now holds real centres rather than the old lattice.
   */
  async function markPoint(point: MarkedPoint) {
    let district = activeEnd.district;
    if (!district) {
      const catalogue = await loadGeoDistricts();
      const withinRegion = activeEnd.region
        ? catalogue.filter((item) => item.region.id === activeEnd.region?.id)
        : [];
      district = nearestDistrict(withinRegion.length ? withinRegion : catalogue, point);
    }
    applyEnd({ ...activeEnd, district, stop: null, point });
    go(directionOwner === "driver" ? "driver-feed" : "client-home");
  }

  /**
   * "Where I am now" - the locate button on the home map.
   *
   * The browser gives a coordinate and nothing else, so the district has to be worked out here: the nearest
   * district centre in the v2 catalogue wins. That is only trustworthy because the catalogue now holds real
   * centres (scripts/backfill_district_centers.py); against the old generated lattice this would have named
   * a neighbouring district about as often as the right one.
   *
   * The address underneath comes from our own server's geocoder, and the coordinate the person gets is their
   * real position - not the centre of the district it resolved to. If the browser refuses, nothing is
   * guessed: the person is told and the map stays where it was.
   */
  async function useCurrentLocation() {
    if (locating) return;
    if (!("geolocation" in navigator)) {
      setError(translate("app.location.unsupported"));
      return;
    }
    setLocating(true);
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 15000,
          maximumAge: 60000,
        });
      });
      const here = { lat: position.coords.latitude, lng: position.coords.longitude };

      const [regions, districts] = await Promise.all([
        listRegions().catch(() => [] as RegionDTO[]),
        loadGeoDistricts(),
      ]);
      const nearest = nearestDistrict(districts, here);
      const region = nearest ? regions.find((item) => item.id === nearest.region.id) ?? null : null;
      if (!nearest || !region) {
        setError(translate("app.location.noDistrict"));
        return;
      }

      const named = await reverseGeocode(here).catch(() => null);
      // `provider: "local"` is the server saying it had no geocoder answer and guessed from the catalogue;
      // a wrong street name is worse than none, so that case falls back to the coordinates.
      const address = named && named.provider !== "local" ? (named.formatted_address ?? null) : null;

      setLocationSelectorMode("pickup");
      setDirectionOwner("client");
      setPickupEnd({ region, district: nearest, stop: null, point: { ...here, address }, corridorId: "" });
      setOrderForm((current) => ({
        ...current,
        pickup_lat: here.lat,
        pickup_lng: here.lng,
        pickup_address: address || `${nearest.name_uz}, ${region.name_uz}`,
      }));
      setMessage(translate("app.location.found", { district: nearest.name_uz, region: region.name_uz }));
    } catch (err) {
      const denied = typeof err === "object" && err !== null && "code" in err && (err as GeolocationPositionError).code === 1;
      setError(
        denied
          ? translate("app.location.denied")
          : translate("app.location.failed"),
      );
    } finally {
      setLocating(false);
    }
  }

  /** Step 3: the verified stop the booking is actually agreed on. */
  function selectGeoStop(stop: StopDTO, corridorId: string) {
    applyEnd({ ...activeEnd, stop, point: null, corridorId });
    go(directionOwner === "driver" ? "driver-feed" : "client-home");
  }

  function normalizeCityText(value: string) {
    return value
      .toLowerCase()
      .replace(/[''`]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function citySearchTerms(city: City) {
    const base = [city.name_uz, city.name_ru, city.region].map((value) => normalizeCityText(String(value ?? ""))).filter(Boolean);
    const joined = base.join(" ");
    const aliasGroups = [
      ["toshkent", "tashkent", "ташкент"],
      ["jizzax", "jizzakh", "джизак", "джизакская"],
      ["samarqand", "samarkand", "самарканд"],
      ["buxoro", "bukhara", "бухара", "бухарская"],
      ["andijon", "andijan", "андижан", "андижанская"],
      // i18n-ignore: search aliases, not display text
      ["fargona", "farg ona", "fergana", "фергана", "ферганская"],
      ["namangan", "наманган", "наманганская"],
      ["navoiy", "navoi", "навои", "навоийская"],
      ["qashqadaryo", "kashkadarya", "кашкадарья", "кашкадарьинская"],
      ["surxondaryo", "surkhandarya", "сурхандарья", "сурхандарьинская"],
      ["sirdaryo", "syrdarya", "сырдарья", "сырдарьинская"],
      ["xorazm", "khorezm", "хорезм", "хорезмская"],
      ["qoraqalpogiston", "karakalpakstan", "каракалпакстан"],
    ];
    const aliasTerms = aliasGroups
      .filter((group) => group.some((term) => joined.includes(term)))
      .flat();

    return Array.from(new Set([
      ...base,
      ...aliasTerms,
    ]));
  }

  // Both ends of a listing sit on one corridor; if they do not, no confirmed road joins them (spec §6.2).
  const directionCorridorId = pickupEnd.corridorId || dropoffEnd.corridorId;
  const sameCorridor = !pickupEnd.corridorId || !dropoffEnd.corridorId || pickupEnd.corridorId === dropoffEnd.corridorId;
  // Q88: a stop pair resolves locally; a point pair is only ready once the server found a route for it.
  const bothStops = Boolean(pickupEnd.stop && dropoffEnd.stop && pickupEnd.stop.id !== dropoffEnd.stop.id && sameCorridor);
  const bothPoints = Boolean(pickupEnd.point && dropoffEnd.point && preview);
  const directionReady = bothStops || bothPoints;
  /** Q5: a service is open per corridor, and which service is being asked about depends on the mode. */
  const serviceClosed =
    serviceMode === "passenger" ? flags?.passenger_enabled === false : flags?.parcel_enabled === false;
  const listingUnitMinor = soumToMinor(listingForm.unitPrice);

  /**
   * The leg is measured **along the route**, so the drive from a marked place to the road is not in it.
   *
   * With a real corridor that gap is a couple of kilometres and saying so would be noise. It only matters
   * where a place sits well off the line - which is exactly what the development radius override allows -
   * and there the figure above would otherwise read as door-to-door when it is not.
   */
  const offRouteNote = useMemo(() => {
    if (!preview) return null;
    const worst = Math.max(preview.origin.route_offset_m ?? 0, preview.destination.route_offset_m ?? 0);
    if (worst < 5000) return null;
    return translate("app.location.offRoute", { km: Math.round(worst / 1000) });
  }, [preview, locale]);

  /**
   * Why "Saqlash" is not available yet.
   *
   * It used to be a bare `disabled` expression, so a half-typed date - the browser's `datetime-local` hands
   * back an empty string until every part is filled, and "31.11" never becomes a date at all - left the
   * button grey with nothing on screen to explain it. The rules here are the server's own: the window must
   * end after it starts (DB CHECK) and after now (`create_listing`), so a refusal that would have come back
   * as a 400 is said here instead, before anything is sent.
   */
  const saveBlockers = useMemo(() => {
    const problems: string[] = [];
    if (!directionReady) problems.push(translate("app.validation.bothPoints"));
    const start = listingForm.windowStart ? new Date(listingForm.windowStart) : null;
    const end = listingForm.windowEnd ? new Date(listingForm.windowEnd) : null;
    const startOk = start !== null && !Number.isNaN(start.getTime());
    const endOk = end !== null && !Number.isNaN(end.getTime());
    if (!startOk) problems.push(translate("app.validation.windowStart"));
    if (!endOk) problems.push(translate("app.validation.windowEnd"));
    if (startOk && endOk && end.getTime() <= start.getTime()) {
      problems.push(translate("app.validation.endAfterStart"));
    }
    if (endOk && end.getTime() <= Date.now()) {
      problems.push(translate("app.validation.windowPast"));
    }
    if (listingUnitMinor <= 0) problems.push(translate("listingOwner.invalid.price"));
    return problems;
  }, [directionReady, listingForm.windowStart, listingForm.windowEnd, listingUnitMinor, locale]);

  /**
   * Q88: the moment both places are marked, ask the server whether a confirmed route serves them.
   *
   * The client is never the judge of this - which corridors exist and how far off the road each tolerates are
   * server facts. A refusal is a normal product state ("not on an ELCHI route yet"), so it is kept as its own
   * message instead of being thrown into the generic error banner.
   */
  useEffect(() => {
    const from = pickupEnd.point;
    const to = dropoffEnd.point;
    if (!from || !to || !pickupEnd.district || !dropoffEnd.district) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    let isActive = true;
    setPreviewBusy(true);
    setPreviewError(null);
    void previewDirection({
      origin_lat: from.lat,
      origin_lng: from.lng,
      origin_district_id: pickupEnd.district.id,
      destination_lat: to.lat,
      destination_lng: to.lng,
      destination_district_id: dropoffEnd.district.id,
    })
      .then((result) => {
        if (!isActive) return;
        setPreview(result);
        setPreviewError(null);
      })
      .catch(() => {
        if (!isActive) return;
        setPreview(null);
        setPreviewError(translate("app.location.previewMismatch"));
      })
      .finally(() => {
        if (isActive) setPreviewBusy(false);
      });
    return () => {
      isActive = false;
    };
  }, [pickupEnd.point, dropoffEnd.point, pickupEnd.district, dropoffEnd.district]);


  // Offer a window the first time the route screen is opened with none set. Only ever fills blanks.
  useEffect(() => {
    if (screen !== "client-route-summary") return;
    setListingForm((current) => {
      if (current.windowStart && current.windowEnd) return current;
      const suggested = suggestedDepartureWindow();
      return {
        ...current,
        windowStart: current.windowStart || suggested.start,
        windowEnd: current.windowEnd || suggested.end,
      };
    });
  }, [screen]);

  /**
   * F1: a service is enabled **per corridor** (Q5), so the answer depends on which direction is on screen.
   *
   * Asking without a corridor resolves the country scope, where a piloted service is still off - reading that
   * as "closed everywhere" would hide a direction that is actually open. So the corridor is passed as soon as
   * it is known, and the flags are re-read when it changes. A failed read closes everything (Q26).
   */
  useEffect(() => {
    if (!auth.isAuthenticated) {
      setFlags(null);
      return;
    }
    let isActive = true;
    void effectiveFlags(directionCorridorId || undefined)
      .then((value) => { if (isActive) setFlags(value.flags); })
      .catch(() => {
        if (isActive) setFlags({ passenger_enabled: false, parcel_enabled: false, driver_listing_enabled: false, tracking_enabled: false });
      });
    return () => { isActive = false; };
  }, [auth.isAuthenticated, directionCorridorId]);
  const parcelReady = Boolean(
    Number(listingForm.weightKg) > 0
    && Number(listingForm.lengthCm) > 0
    && Number(listingForm.widthCm) > 0
    && Number(listingForm.heightCm) > 0,
  );

  /**
   * The districts this direction passes, in travel order (G17). `on_confirmed_route` is what makes the
   * recommendation honest: a district the corridor owns a stop in but no confirmed road reaches yet is not
   * "on your way" (Q46 - without a routing provider only confirmed stop matches exist).
   */
  useEffect(() => {
    if (!directionCorridorId || !directionReady) {
      setRouteVersion(null);
      setRouteDistricts([]);
      setCorridorStops([]);
      return;
    }
    let isActive = true;
    void listCorridorRoutes(directionCorridorId, 1)
      .then((items) => { if (isActive) setRouteVersion(items[0] ?? null); })
      .catch(() => { if (isActive) setRouteVersion(null); });
    void listCorridorDistricts(directionCorridorId)
      .then((items) => { if (isActive) setRouteDistricts(items); })
      .catch(() => { if (isActive) setRouteDistricts([]); });
    void listCorridorStops(directionCorridorId)
      .then((items) => { if (isActive) setCorridorStops(items); })
      .catch(() => { if (isActive) setCorridorStops([]); });
    return () => { isActive = false; };
  }, [directionCorridorId, directionReady]);

  async function loadClientOrders() {
    const result = await listClientOrders({ limit: 50 });
    setOrders(result.items ?? []);
  }

  async function openClientOrder(id: number, target: Screen = "client-order-detail") {
    setSelectedOrderId(id);
    const detail = await getClientOrder(id);
    setOrderDetail(detail as OrderDetail);
    if (target === "client-bids") {
      setBids(await listClientOrderBids(id));
    }
    go(target);
  }

  /**
   * L1 + L4: the draft is written and published in one go, exactly as the v1 button promised.
   *
   * `Idempotency-Key` is generated per attempt (ADR-0005): a repeated tap after a timeout returns the same
   * draft instead of opening a second listing. The free-text comment is filtered by the server (Q43) and the
   * warnings it returns are shown as they come back - the screen never hides that something was masked.
   */
  /** Q88: one end is a verified stop **or** a marked place - the body carries exactly one of the two. */
  function endFields(end: DirectionEnd, prefix: "origin" | "destination") {
    if (end.point && end.district) {
      return {
        [`${prefix}_point`]: {
          lat: end.point.lat,
          lng: end.point.lng,
          district_id: end.district.id,
          address: end.point.address,
        },
      };
    }
    return { [`${prefix}_stop_id`]: end.stop?.id };
  }

  async function publishListingDraft() {
    const haveEnds = (pickupEnd.stop || pickupEnd.point) && (dropoffEnd.stop || dropoffEnd.point);
    if (!haveEnds) return;
    const passenger = serviceMode === "passenger";
    const body = {
      kind: "request",
      service_type: passenger ? "passenger" : "parcel",
      ...endFields(pickupEnd, "origin"),
      ...endFields(dropoffEnd, "destination"),
      departure_window_start: localInputToIso(listingForm.windowStart),
      departure_window_end: localInputToIso(listingForm.windowEnd),
      price_basis: passenger ? "per_seat" : "total",
      unit_price_minor: listingUnitMinor,
      comment: (orderForm.comment ?? "").trim() || null,
      ...(passenger
        ? { passenger: { seat_count: seatCount, adults: seatCount } }
        : {
            parcel: {
              parcel_type: listingForm.parcelType,
              weight_g: Math.round(Number(listingForm.weightKg) * 1000),
              length_cm: Math.round(Number(listingForm.lengthCm)),
              width_cm: Math.round(Number(listingForm.widthCm)),
              height_cm: Math.round(Number(listingForm.heightCm)),
              payer: "sender",
              sender: { name: listingForm.senderName.trim(), phone: orderForm.sender_phone.trim() },
              receiver: { name: listingForm.receiverName.trim(), phone: orderForm.receiver_phone.trim() },
              photo_file_id: orderForm.cargo_photo_url || null,
            },
          }),
    } as unknown as ListingCreate;
    const created = await createListing(body, newIdempotencyKey());
    setListingWarnings(created.warnings.map((warning) => warning.code));
    await publishListing(created.data.id, created.data.version);
    resetOrderDraft();
    await loadMyListings();
    go("client-success");
  }

  async function openListing(listingId: string, target: Screen = "client-listing-detail") {
    const listing = await getListing(listingId);
    setListingDetail(listing);
    // My own threads with each driver. The anonymous board of competing offers (P9/Q40) is the *driver*
    // view of a request - the owner gets 404 there - so it belongs on the driver screens, not here.
    setListingThreads(await listListingProposals(listingId).catch(() => [] as ProposalThreadDTO[]));
    go(target);
  }

  /** B5: the codes belong to the client; the driver never sees them (rules.CLIENT_CODE_KINDS). */
  async function openClientBooking(bookingId: string) {
    const booking = (await getBooking(bookingId)) as BookingClientDTO;
    setClientBooking(booking);
    setBookingCodes(await getBookingCodes(bookingId).catch(() => null));
    setBookingDisputes(await myDisputes({ limit: 20 }).catch(() => [] as DisputeDTO[]));
    setReissueNotice(null);
    if (booking.service_status === "cancelled") await loadIntentOfBooking(bookingId);
    go("client-booking-detail");
  }

  /**
   * ADR-0025: a cancelled booking that came from a saved request. The request is re-read from the server (not a
   * copy kept on this device) so "Qayta qidirish" is offered exactly when the server says it may be (`can_reopen`).
   */
  async function loadIntentOfBooking(bookingId: string): Promise<TripIntentDTO | null> {
    if (auth.user?.role !== "client") return null;
    const booked = await listTripIntents("booked").catch(() => [] as TripIntentDTO[]);
    const linked = intentOfBooking(booked, bookingId);
    if (!linked) return null;
    const fresh = await getTripIntent(linked.id).catch(() => linked);
    setMyIntents((list) => [fresh, ...list.filter((item) => item.id !== fresh.id)]);
    return fresh;
  }

  /** The explicit "search again" of ADR-0025, started from the cancelled booking itself. */
  function searchAgainFor(intent: TripIntentDTO) {
    void run(async () => {
      const next = await reopenTripIntent(intent.id, intent.version);
      rememberIntent(next);
      setServiceMode(next.service_type as "parcel" | "passenger");
      go("client-offers");
    }, translate("app.toast.searchRestarted"));
  }

  /**
   * B3: cancel a booking, from either side.
   *
   * The refusal the person most needs to understand - a no-show under operator review (Q7/Q19) - is said in its
   * own words on the sheet, and the booking is re-read so the screen shows what is true now. On success a
   * client's saved request is re-read, because that is what makes "Qayta qidirish" reachable (ADR-0025).
   */
  function submitCancel() {
    const ask = cancelAsk;
    if (!ask || !cancelReason) return;
    void run(async () => {
      setCancelRefusal(null);
      try {
        await cancelBooking(ask.bookingId, ask.version, cancelReason, cancelComment.trim() || undefined);
      } catch (cause) {
        const key = cancelRefusalKey(cause as { code?: string });
        if (!key) throw cause;
        const refusal = translateDynamic(key) ?? getErrorMessage(cause);
        await (ask.side === "driver" ? openDriverBooking(ask.bookingId) : openClientBooking(ask.bookingId)).catch(() => undefined);
        setCancelRefusal(refusal);
        return;
      }
      setCancelAsk(null);
      setCancelComment("");
      if (ask.side === "driver") {
        await openDriverBooking(ask.bookingId);
        await loadDriverBookings().catch(() => undefined);
      } else {
        await openClientBooking(ask.bookingId);
        await loadMyListings().catch(() => undefined);
      }
      setMessage(translate("bookingCancel.done"));
    });
  }

  function openCancel(bookingId: string, side: BookingSide, version: number) {
    setCancelAsk({ bookingId, side, version });
    setCancelReason(CANCEL_REASONS[side][0]);
    setCancelComment("");
    setCancelRefusal(null);
  }

  /** B5a: a new code for its owner. The server's wait (Q75) is shown next to the code, not as a failure. */
  function reissueCode(bookingId: string, kind: string) {
    void run(async () => {
      try {
        const result = await reissueBookingCode(bookingId, kind as ProofKind);
        setBookingCodes((current) => {
          const fresh = result.data.codes;
          const kept = (current?.codes ?? []).filter((code) => !fresh.some((item) => item.kind === code.kind));
          return { booking_id: bookingId, codes: [...kept, ...fresh] };
        });
        setReissueNotice({ kind, text: translate("reissue.done"), ok: true });
      } catch (cause) {
        const wait = reissueWait(cause as { code?: string; details?: unknown });
        if (!wait) throw cause;
        setReissueNotice({ kind, text: reissueWaitText(wait), ok: false });
      }
    });
  }

  /** S1/S3 from either side: the booking the rating or dispute screen works on is the one open for that side. */
  function openRating(bookingId: string, side: BookingSide) {
    setOpenBooking({ id: bookingId, side });
    setRating(5);
    setRatingComment("");
    go("booking-rating");
  }

  function openDisputeForm(bookingId: string, side: BookingSide) {
    setOpenBooking({ id: bookingId, side });
    setDisputeType("service");
    setDisputeComment("");
    go("booking-dispute");
  }

  /** S5: one dispute, re-read so both sides' latest evidence and any decision are current. */
  async function openDisputeDetail(disputeId: string) {
    setDisputeDetail(await getDispute(disputeId));
    setEvidenceNote(null);
    go("dispute-detail");
  }

  /** L3: the owner's edit form, opened on the listing as the server has it now (its `version` is what is sent). */
  async function openListingEdit(listingId: string, back: Screen) {
    const listing = await getListing(listingId);
    const threads = listing.kind === "request"
      ? await listListingProposals(listingId).catch(() => null)
      : null;
    setListingEdit({
      listing,
      form: formFromListing(listing),
      back,
      confirming: false,
      openOffers: threads ? threads.filter((thread) => thread.state === "open").length : null,
    });
    go("listing-edit");
  }

  /** L5/L6: pause or resume, then show the listing as the server answered it. */
  function setListingPaused(listing: ListingDTO, pause: boolean, after: () => Promise<void>) {
    void run(async () => {
      if (pause) await pauseListing(listing.id, listing.version);
      else await resumeListing(listing.id, listing.version);
      await after();
    }, translate(pause ? "listingOwner.paused" : "listingOwner.resumed"));
  }

  /** ADR-0025: the editor opens on the request as the server has it, not a copy from another session. */
  function openIntentEditor() {
    void run(async () => {
      if (activeIntent) rememberIntent(await getTripIntent(activeIntent.id));
      go("client-intent-edit");
    });
  }

  /**
   * N4: where an inbox item leads. The link is the server's (`communications.recipients`); the screen it opens
   * depends on which side this account is, because a booking has a client view and a driver view.
   */
  async function openInboxItem(item: NotificationDTO) {
    if (!item.is_read) {
      await markNotificationRead(item.id).catch(() => undefined);
      setNotifications((list) => list.map((row) => (row.id === item.id ? { ...row, is_read: true } : row)));
    }
    const target = parseInboxLink(item.link);
    const driver = auth.user?.role === "driver";
    if (!target) return;
    if (target.kind === "booking") {
      if (driver) await openDriverBooking(target.id);
      else await openClientBooking(target.id);
      if (target.chat) await openChat(target.id, driver ? "driver" : "client");
    } else if (target.kind === "listing") {
      if (driver) go("driver-routes");
      else await openListing(target.id);
    } else if (target.kind === "proposal") {
      go(driver ? "driver-proposals" : "client-proposals");
    } else if (target.kind === "trip") {
      if (driver) go("driver-routes");
    } else if (target.kind === "dispute") {
      await openDisputeDetail(target.id);
    }
  }

  const CHAT_PAGE = 30;

  /** N6: the thread of one booking. The server returns the masked text, so nothing is re-filtered here. */
  async function loadChat(bookingId: string, limit = CHAT_PAGE) {
    const page = await listMessages(bookingId, { limit });
    setChatMessages(page);
    setChatHasMore(page.length >= limit);
  }

  async function openChat(bookingId: string, side: "client" | "driver") {
    setOpenBooking({ id: bookingId, side });
    setChatDraft("");
    setChatFailed(null);
    setChatWarnings([]);
    setChatState(null);
    // State and messages together: the composer must not be drawn before it is known whether writing is
    // still allowed, or the screen invites a message the server will refuse.
    const [state] = await Promise.all([getChatState(bookingId), loadChat(bookingId)]);
    setChatState(state);
    go("booking-chat");
  }

  /**
   * Saved searches come back as ids. A driver reading `dst_9f2c...` learns nothing, so the district catalogue
   * is fetched alongside and the ids are resolved to the names the driver picked them by. An id that cannot be
   * resolved is described ("bekat") rather than printed.
   */
  /** Open the ranked matches of a listing this person owns. */
  async function openMatches(listingId: string, kind: string) {
    const result = await listingMatches(listingId, { limit: 20 });
    setMatches(result.data);
    setMatchesFor({ id: listingId, kind });
    setMatchScope((result.meta as { match_scope?: string } | undefined)?.match_scope ?? null);
    go("listing-matches");
  }

  async function loadSavedSearches() {
    const [rows, districts] = await Promise.all([savedSearches(), listDistricts({ limit: 500 })]);
    setSaved(rows);
    setDistrictNames(Object.fromEntries(districts.map((district) => [district.id, district.name_uz])));
  }

  async function loadAmendments(bookingId: string) {
    setAmendments(await listAmendments(bookingId));
  }

  /**
   * Open the amendment screen for a booking.
   *
   * The booking is re-read first: an amendment carries `expected_version`, and proposing against a stale one
   * is exactly the race the version exists to catch.
   */
  async function openAmendments(bookingId: string, side: "client" | "driver") {
    const booking = await getBooking(bookingId);
    if (side === "driver") setDriverBooking(booking as BookingDTO);
    else setClientBooking(booking as BookingClientDTO);
    setOpenBooking({ id: bookingId, side });
    setAmendmentForm({ quantity: String(booking.quantity), unitPrice: String(Math.round(booking.unit_price_minor / 100)), reason: "" });
    await loadAmendments(bookingId);
    go("booking-amendment");
  }

  async function openTracking(bookingId: string, side: "client" | "driver") {
    setOpenBooking({ id: bookingId, side });
    setTrackingError("");
    try {
      setTracking(await getBookingTracking(bookingId));
    } catch (err) {
      // §10.6: a closed window is a normal answer, not a failure - the screen says which it is.
      setTracking(null);
      setTrackingError(getErrorMessage(err));
    }
    go("booking-tracking");
  }

  /** B10: record the handover. The server refuses a client who is not the payer, and that answer is shown. */
  async function reportCash(bookingId: string, side: "client" | "driver", version: number) {
    await reportCashReceipt(
      bookingId,
      {
        expected_version: version,
        amount_minor: soumToMinor(cashAmount),
        reported_at: new Date().toISOString(),
        note: null,
      },
      newIdempotencyKey(),
    );
    setCashAmount("");
    await (side === "driver" ? openDriverBooking(bookingId) : openClientBooking(bookingId));
  }

  async function decideCash(bookingId: string, side: "client" | "driver", receipt: CashReceiptDTO, decision: "acknowledge" | "contest") {
    await decideCashReceipt(bookingId, receipt.id, decision, receipt.version);
    await (side === "driver" ? openDriverBooking(bookingId) : openClientBooking(bookingId));
  }

  /**
   * P6: answer with different terms instead of only accepting or refusing.
   *
   * `expected_revision` is what makes it safe: if the other side moved first, the server answers
   * PROPOSAL_CHANGED and the screen re-reads rather than writing over a revision it never saw. Nothing is
   * applied optimistically - the thread on screen is always the one the server confirmed.
   */
  async function sendCounter(threadId: string, revision: number, reload: () => Promise<void>, withBonus = false) {
    if (counterPending) return;
    setCounterPending(true);
    try {
      const promo = withBonus ? consentBody(counterConsent) : undefined;
      await counterProposal(threadId, {
        expected_revision: revision,
        unit_price_minor: soumToMinor(counterPrice),
        ...(promo ? { promo_consent: promo } : {}),
      });
      setCounterFor(null);
      setCounterPrice("");
      setCounterConsent(NO_CONSENT);
      await reload();
    } catch (error) {
      if (needsRequote(error as { code?: string })) {
        // the bonus changed under the person: keep the form open with the new numbers and ask again
        requoteOn(error);
        throw error;
      }
      // A refused counter usually means the other side moved first: show what is on the server now, not the
      // stale card the person was looking at, and let the error message explain why nothing was sent.
      setCounterFor(null);
      await reload().catch(() => undefined);
      throw error;
    } finally {
      setCounterPending(false);
    }
  }

  async function loadMyProposals() {
    setMyProposals(await listMyProposals({ limit: 30 }));
  }

  async function loadMyListings() {
    const [items, bookings] = await Promise.all([
      listMyListings({ limit: 30 }),
      listMyBookings({ role: "client", limit: 30 }),
    ]);
    setMyListings(items);
    setClientBookings(bookings);
    // There is no proposal counter on the listing DTO, so the number is counted from the open listings
    // themselves rather than guessed - an empty answer means no proposal, not "unknown".
    const open = items.filter((item) => item.status === "published").slice(0, 10);
    const counts = await Promise.all(
      open.map((item) => listListingProposals(item.id).then((threads) => threads.length).catch(() => 0)),
    );
    setProposalTotal(counts.reduce((sum, value) => sum + value, 0));
  }

  /** The trip offers already published for one trip - what that journey is advertised as, and for how much. */
  function tripOffers(tripId: string) {
    return myOffers.filter((offer) => offer.trip_id === tripId && offer.status !== "cancelled" && offer.status !== "expired");
  }

  /**
   * Which services this trip can still be advertised for.
   *
   * Q92: one trip carries both, and the database says so - `uq_listings_open_trip_offer` is unique on
   * `(trip_id, service_type)`, not on `trip_id`. So a driver may publish a taxi offer *and* a parcel offer on
   * the same journey, and the second one is refused only if it repeats the first's service.
   *
   * The screen used to open on "passenger" every time, which meant the second tap on a trip that already had
   * a passenger offer walked the driver through the whole form and then failed on send with DUPLICATE_LISTING
   * - the one path that makes "can a driver post both?" feel like "no". The same filter as `tripOffers` is
   * used, because that is exactly the index's predicate: a cancelled or expired offer frees its service again.
   */
  function availableOfferServices(tripId: string): OfferService[] {
    // `myOffers` already holds every listing of this trip; the module applies the index's own status filter.
    return offerableServices(
      myOffers.filter((offer) => offer.trip_id === tripId),
      { passengerEnabled: Boolean(flags?.passenger_enabled) },
    );
  }

  function resetOrderDraft() {
    setOrderForm(emptyOrder);
    setSelectedFromCity(null);
    setSelectedToCity(null);
    setSelectedFromDistrict(null);
    setSelectedToDistrict(null);
    setPickupEnd(emptyDirectionEnd);
    setDropoffEnd(emptyDirectionEnd);
    setRouteVersion(null);
    setRouteDistricts([]);
    setCorridorStops([]);
    setListingForm({
      windowStart: "",
      windowEnd: "",
      unitPrice: "",
      parcelType: "box",
      weightKg: "",
      lengthCm: "",
      widthCm: "",
      heightCm: "",
      senderName: "",
      receiverName: "",
    });
  }

  async function loadDriverProfile() {
    const profile = await getDriverProfile();
    setDriverProfile(profile);
    setDriverForm({
      full_name: profile.full_name ?? profile.user?.full_name ?? "",
      car_model: profile.car_model ?? "",
      car_color: profile.car_color ?? "",
      plate_number: profile.plate_number ?? "",
    });
  }

  /**
   * The driver's planned journeys (T1), the cars they may use - a car is usable only once staff verify it -
   * and the trip offers they have already put on the market.
   *
   * Q92: a driver's own listings live in the same `/me/listings` collection a client's requests do; they are
   * the same object with the other author. Keeping them next to the trips is what lets a trip card say whether
   * it is advertised and for how much.
   */
  async function loadDriverTrips() {
    const [tripList, vehicleList, listings] = await Promise.all([
      listMyTrips({ limit: 30 }),
      listMyVehicles(),
      listMyListings({ limit: 30 }).catch(() => [] as ListingDTO[]),
    ]);
    setTrips(tripList);
    setVehicles(vehicleList);
    setMyOffers(listings.filter((item) => item.kind === "trip_offer"));
  }

  /**
   * M1: the open client requests this driver may answer.
   *
   * The ends are the ones the driver picked in the same selector the client uses. When a district was chosen
   * the question widens from "this exact stop" to "anywhere in this district", which is how a driver going
   * Toshkent -> Qarshi also sees the requests of the districts on the way - still on verified stops and the
   * confirmed route order, never merely "administratively nearby" (spec §6.1, Q46).
   */
  async function loadRequestFeed(mode: "parcel" | "passenger" = driverServiceMode) {
    if (!pickupEnd.stop && !pickupEnd.district) {
      setRequestFeed([]);
      return;
    }
    const result = await requestsFeed({
      // Passed in, not read from state: a toggle sets the state and reloads in the same handler, and the state
      // React has not applied yet would fetch the service the driver just switched away from.
      service_type: mode,
      origin_district_id: pickupEnd.district?.id,
      origin_stop_id: pickupEnd.district ? undefined : pickupEnd.stop?.id,
      destination_district_id: dropoffEnd.district?.id,
      destination_stop_id: dropoffEnd.district ? undefined : dropoffEnd.stop?.id,
      limit: 30,
    });
    setRequestFeed(result.data);
    setMatchScope((result.meta as { match_scope?: string } | undefined)?.match_scope ?? null);
  }

  /** The documents screen reads its own list: the profile carries a verdict, not which slot is missing. */
  async function loadDriverDocuments() {
    setDriverDocuments(await listDriverDocuments());
  }

  /**
   * Q40 / ADR-0019: the other drivers' current offers on this client request, anonymised by the server.
   *
   * This is the open half of the auction. A bidder who cannot see that the request already sits at 280 000
   * either underbids blind or names a price nobody will take, so the board is loaded before the bid screen is
   * drawn. What comes back never carries a name, phone, plate or make - only the stable "Haydovchi #N" label,
   * the price, the window, the vehicle class and the trust bucket.
   *
   * It fails soft on purpose: the endpoint 404s when the service flag is off or the corridor is not open, and
   * that must cost the driver the board, not the ability to bid.
   */
  async function loadRivalOffers(listingId: string) {
    try {
      setRivalOffers(await listListingOffers(listingId));
      setRivalOffersError(false);
    } catch {
      setRivalOffers([]);
      setRivalOffersError(true);
    }
  }

  /**
   * Q92, the other half of the same market: the driver trip offers that serve where this client is going.
   *
   * The client picked two places on the home sheet; the district of each is what the feed is asked with, so a
   * client going Toshkent -> Qarshi sees every offer that calls at a verified stop in those districts. Nothing
   * is matched merely because it is administratively nearby - the server still answers on the confirmed route.
   *
   * Seats matter for a passenger offer: a per-seat price is only comparable for the number of seats asked for,
   * and an offer with fewer seats left than that is not a match at all.
   */
  // --- ADR-0025: the saved trip/parcel request ------------------------------------------------------------------

  function rememberIntent(intent: TripIntentDTO | null) {
    setActiveIntent(intent);
    writeActiveIntentId(auth.user?.id, intent?.id ?? null);
    if (intent) setMyIntents((list) => [intent, ...list.filter((item) => item.id !== intent.id)]);
  }

  async function loadIntents(): Promise<TripIntentDTO | null> {
    setIntentLoading(true);
    setIntentError(null);
    try {
      // Live ones only, asked for by status so a long history of closed requests never pushes them off the page.
      const [active, booked] = await Promise.all([listTripIntents("active"), listTripIntents("booked")]);
      const live = [...active, ...booked];
      const chosen = pickActive(live, readActiveIntentId(auth.user?.id));
      setMyIntents(live);
      setActiveIntent(chosen);
      writeActiveIntentId(auth.user?.id, chosen?.id ?? null);
      return chosen;
    } catch (cause) {
      setIntentError(getErrorMessage(cause));
      return null;
    } finally {
      setIntentLoading(false);
    }
  }

  /** One end as the request stores it: a verified stop by id, a marked place by its district and point (Q88). */
  function intentEnd(end: DirectionEnd) {
    if (end.point && end.district) {
      return { district_id: end.district.id, lat: end.point.lat, lng: end.point.lng, address: end.point.address ?? null };
    }
    return { stop_id: end.stop?.id ?? null };
  }

  /** What the route summary says, as request terms. The price is optional - it is only the client's own hint. */
  function intentTermsFromHome() {
    const passenger = serviceMode === "passenger";
    return {
      origin: intentEnd(pickupEnd),
      destination: intentEnd(dropoffEnd),
      window_start: localInputToIso(listingForm.windowStart),
      window_end: localInputToIso(listingForm.windowEnd),
      quantity: passenger ? seatCount : 1,
      price_basis: listingUnitMinor > 0 ? (passenger ? "per_seat" : "total") : null,
      unit_price_minor: listingUnitMinor > 0 ? listingUnitMinor : null,
    };
  }

  /**
   * PATCH the active request. A material change with open offers answers 409 first; the client is then shown how
   * many offers close and the same body is resent with `acknowledge_open_offers` only after they agree.
   */
  async function sendIntentEdit(body: Record<string, unknown>, then: Screen): Promise<TripIntentDTO | null> {
    if (!activeIntent) return null;
    try {
      const result = await editTripIntent(activeIntent.id, body as unknown as TripIntentUpdate);
      rememberIntent(result.data);
      return result.data;
    } catch (cause) {
      const failure = cause as { code?: string; details?: { open_offers?: number } };
      if (failure.code === "TRIP_INTENT_OFFERS_AFFECTED") {
        setIntentEditPending({ body, openOffers: failure.details?.open_offers ?? activeIntent.open_offers, then });
        return null;
      }
      if (failure.code?.startsWith("TRIP_INTENT") || failure.code === "VERSION_CONFLICT") void loadIntents();
      throw cause;
    }
  }

  async function saveIntentFromHome() {
    const terms = intentTermsFromHome();
    const editing = intentDraftMode === "edit" && activeIntent?.status === "active"
      && activeIntent.service_type === serviceMode;
    if (editing && activeIntent) {
      if (!(await sendIntentEdit(updateBody(activeIntent, terms), "client-offers"))) return;
    } else {
      const created = await createTripIntent({
        service_type: serviceMode,
        ...terms,
        parcel: serviceMode === "parcel" ? { parcel_type: listingForm.parcelType } : null,
      } as unknown as TripIntentCreate);
      rememberIntent(created.data);
    }
    setIntentDraftMode("new");
    go("client-offers");
  }

  function saveIntentEdit(form: IntentEditForm) {
    if (!activeIntent) return;
    const passenger = activeIntent.service_type === "passenger";
    const priceMinor = soumToMinor(form.price);
    const body = updateBody(activeIntent, {
      window_start: localInputToIso(form.windowStart),
      window_end: localInputToIso(form.windowEnd),
      quantity: passenger ? form.quantity : 1,
      price_basis: priceMinor > 0 ? (passenger ? "per_seat" : "total") : null,
      unit_price_minor: priceMinor > 0 ? priceMinor : null,
      parcel: passenger ? null : parcelInput(form),
    });
    void run(async () => {
      if (await sendIntentEdit(body, "client-offers")) go("client-offers");
    }, translate("app.toast.intentUpdated"));
  }

  function closeActiveIntent() {
    if (!activeIntent) return;
    const intent = activeIntent;
    void run(async () => {
      await closeTripIntent(intent.id, intent.version);
      const next = await loadIntents();
      go("client-offers");
      await loadOfferFeed(serviceMode, next);
    }, translate("app.toast.intentClosed"));
  }

  /** Explicit "search again" after a cancelled booking; the old offers stay closed (ADR-0025). */
  function reopenActiveIntent() {
    if (!activeIntent) return;
    const intent = activeIntent;
    void run(async () => {
      const next = await reopenTripIntent(intent.id, intent.version);
      rememberIntent(next);
      await loadOfferFeed(serviceMode, next);
    }, translate("app.toast.searchRestarted"));
  }

  function startNewIntent() {
    setIntentDraftMode("new");
    go("client-home");
  }

  function editIntentRoute() {
    if (!activeIntent) return;
    setIntentDraftMode("edit");
    setServiceMode(activeIntent.service_type as "parcel" | "passenger");
    go("client-home");
  }

  /** The list may be older than the request (edited from another device): the chosen one is re-read first. */
  function selectIntent(intent: TripIntentDTO) {
    void run(async () => {
      const fresh = await getTripIntent(intent.id);
      rememberIntent(fresh);
      await loadOfferFeed(serviceMode, fresh);
    });
  }

  /** The request the offer screen works with: live, and of the same service as this driver's offer. */
  function intentFor(offer: { service_type: string } | null | undefined): TripIntentDTO | null {
    return activeIntent && offer && activeIntent.status === "active" && activeIntent.service_type === offer.service_type
      ? activeIntent
      : null;
  }

  /** A driver's offer opens already filled from the request; the differences are fetched, nothing is reserved. */
  function openOfferBid(item: FeedItemDTO) {
    const intent = intentFor(item.listing);
    setSelectedOffer(item);
    setIntentFit(null);
    if (intent) {
      const fill = prefillBid(intent, item.listing);
      setOfferBid({
        price: fill.price,
        seats: fill.seats,
        parcelType: intent.current_version.parcel?.parcel_type ?? "box",
        weightKg: fill.weightKg,
        lengthCm: fill.lengthCm,
        widthCm: fill.widthCm,
        heightCm: fill.heightCm,
        receiverName: fill.receiverName,
        receiverPhone: fill.receiverPhone,
      });
      setIntentFitLoading(true);
      void tripIntentFit(intent.id, item.listing.id)
        .then(setIntentFit)
        .catch(() => setIntentFit(null))
        .finally(() => setIntentFitLoading(false));
    } else {
      setOfferBid({ ...offerBid, price: String(Math.round(item.listing.unit_price_minor / 100)), seats: 1 });
    }
    go("client-offer-bid");
  }

  async function loadOfferFeed(mode: "parcel" | "passenger" = serviceMode, intentOverride?: TripIntentDTO | null) {
    // ADR-0025: with a live saved request the feed answers for it, so the list matches the summary above it and
    // survives a restart; without one it reads the places marked on the home sheet, as before.
    const intent = intentOverride !== undefined ? intentOverride : activeIntent;
    if (intent && intent.status === "active") {
      const v = intent.current_version;
      const result = await offersFeed({
        service_type: intent.service_type,
        origin_district_id: v.origin.district?.id,
        origin_stop_id: v.origin.district ? undefined : v.origin.stop?.id,
        destination_district_id: v.destination.district?.id,
        destination_stop_id: v.destination.district ? undefined : v.destination.stop?.id,
        seats: intent.service_type === "passenger" ? v.quantity : undefined,
        limit: 30,
      });
      setOfferFeed(result.data);
      setMatchScope((result.meta as { match_scope?: string } | undefined)?.match_scope ?? null);
      return;
    }
    if (!pickupEnd.stop && !pickupEnd.district) {
      setOfferFeed([]);
      return;
    }
    const result = await offersFeed({
      service_type: mode,
      origin_district_id: pickupEnd.district?.id,
      origin_stop_id: pickupEnd.district ? undefined : pickupEnd.stop?.id,
      destination_district_id: dropoffEnd.district?.id,
      destination_stop_id: dropoffEnd.district ? undefined : dropoffEnd.stop?.id,
      seats: mode === "passenger" ? offerBid.seats : undefined,
      limit: 30,
    });
    setOfferFeed(result.data);
    setMatchScope((result.meta as { match_scope?: string } | undefined)?.match_scope ?? null);
  }

  /**
   * §9.2: the wallet is the commission account, not earnings. A pending top-up is a request, not money, so it
   * is shown on its own line and never added to the balance.
   */
  async function loadWallet() {
    const [balance, requests, lines] = await Promise.all([
      fetchWallet(),
      listTopups({ limit: 10 }),
      walletTransactions({ limit: 50 }).catch(() => [] as LedgerLineDTO[]),
    ]);
    setWalletState(balance);
    setTopups(requests);
    setWalletLines(lines);
  }

  async function openDriverBooking(bookingId: string) {
    setProofCode("");
    setDriverBooking((await getBooking(bookingId)) as BookingDTO);
    setBookingDisputes(await myDisputes({ limit: 20 }).catch(() => [] as DisputeDTO[]));
    go("driver-order-detail");
  }

  async function loadDriverBookings() {
    setDriverBookings(await listMyBookings({ role: "driver", limit: 30 }));
  }

  /** N4 (v2): the in-app inbox is the only delivery channel in the pilot (Q82), so the bell count comes from here. */
  async function loadNotifications() {
    setNotifications(await fetchNotifications({ limit: 50 }));
  }

  /**
   * What support looks like right now: who can be reached (S13), and what this person has already asked.
   *
   * Both are allowed to fail quietly. A help screen that itself shows an error is the worst moment for one,
   * and the ticket form underneath works either way - so a missing answer means "no line", which is also the
   * truthful pilot answer (Q87).
   */
  async function loadSupport() {
    const [contacts, tickets] = await Promise.all([
      fetchSupportContacts().catch(() => null),
      mySupportTickets({ limit: 20 }).catch(() => []),
    ]);
    setSupportInfo(contacts);
    setSupportTickets(Array.isArray(tickets) ? tickets : []);
  }

  async function runConfirmAction(action: ConfirmAction) {
    if (action.type === "select-driver") {
      if (!selectedOrderId || !(action.bid.id ?? action.bid.bid_id)) return;
      await selectDriver(selectedOrderId, Number(action.bid.id ?? action.bid.bid_id));
      setConfirmAction(null);
      await openClientOrder(selectedOrderId);
      return;
    }
    if (action.type === "confirm-delivery" && orderDetail) {
      await confirmClientOrder(orderDetail.id);
      setConfirmAction(null);
      go("client-rating");
      return;
    }
    if (action.type === "cancel-order" && orderDetail) {
      await cancelClientOrder(orderDetail.id, "Mijoz bekor qildi");
      setConfirmAction(null);
      await loadClientOrders();
      go("client-orders");
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated) return;
    if (screen === "client-home" || screen === "client-orders") {
      void run(async () => {
        await loadMyListings();
        await loadClientOrders();
        // The tab badge has to be right before the person opens the tab.
        await loadNotifications().catch(() => undefined);
      });
    }
    if (screen === "client-notifications" || screen === "driver-notifications") void run(loadNotifications);
    if (screen === "support") void run(loadSupport);
    if (screen === "client-point-picker") {
      // Fails quietly: the map is the flow, and the shortcuts are an extra. An empty list is also the
      // truthful answer for most districts.
      void loadStopOptions({
        districtId: activeEnd.district?.id ?? null,
        regionId: activeEnd.district ? null : (activeEnd.region?.id ?? null),
        corridorId: otherEnd.corridorId || null,
      })
        .then(setStopOptions)
        .catch(() => setStopOptions([]));
    }
    if (screen === "client-profile") {
      void run(async () => {
        const profile = await getClientProfile();
        setClientName(profile.full_name ?? "");
        await loadClientOrders();
      });
    }
    if (screen === "driver-profile-form") void run(loadDriverTrips);
    if (screen === "driver-home" || screen === "driver-profile" || screen === "driver-income") {
      void run(async () => {
        await loadDriverProfile();
        // The bell needs a count before the driver opens the inbox, so the badge is truthful on arrival.
        if (screen === "driver-home") await loadNotifications().catch(() => undefined);
        if (screen === "driver-home") await loadWallet().catch(() => setWalletState(null));
        if (screen === "driver-profile") await loadDriverTrips();
      });
    }
    if (screen === "my-disputes") void run(async () => setBookingDisputes(await myDisputes()));
    if (screen === "driver-saved-searches") void run(loadSavedSearches);
    if (screen === "driver-routes") void run(loadDriverTrips);
    if (screen === "driver-add-route") {
      void run(async () => {
        await loadDriverTrips();
        setCorridors(await listCorridors());
      });
    }
    if (screen === "driver-documents") void run(loadDriverDocuments);
    if (screen === "driver-feed") void run(loadRequestFeed);
    if (screen === "driver-offer-create") void run(loadDriverTrips);
    if (screen === "client-offers") void run(loadOfferFeed);
    if (screen === "driver-proposals" || screen === "client-proposals") {
      void run(async () => {
        if (screen === "driver-proposals") await loadDriverTrips();
        await loadMyProposals();
      });
    }
    if (screen === "driver-orders") void run(loadDriverBookings);
    if (screen === "driver-income") void run(loadWallet);
  }, [screen, auth.isAuthenticated]);

  const unreadNotifications = unreadCount(notifications);

  /**
   * W11: the driver's commission estimate for the bid being typed, re-asked shortly after the price stops
   * changing. Driver-only by construction (Q16) - this screen is never a client's - and it fails soft: an
   * unavailable estimate must not stop a bid.
   */
  useEffect(() => {
    if (screen !== "driver-bid" || auth.user?.role !== "driver" || !selectedRequest) {
      setFeeQuote(null);
      setFeeQuoteFailed(false);
      return;
    }
    const listing = selectedRequest.listing;
    const total = bidTotalMinor(listing.price_basis, Math.round(Number(bidPrice)) * 100, listing.quantity);
    if (total <= 0) {
      setFeeQuote(null);
      setFeeQuoteFailed(false);
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      void commissionQuote({ service_type: listing.service_type, total_minor: total })
        .then((quote) => { if (active) { setFeeQuote({ quote, totalMinor: total }); setFeeQuoteFailed(false); } })
        .catch(() => { if (active) { setFeeQuote(null); setFeeQuoteFailed(true); } });
    }, 400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [screen, bidPrice, selectedRequest, auth.user?.role]);

  /**
   * D16 / §17.1: an unverified driver takes no new business at all - no bid, no trip, no trip offer.
   *
   * The server is the authority and already refuses with `DRIVER_NOT_ELIGIBLE`, but a screen that lets the
   * driver fill in a price and then fails on send teaches nothing: the driver retries, and the real reason
   * (a document still missing) is never read. So the driver-side screens that start new business refuse
   * first, in words, with the way out on the same screen.
   */
  const driverApproved = driverProfile?.verification_status === "approved";

  /**
   * B3 on either booking screen: the button, the inline confirmation with a reason, and the server's refusal.
   *
   * The confirmation says what happens - the booking closes, the seat is freed, no penalty in the pilot (Q45) -
   * and a pending no-show review is named before the person tries, because only the operator may cancel then
   * (Q7/Q19). The server stays the authority: its refusal is shown here in words, next to the button.
   */
  function renderCancelControls(
    booking: { id: string; version: number; service_status: string; no_show_review?: { status: string } | null },
    side: BookingSide,
  ) {
    const mine = cancelAsk?.bookingId === booking.id;
    const refusal = mine && cancelRefusal ? (
      <p className="rounded-[12px] bg-destructive/10 px-3 py-2.5 text-[13px] leading-5 text-destructive">{cancelRefusal}</p>
    ) : null;
    if (!canCancelBooking(booking.service_status)) return refusal;
    if (cancelBlockedByReview(booking.no_show_review)) {
      return (
        <>
          {refusal}
          <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
            {translate("bookingCancel.reviewPending")}
          </p>
        </>
      );
    }
    if (!mine || cancelRefusal) {
      return (
        <>
          {refusal}
          <SecondaryButton danger disabled={busy} onClick={() => openCancel(booking.id, side, booking.version)}>
            {translate("bookingCancel.button")}
          </SecondaryButton>
        </>
      );
    }
    return (
      <div className="space-y-3 rounded-[16px] border border-destructive/30 bg-card p-4">
        <p className="text-[15px] font-semibold text-foreground">{translate("bookingCancel.title")}</p>
        <p className="text-[13px] leading-5 text-muted-foreground">{translate("bookingCancel.body")}</p>
        <PickSelect
          label={translate("bookingCancel.reasonLabel")}
          placeholder={translate("bookingCancel.reasonLabel")}
          value={cancelReason}
          options={CANCEL_REASONS[side].map((code) => [code, translateDynamic(`bookingCancel.reason.${code}`) ?? code])}
          onChange={setCancelReason}
        />
        <Field
          label={translate("bookingCancel.commentLabel")}
          value={cancelComment}
          multiline
          onChange={setCancelComment}
          hint={translate("app.bookingCancel.commentHint")}
        />
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || !cancelReason}
            onClick={submitCancel}
            className="el-press h-11 flex-1 rounded-[12px] bg-destructive text-[14px] font-semibold text-primary-foreground disabled:opacity-60"
          >
            {translate("bookingCancel.confirm")}
          </button>
          <button
            type="button"
            onClick={() => { setCancelAsk(null); setCancelRefusal(null); }}
            className="el-press h-11 flex-1 rounded-[12px] bg-muted text-[14px] font-semibold text-muted-foreground"
          >
            {translate("bookingCancel.keep")}
          </button>
        </div>
      </div>
    );
  }

  /** What a cancelled booking says about itself: who cancelled, when, and why (the machine code in words). */
  function renderCancelledNote(booking: { cancelled?: { at: string; by_side: string; reason_code: string } | null }) {
    if (!booking.cancelled) return null;
    const who = translateDynamic(`dispute.side.${booking.cancelled.by_side}`) ?? booking.cancelled.by_side;
    const why = translateDynamic(`bookingCancel.reason.${booking.cancelled.reason_code}`) ?? booking.cancelled.reason_code;
    return (
      <p className="text-[13px] leading-5 text-muted-foreground">
        {translate("bookingCancel.cancelledBy")}: {who} · {formatDateTime(booking.cancelled.at)} · {why}
      </p>
    );
  }

  /** The disputes of one booking, each opening its detail (S5). */
  function renderBookingDisputes(bookingId: string) {
    return bookingDisputes.filter((item) => item.booking_id === bookingId).map((item) => (
      <button
        key={item.id}
        type="button"
        onClick={() => void run(() => openDisputeDetail(item.id))}
        className="el-press w-full rounded-[14px] border border-border bg-card p-4 text-left"
      >
        <p className="text-[12px] text-muted-foreground">{translate("dispute.detailTitle")}</p>
        <p className="mt-1 text-[14px] font-medium text-foreground">
          {disputeTypeLabel(item.type)} · {disputeStatusLabel(item.status)}
        </p>
      </button>
    ));
  }

  /**
   * The person on the other side of an accepted booking: reputation, then "Xavfsizlik" (report this booking, block
   * this person). Only a booking carries the counterparty's id (Q43) - nothing here derives one.
   */
  function renderBookingSafety(booking: AnyBooking, side: "client" | "driver") {
    const other = bookingCounterparty(booking, side);
    return (
      <>
        {other && (
          <div className="space-y-2">
            <p className="px-1 text-[13px] font-semibold text-muted-foreground">
              {translate(side === "client" ? "safety.driverTitle" : "safety.clientTitle")}: {other.name}
            </p>
            <ReputationCard userId={other.userId} serviceType={booking.service_type} />
          </div>
        )}
        <div className="space-y-2">
          <p className="px-1 text-[13px] font-semibold text-muted-foreground">{translate("safety.section")}</p>
          <p className="px-1 text-[12px] leading-5 text-muted-foreground">{translate("safety.sectionHint")}</p>
          <ReportForm subjectType="booking" subjectId={booking.id} />
          {other ? (
            <BlockPanel targetUserId={other.userId} labelFor={(id) => (id === other.userId ? other.name : id)} />
          ) : (
            <p className="px-1 text-[12px] leading-5 text-muted-foreground">{translate("safety.counterpartyMissing")}</p>
          )}
        </div>
      </>
    );
  }

  /** L5/L6/L3: the owner's pause, resume and edit buttons under one listing. */
  function renderListingOwnerControls(listing: ListingDTO, back: Screen, after: () => Promise<void>) {
    const actions = ownerListingActions(listing.status);
    if (!actions.canEdit && !actions.canPause && !actions.canResume) return null;
    return (
      <div className="space-y-2">
        {actions.canPause && (
          <>
            <SecondaryButton disabled={busy} onClick={() => setListingPaused(listing, true, after)}>
              {translate("listingOwner.pause")}
            </SecondaryButton>
            <p className="text-[12px] leading-5 text-muted-foreground">{translate("listingOwner.pauseHint")}</p>
          </>
        )}
        {actions.canResume && (
          <PrimaryButton disabled={busy} onClick={() => setListingPaused(listing, false, after)}>
            {translate("listingOwner.resume")}
          </PrimaryButton>
        )}
        {actions.canEdit && (
          <SecondaryButton disabled={busy} onClick={() => void run(() => openListingEdit(listing.id, back))}>
            {translate("listingOwner.edit")}
          </SecondaryButton>
        )}
      </div>
    );
  }

  const content = (() => {
    if (auth.isLoading) {
      return <EmptyState icon={Loader2} title={translate("common.loading")} />;
    }

    if (screen === "splash") {
      return (
        /* The reference client's opening: the envoy's seal presses down, the name settles under it, and the
           caravan thread draws itself from origin to destination. The screen is the calm ground rather than a
           full-bleed blue, so the seal is the one thing that carries colour. */
        <main className="flex flex-1 flex-col items-center justify-between bg-background px-5 py-12">
          <div />
          <div className="flex flex-col items-center gap-5 text-center">
            <div className="anim-stamp relative">
              <div
                className="relative flex h-20 w-20 items-center justify-center rounded-[26px] bg-primary"
                style={{ boxShadow: "var(--shadow-pop)" }}
              >
                <span
                  className="absolute rounded-[18px]"
                  style={{ inset: 9, border: "1.5px solid color-mix(in srgb, var(--primary-foreground) 35%, transparent)" }}
                />
                <Send size={32} weight="fill" className="relative text-primary-foreground" />
              </div>
            </div>
            <div>
              <h1 className="anim-rise stagger-1 font-display text-[26px] font-bold text-foreground">elchi</h1>
              <p className="anim-rise stagger-2 mt-1.5 text-[14px] leading-6 text-muted-foreground">
                {translate("onboarding.tagline")}
              </p>
            </div>
            <div className="anim-fade stagger-2 mt-2 flex items-center" aria-hidden="true">
              <span
                className="h-3 w-3 flex-none rounded-full border-[2.5px]"
                style={{ borderColor: "var(--feruza)", background: "var(--background)" }}
              />
              <span
                className="anim-grow stagger-3 mx-1 h-0.5 w-24"
                style={{
                  background: "repeating-linear-gradient(to right, var(--primary) 0 3px, transparent 3px 8px)",
                  opacity: 0.7,
                }}
              />
              <span
                className="anim-fade stagger-5 h-3 w-3 flex-none"
                style={{ background: "var(--primary)", borderRadius: "50% 50% 50% 3px", transform: "rotate(45deg)" }}
              />
            </div>
          </div>
          <div className="el-fade w-full">
            <PrimaryButton onClick={() => go("onboarding")}>{translate("onboarding.start")}</PrimaryButton>
          </div>
        </main>
      );
    }

    if (screen === "onboarding") {
      // Each step carries its own tint (reference design): the eye reads three different promises, not one
      // screen shown three times.
      const steps = [
        [translate("onboarding.step1Title"), translate("onboarding.step1Text"), MapPin, "var(--accent)", "var(--primary)"],
        [translate("onboarding.step2Title"), translate("onboarding.step2Text"), FileText, "color-mix(in srgb, var(--success) 8%, transparent)", "var(--success)"],
        [translate("onboarding.step3Title"), translate("onboarding.step3Text"), CheckCircle, "color-mix(in srgb, var(--warning) 8%, transparent)", "var(--warning)"],
      ] as const;
      const [title, subtitle, Icon, tint, tone] = steps[onboardingStep];
      const last = onboardingStep === steps.length - 1;
      return (
        <main className="flex flex-1 flex-col bg-card px-8 py-8">
          {/* The wordmark stays on screen through all three promises, so the person always knows whose app
              is making them (reference client). */}
          <div className="anim-fade">
            <ElchiLogo size={36} />
          </div>
          <div className="flex flex-1 flex-col items-center justify-center text-center">
            {/* `key` restarts the entrance on every step, so the icon arrives with its promise. */}
            <div
              key={onboardingStep}
              className="el-pop mb-10 flex h-32 w-32 items-center justify-center rounded-[36px]"
              style={{ background: tint }}
            >
              <Icon size={60} color={tone} />
            </div>
            <div className="mb-8">
              <StepDots step={onboardingStep} total={steps.length} />
            </div>
            <h2 key={`t${onboardingStep}`} className="el-fade text-[22px] font-bold leading-[30px] text-foreground">
              {title}
            </h2>
            <p key={`s${onboardingStep}`} className="el-fade mt-3 text-[15px] leading-6 text-muted-foreground">
              {subtitle}
            </p>
          </div>
          <div className="space-y-2">
            <PrimaryButton onClick={() => (last ? go("role") : setOnboardingStep(onboardingStep + 1))}>
              {last ? translate("onboarding.start") : translate("onboarding.next")}
            </PrimaryButton>
            {!last && <GhostButton onClick={() => go("role")}>{translate("onboarding.skip")}</GhostButton>}
          </div>
        </main>
      );
    }

    if (screen === "role") {
      const roles = [
        ["client", Package, translate("onboarding.roleClient"), translate("onboarding.roleClientHint")],
        ["driver", Truck, translate("onboarding.roleDriver"), translate("onboarding.roleDriverHint")],
      ] as const;
      return (
        <main className="flex flex-1 flex-col bg-background px-5 pb-8 pt-10">
          <button
            type="button"
            onClick={() => go("onboarding")}
            aria-label={translate("common.back")}
            className="el-press mb-6 flex h-9 w-9 items-center justify-center self-start rounded-xl bg-secondary"
          >
            <ChevronLeft size={18} className="text-foreground" />
          </button>
          <div className="anim-fade">
            <ElchiLogo size={36} />
          </div>
          <div className="anim-rise stagger-1 mb-8 mt-6">
            <h2 className="font-display text-[22px] font-bold text-foreground">{translate("onboarding.roleTitle")}</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">{translate("onboarding.roleSubtitle")}</p>
          </div>
          {/* The reference client selects and moves on in one tap: the role is the question this screen asks,
              so a second "continue" only adds a step to answer it twice. */}
          <div className="flex flex-1 flex-col gap-3">
            {roles.map(([role, Icon, label, description], index) => (
              <button
                key={role}
                type="button"
                onClick={() => {
                  setSelectedRole(role as MobileRole);
                  go("phone");
                }}
                style={{ boxShadow: "var(--shadow-card)" }}
                className={cls(
                  "el-press-soft anim-rise flex items-center gap-4 rounded-2xl border border-border bg-card p-5 text-left hover:border-primary/40",
                  index === 0 ? "stagger-2" : "stagger-3",
                )}
              >
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10">
                  <Icon size={26} className="text-primary" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-base font-bold text-foreground">{label}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">{description}</span>
                </span>
                <ChevronRight size={18} className="flex-none text-muted-foreground" />
              </button>
            ))}
          </div>
          <p className="mt-4 text-center text-xs text-muted-foreground">Elchi · UZ · {new Date().getFullYear()}</p>
        </main>
      );
    }

    if (screen === "phone") {
      const phoneDigits = phone.replace(/\D/g, "").replace(/^998/, "");
      const RoleIcon = selectedRole === "driver" ? Truck : Package;
      const submit = () =>
        run(async () => {
          await auth.requestOtp({ phone, role: selectedRole });
          go("otp");
        }, translate("auth.codeSent"));
      return (
        <main className="flex flex-1 flex-col bg-background px-5 pb-8 pt-10">
          <button
            type="button"
            onClick={() => go("role")}
            aria-label={translate("common.back")}
            className="el-press mb-6 flex h-9 w-9 items-center justify-center self-start rounded-xl bg-secondary"
          >
            <ChevronLeft size={18} className="text-foreground" />
          </button>
          {/* Which role is being signed in stays on screen, because it decides what the next screens are. */}
          <div className="anim-fade mb-6 flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/15">
              <RoleIcon size={15} className="text-primary" />
            </span>
            <span className="text-xs font-medium text-muted-foreground">
              <span className="font-semibold text-foreground">
                {selectedRole === "driver" ? translate("dispute.side.driver") : translate("dispute.side.client")}
              </span>{" "}
              {translate("auth.roleSuffix")}
            </span>
          </div>
          <div className="anim-rise stagger-1">
            <h2 className="font-display mb-1.5 text-[22px] font-bold text-foreground">{translate("auth.phoneTitle")}</h2>
            <p className="mb-8 text-sm text-muted-foreground">{translate("auth.phoneSubtitle")}</p>
          </div>
          <div className="anim-rise stagger-2 flex-1">
            <PhoneField value={phoneDigits} onChange={(digits) => setPhone(`+998${digits}`)} onSubmit={submit} />
          </div>
          <PrimaryButton disabled={busy || phoneDigits.length < 9} onClick={submit} icon={Send} busy={busy}>
            {translate("auth.getCode")}
          </PrimaryButton>
        </main>
      );
    }

    if (screen === "otp") {
      const verify = () =>
        run(async () => {
          const user = await auth.loginWithOtp({ phone: normalizeUzPhone(phone), role: selectedRole, otp });
          go(user.role === "driver" ? "driver-home" : "client-home");
        });
      return (
        <main className="flex flex-1 flex-col bg-background px-6 pb-6 pt-6">
          <button
            type="button"
            onClick={() => go("phone")}
            aria-label={translate("common.back")}
            className="el-press flex h-9 w-9 items-center justify-center self-start rounded-xl bg-secondary"
          >
            <ChevronLeft size={18} className="text-foreground" />
          </button>

          <div className="anim-rise mt-6 text-center">
            <h2 className="font-display text-[22px] font-bold text-foreground">{translate("auth.otpTitle")}</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">{translate("auth.otpSentTo")}</p>
            <p className="mt-1 break-all font-mono text-sm font-semibold text-foreground">{phone}</p>
          </div>

          <div className="anim-rise stagger-2 mt-8">
            <CodeField label={translate("auth.otpLabel", { length: OTP_LENGTH })} value={otp} length={OTP_LENGTH} onChange={setOtp} onComplete={verify} />
          </div>

          {import.meta.env.DEV && (
            <p className="mt-3 text-center text-[12px] text-muted-foreground">
              {translate("auth.devCode", { code: import.meta.env.VITE_DEV_OTP || "12345" })}
            </p>
          )}

          <div className="mt-5 flex justify-center">
            {resendIn > 0 ? (
              <p className="font-mono text-xs text-muted-foreground">
                {translate("auth.resendIn", { seconds: resendIn.toString().padStart(2, "0") })}
              </p>
            ) : (
              <button
                type="button"
                onClick={() =>
                  run(async () => {
                    await auth.requestOtp({ phone, role: selectedRole });
                    setResendIn(RESEND_SECONDS);
                  }, translate("auth.codeResent"))
                }
                className="el-press flex items-center gap-1 text-xs font-medium text-primary"
              >
                <RefreshCw size={11} />
                {translate("auth.resendCode")}
              </button>
            )}
          </div>

          <div className="mt-7">
            <PrimaryButton disabled={busy || otp.length !== OTP_LENGTH} onClick={verify} icon={ArrowRight} iconAfter busy={busy}>
              {translate("common.confirm")}
            </PrimaryButton>
          </div>
        </main>
      );
    }


    if (screen === "support") {
      /**
       * Help, ported from the reference client - with one deliberate difference.
       *
       * That client shows a "Call" button to a hard-coded number and the line "Har kuni 09:00 - 21:00". In the
       * pilot there is no answered line: `ELCHI_SUPPORT_PHONE` is empty, so S13 replies `available: false`
       * with no number and no hours (Q87). A call button that rings nowhere, and opening hours nobody keeps,
       * are promises the operation cannot honour - so the number and the hours are shown only when the server
       * says there are any, and otherwise this screen offers the thing that does work: a ticket someone reads.
       */
      const faqs = [
        [
          translate("support.faq1Question"),
          translate("support.faq1Answer"),
        ],
        [
          translate("support.faq2Question"),
          translate("support.faq2Answer"),
        ],
        [
          translate("support.faq3Question"),
          translate("support.faq3Answer"),
        ],
        [
          translate("support.faq4Question"),
          translate("support.faq4Answer"),
        ],
      ] as const;
      const contacts = supportInfo;
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("support.title")} back={() => go(auth.user?.role === "driver" ? "driver-profile" : "client-profile")} />
          <section className="el-enter flex-1 space-y-5 overflow-y-auto px-4 py-4">
            <div className="flex items-start gap-3 rounded-2xl border border-primary/20 bg-primary/10 p-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/15">
                <Headphones size={20} className="text-primary" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-foreground">{translate("support.cardTitle")}</p>
                {contacts?.available && contacts.phone ? (
                  <>
                    {contacts.hours_text && (
                      <p className="mt-0.5 text-xs text-muted-foreground">{contacts.hours_text}</p>
                    )}
                    <a
                      href={`tel:${contacts.phone}`}
                      className="el-press mt-3 inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
                    >
                      <Phone size={15} />
                      {contacts.phone}
                    </a>
                  </>
                ) : (
                  <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                    {translate("support.noPhoneLine")}
                  </p>
                )}
              </div>
            </div>

            <div>
              <SectionLabel>{translate("support.newTicket")}</SectionLabel>
              <div className="rounded-2xl border border-border bg-card p-4">
                <textarea
                  value={supportMessage}
                  onChange={(event) => setSupportMessage(event.target.value)}
                  rows={4}
                  placeholder={translate("support.messagePlaceholder")}
                  className="el-focus w-full resize-none rounded-[12px] border-[1.5px] border-border bg-card p-3 text-[15px] text-foreground outline-none placeholder:text-slate-400"
                />
                <div className="mt-3">
                  <PrimaryButton
                    disabled={busy || supportMessage.trim().length < 5}
                    busy={busy}
                    onClick={() =>
                      run(async () => {
                        await createSupportTicket(
                          { kind: "support", message: supportMessage.trim(), booking_id: null },
                          newIdempotencyKey(),
                        );
                        setSupportMessage("");
                        await loadSupport();
                      }, translate("support.ticketSent"))
                    }
                  >
                    {translate("common.send")}
                  </PrimaryButton>
                </div>
              </div>
            </div>

            {supportTickets.length > 0 && (
              <div>
                <SectionLabel>{translate("support.myTickets")}</SectionLabel>
                <div className="space-y-2">
                  {supportTickets.map((ticket) => (
                    <div key={ticket.id} className="rounded-2xl border border-border bg-card p-4">
                      <div className="flex items-center justify-between gap-3">
                        <StatusBadge status={ticket.status} />
                        <span className="font-mono text-[11px] text-muted-foreground">{shortDate(ticket.created_at)}</span>
                      </div>
                      {ticket.message && (
                        <p className="mt-2 break-words text-[13px] leading-5 text-foreground">{ticket.message}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <SectionLabel>{translate("support.faqTitle")}</SectionLabel>
              <div className="flex flex-col gap-2">
                {faqs.map(([question, answer]) => (
                  <FaqItem key={question} question={question} answer={answer} />
                ))}
              </div>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "settings") {
      /**
       * Settings, ported from the reference client's panel.
       *
       * Its notification toggles are not here. That panel keeps them in component state, so they look like
       * preferences and are forgotten on the next launch; and there is no push provider yet (Q82), so the only
       * channel is the in-app inbox, which cannot be switched off without silencing the product. A switch that
       * remembers nothing and controls nothing is worse than no switch.
       *
       * The language picker is here since the screen copy moved into the dictionary (`scripts/i18n_coverage.py`
       * measures what is left). The choice is per device, like the theme; staff screens stay Uzbek.
       */
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("settingsScreen.title")} back={() => go(auth.user?.role === "driver" ? "driver-profile" : "client-profile")} />
          <section className="el-enter flex-1 space-y-5 overflow-y-auto px-4 py-4 pb-8">
            <div>
              <SectionLabel>{translate("settingsScreen.appearance")}</SectionLabel>
              <div className="rounded-2xl border border-border bg-card p-4">
                <AppearancePicker />
              </div>
            </div>

            <div>
              <SectionLabel>{translate("settings.language")}</SectionLabel>
              <div className="rounded-2xl border border-border bg-card p-4">
                <p className="mb-3 text-xs text-muted-foreground">{translate("settings.languageHint")}</p>
                <div className="grid grid-cols-2 gap-2" role="group" aria-label={translate("settings.language")}>
                  {LOCALES.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      lang={option.value}
                      aria-pressed={locale === option.value}
                      onClick={() => setLocale(option.value)}
                      className={
                        locale === option.value
                          ? "el-press rounded-xl border border-primary bg-primary/10 px-3 py-3 text-sm font-semibold text-primary"
                          : "el-press rounded-xl border border-border bg-secondary/50 px-3 py-3 text-sm font-semibold text-foreground"
                      }
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div>
              <SectionLabel>{translate("settingsScreen.account")}</SectionLabel>
              <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
                <button
                  type="button"
                  onClick={() => go("support")}
                  className="el-press flex w-full items-center gap-3 px-4 py-3.5 text-left"
                >
                  <IconTile icon={Headphones} size={34} />
                  <span className="flex-1 text-sm font-medium text-foreground">{translate("support.title")}</span>
                  <ChevronRight size={16} className="text-muted-foreground" />
                </button>
                <a
                  href="/privacy"
                  className="el-press flex w-full items-center gap-3 px-4 py-3.5 text-left"
                >
                  <IconTile icon={Shield} size={34} />
                  <span className="flex-1 text-sm font-medium text-foreground">{translate("settingsScreen.privacy")}</span>
                  <ChevronRight size={16} className="text-muted-foreground" />
                </a>
              </div>
            </div>

            <div className="overflow-hidden rounded-2xl border border-border bg-card">
              <button
                type="button"
                onClick={() => run(async () => { await auth.logout(); go("role"); })}
                className="el-press flex w-full items-center gap-3 px-4 py-3.5 text-left"
              >
                <IconTile icon={LogOut} size={34} tone="danger" />
                <span className="flex-1 text-sm font-medium text-destructive">{translate("settingsScreen.logout")}</span>
              </button>
            </div>

            <p className="text-center text-[10px] text-muted-foreground">Elchi · {APP_VERSION}</p>
          </section>
        </main>
      );
    }

    if (screen === "client-home") {
      return (
        <main className="relative flex flex-1 flex-col overflow-hidden bg-border">
          <ClientMapCanvas
            pickupLat={orderForm.pickup_lat}
            pickupLng={orderForm.pickup_lng}
            dropoffLat={orderForm.dropoff_lat}
            dropoffLng={orderForm.dropoff_lng}
            routePolyline={preview?.route_polyline}
          />
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between px-5 pt-4">
            <SidebarButton className="pointer-events-auto" onClick={() => setSidebarOpen(true)} />
            <button
              type="button"
              onClick={() => void useCurrentLocation()}
              disabled={locating}
              className="el-press pointer-events-auto flex h-11 w-11 items-center justify-center rounded-full bg-card text-primary shadow-lg disabled:text-slate-400"
              aria-label={translate("home.currentLocation")}
              aria-busy={locating}
            >
              <LocateFixed size={20} />
            </button>
          </div>
          <section className="absolute inset-x-0 bottom-0 z-10 rounded-t-[26px] bg-card px-5 pb-5 pt-4 shadow-[0_-10px_30px_rgba(15,23,42,0.18)]">
            <div className="mx-auto mb-4 h-1.5 w-20 rounded-full bg-slate-300" />
            {/* Q89: the passenger service is built but stays behind its flag (K7). With the flag off there is
                no toggle at all - not a disabled one that invites a support call - and then the heading has to
                name the mode, because nothing else does. */}
            {pendingCode() && (
              <button
                type="button"
                onClick={() => go("client-bonus")}
                className="el-press mb-3 w-full rounded-[14px] border border-primary/30 bg-accent px-4 py-3 text-left text-[13px] font-semibold text-primary"
              >
                {translate("home.referralCodeSaved", { code: pendingCode() ?? "" })}
              </button>
            )}
            {flags?.passenger_enabled ? (
              <div className="mb-4">
                <SegmentedControl
                  value={serviceMode}
                  options={[["passenger", translate("home.modeTaxi")], ["parcel", translate("home.modeParcel")]] as const}
                  onChange={setServiceMode}
                />
              </div>
            ) : (
              <h1 className="mb-4 text-[22px] font-bold text-foreground">{translate("home.modeParcel")}</h1>
            )}
            <div className="overflow-hidden rounded-[18px] border border-border bg-card">
              <LocationPointRow
                label={translate("direction.from")}
                title={pickupEnd.region?.name_uz}
                address={orderForm.pickup_address}
                hasPoint={hasLocation(orderForm.pickup_lat, orderForm.pickup_lng)}
                onClick={() => openLocationSelector("pickup")}
                node="origin"
              />
              <DirectionLink />
              <LocationPointRow
                label={translate("direction.to")}
                title={dropoffEnd.region?.name_uz}
                address={orderForm.dropoff_address}
                hasPoint={hasLocation(orderForm.dropoff_lat, orderForm.dropoff_lng)}
                onClick={() => openLocationSelector("dropoff")}
                node="destination"
              />
            </div>
            {previewBusy && (
              <div className="mt-3 rounded-[14px] bg-muted px-4 py-3">
                <p className="text-[13px] text-muted-foreground">{translate("home.checkingRoute")}</p>
              </div>
            )}
            {!previewBusy && previewError && (
              <div className="mt-3 rounded-[14px] bg-destructive/10 px-4 py-3">
                <p className="text-[13px] font-semibold leading-5 text-destructive">{previewError}</p>
                <p className="mt-1 text-[12px] leading-5 text-destructive">
                  {translate("home.movePointHint")}
                </p>
              </div>
            )}
            {!previewBusy && preview && (
              /* The numbers are the **leg between the two marked places**, not the corridor. A corridor can
                 be 2 316 km long while this trip is 247 km, and putting the corridor's length above a price
                 field is simply a wrong number in front of a decision. The corridor's own name and the
                 districts it passes are context, so they sit underneath in muted type. */
              <div className="mt-3 rounded-[14px] bg-accent px-4 py-3">
                <p className="text-[20px] font-bold leading-7 text-foreground">
                  {formatKm(preview.leg_distance_m)} · {formatDuration(preview.leg_duration_s)}
                </p>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  {translate("home.estimatedTime", { corridor: preview.corridor_name })}
                </p>
                {offRouteNote && <p className="mt-1.5 text-[12px] leading-5 text-warning">{offRouteNote}</p>}
              </div>
            )}
            {!previewBusy && !preview && !previewError && directionReady && (
              <div className="mt-3 rounded-[14px] bg-accent px-4 py-3">
                <p className="text-[12px] font-semibold text-primary">{translate("home.routeDistricts")}</p>
                <p className="mt-0.5 text-[15px] font-semibold text-foreground">
                  {routeDistricts.filter((item) => item.on_confirmed_route).map((item) => item.district.name_uz).join(" - ") || translate("home.routeLoading")}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                  {translate("home.districtDriversNote")}
                </p>
              </div>
            )}
            {/* No counts here. This sheet asks one question - where to and where from - and a tally of
                listings, proposals and finished orders answers a different one. It lives on "Buyurtmalar",
                which is where somebody goes when that is what they want to know. */}
            <div className="mt-4">
              {/* The gate has to follow the chosen mode: it used to read `parcel_enabled` even with Taksi
                  selected, so a closed parcel service would have disabled the passenger flow too - and the
                  sentence under it would have named the wrong service. */}
              <PrimaryButton disabled={!directionReady || serviceClosed} onClick={() => go("client-route-summary")}>
                {translate("home.viewRoute")}
              </PrimaryButton>
              {serviceClosed && (
                <p className="mt-2 text-center text-[12px] leading-5 text-destructive">
                  {serviceMode === "passenger"
                    ? translate("home.passengerClosed")
                    : translate("home.parcelClosed")}
                </p>
              )}
              {/* Q92: ELCHI is a market in both directions. The button above publishes this client's own
                  request with their own price; answering a driver who published theirs is the other way in,
                  and it now has its own place in the drawer rather than a second button under this one. */}
              {pickupEnd.stop && dropoffEnd.stop && pickupEnd.stop.id === dropoffEnd.stop.id && (
                <p className="mt-2 text-center text-[12px] leading-5 text-destructive">
                  {translate("home.sameStop")}
                </p>
              )}
              {pickupEnd.stop && dropoffEnd.stop && !sameCorridor && (
                <p className="mt-2 text-center text-[12px] leading-5 text-destructive">
                  {translate("home.noConfirmedRoute")}
                </p>
              )}
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-offers") {
      const offerSections = splitFeedGroups(offerFeed);
      const offerCard = (item: FeedItemDTO, isAlternative = false) => {
        const reason = isAlternative ? alternativeReasonLabel(item.match.reasons) : null;
        return (
          <div
            key={item.listing.id}
            className={cls(
              "rounded-[16px] border bg-card p-4",
              isAlternative ? "border-dashed border-muted-foreground/40" : "border-border",
            )}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                <MapPin size={14} color="var(--primary)" />
                {endLabel(item.listing.origin_stop, item.listing.origin_point)} {"->"} {endLabel(item.listing.destination_stop, item.listing.destination_point)}
              </span>
              <span
                className={cls(
                  "shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold",
                  isAlternative ? "bg-warning/14 text-warning" : "bg-accent text-primary",
                )}
              >
                {reason ?? matchLabel(item.match.match_type)}
              </span>
            </div>
            <div className="flex items-center justify-between text-[13px] text-muted-foreground">
              <span>{shortDate(item.listing.departure_window_start)}</span>
              <span className="font-semibold text-foreground">
                {formatUzs(item.listing.unit_price_minor / 100)}
                {item.listing.price_basis === "per_seat" ? ` / ${translate("common.seat")}` : ""}
              </span>
            </div>
            {/* Section 8.2 / AC36: no invented 4.5 for a driver nobody has rated - the label is the server's. */}
            <p className="mt-1 text-[12px] text-muted-foreground">
              {item.reputation.average_rating !== null
                ? translate("offers.driverPriceRated", {
                    count: item.reputation.completed_bookings,
                    rating: String(item.reputation.average_rating),
                  })
                : translate("offers.driverPriceUnrated", { count: item.reputation.completed_bookings })}
            </p>
            <button
              type="button"
              onClick={() => openOfferBid(item)}
              className={cls(
                "el-press mt-3 h-10 w-full rounded-[10px] text-[14px] font-semibold",
                isAlternative ? "border border-primary text-primary" : "bg-primary text-primary-foreground",
              )}
            >
              {translate("offers.makeOffer")}
            </button>
          </div>
        );
      };
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("offers.title")} back={() => go("client-home")} />
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <TripIntentSummary
              intent={activeIntent}
              others={myIntents}
              loading={intentLoading}
              error={intentError}
              busy={busy}
              onEdit={openIntentEditor}
              onNew={startNewIntent}
              onReopen={reopenActiveIntent}
              onRetry={() => void loadIntents()}
              onSelect={selectIntent}
            />
            <p className="text-[13px] leading-5 text-muted-foreground">
              {(activeIntent?.status === "active" ? activeIntent.service_type : serviceMode) === "passenger"
                ? translate("offers.introPassenger")
                : translate("offers.introParcel")}
            </p>
            {matchScope === "confirmed_stops" && (offerFeed.length > 0) && (
              <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
                {confirmedStopsNote()}
              </p>
            )}
            {busy && !offerFeed.length ? <ListSkeleton /> : offerFeed.length ? (
              <>
                {offerSections.primary.map((item) => offerCard(item))}
                {offerSections.alternative.length > 0 && (
                  <div className="pt-2">
                    <h2 className="text-[16px] font-bold text-foreground">{translate("match.alternativesTitle")}</h2>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      {translate("match.alternativesNote")}
                    </p>
                  </div>
                )}
                {offerSections.alternative.map((item) => offerCard(item, true))}
              </>
            ) : (
              <EmptyState
                icon={Truck}
                title={translate("offers.emptyTitle")}
                subtitle={translate("offers.emptySubtitle")}
                action={translate("offers.emptyAction")}
                onAction={() => go("client-home")}
              />
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-offer-bid" && selectedOffer) {
      const offer = selectedOffer.listing;
      const perSeat = offer.price_basis === "per_seat";
      // ADR-0025: with a saved request the number of people is the request's, the same for every driver.
      const bidIntent = intentFor(offer);
      const intentExpired = bidIntent ? bidIntent.expired || isExpired(bidIntent) : false;
      const seats = bidIntent ? bidIntent.current_version.quantity : perSeat ? Math.max(1, offerBid.seats) : 1;
      const priceSoum = Math.round(Number(offerBid.price));
      const requestPrice = bidIntent?.current_version.unit_price_minor ? bidIntent.current_version : null;
      const priceFromRequest = bidIntent ? prefillBid(bidIntent, offer).priceFromRequest : false;
      const parcelNeeded = offer.service_type === "parcel";
      const parcelReady = !parcelNeeded || Boolean(
        Number(offerBid.weightKg) > 0 && Number(offerBid.lengthCm) > 0 && Number(offerBid.widthCm) > 0
        && Number(offerBid.heightCm) > 0 && offerBid.receiverName.trim() && offerBid.receiverPhone.trim(),
      );
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("offers.makeOffer")} back={() => go("client-offers")} />
          <section className="el-enter flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
            {bidIntent && (
              <div className="rounded-[14px] border border-primary/30 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{translate("offerBid.yourRequest")}</p>
                <p className="mt-0.5 text-[14px] font-semibold leading-5 text-foreground">{intentSummary(bidIntent)}</p>
                <div className="mt-1.5 flex gap-4">
                  <button type="button" onClick={openIntentEditor} className="el-press text-[13px] font-semibold text-primary">
                    {translate("listingOwner.edit")}
                  </button>
                  <button type="button" onClick={startNewIntent} className="el-press text-[13px] font-semibold text-muted-foreground">
                    {translate("offerBid.newIntent")}
                  </button>
                </div>
              </div>
            )}
            {bidIntent && intentExpired && (
              <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
                {translate("offerBid.intentExpired")}
              </p>
            )}
            {bidIntent && <TripIntentFitNotes fit={intentFit} loading={intentFitLoading} />}
            <div className="rounded-[14px] bg-background p-4">
              <p className="font-semibold text-foreground">
                {endLabel(offer.origin_stop, offer.origin_point)} {"->"} {endLabel(offer.destination_stop, offer.destination_point)}
              </p>
              {/* The driver's advertised price and the client's own offer are two lines, never one number. */}
              <p className="mt-1 text-[13px] text-muted-foreground">
                {translate("offerBid.driverPrice", {
                  price: bidIntent
                    ? priceLine(offer.price_basis, offer.unit_price_minor, seats)
                    : `${formatUzs(offer.unit_price_minor / 100)}${perSeat ? ` / ${translate("common.seat")}` : ""}`,
                })}
              </p>
              <p className="mt-1 text-[13px] text-muted-foreground">
                {translate("offerBid.departure", {
                  from: shortDate(offer.departure_window_start),
                  to: shortDate(offer.departure_window_end),
                })}
              </p>
            </div>

            {bidIntent && bidIntent.service_type === "passenger" && (
              <p className="text-[13px] text-secondary-foreground">
                {translate("offerBid.peopleLabel")}{" "}
                <span className="font-semibold">{translate("offerBid.peopleCount", { count: seats })}</span>{" "}
                {translate("offerBid.peopleFromIntent")}
              </p>
            )}
            {perSeat && !bidIntent && (
              <Field
                label={translate("offerBid.seatsLabel")}
                type="number"
                value={String(offerBid.seats)}
                onChange={(value) => setOfferBid({ ...offerBid, seats: Math.max(1, Math.min(8, Number(value) || 1)) })}
              />
            )}
            <Field
              label={perSeat ? translate("offerBid.pricePerSeatLabel") : translate("offerBid.priceLabel")}
              type="number"
              value={offerBid.price}
              onChange={(value) => setOfferBid({ ...offerBid, price: value })}
              placeholder={translate("offerBid.pricePlaceholder")}
            />
            {bidIntent && priceSoum > 0 ? (
              <p className="text-[13px] font-semibold leading-5 text-foreground">
                {translate("offerBid.yourOffer", { price: priceLine(offer.price_basis, priceSoum * 100, seats) })}
              </p>
            ) : perSeat && priceSoum > 0 ? (
              <p className="text-[12px] leading-5 text-muted-foreground">
                {translate("offerBid.totalForSeats", { seats, total: formatUzs(priceSoum * seats) })}
              </p>
            ) : null}
            {bidIntent && requestPrice && !priceFromRequest && (
              <p className="text-[12px] leading-5 text-muted-foreground">
                {translate("offerBid.requestPriceOtherBasis", {
                  price: priceLine(requestPrice.price_basis ?? "total", requestPrice.unit_price_minor ?? 0, seats),
                })}
              </p>
            )}
            {bidIntent && (
              <p className="text-[12px] leading-5 text-muted-foreground">
                {translate("offerBid.priceOnlyForDriver")}
              </p>
            )}

            {parcelNeeded && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Field label={translate("offerBid.weightKg")} type="number" value={offerBid.weightKg} onChange={(v) => setOfferBid({ ...offerBid, weightKg: v })} />
                  <Field label={translate("offerBid.lengthCm")} type="number" value={offerBid.lengthCm} onChange={(v) => setOfferBid({ ...offerBid, lengthCm: v })} />
                  <Field label={translate("offerBid.widthCm")} type="number" value={offerBid.widthCm} onChange={(v) => setOfferBid({ ...offerBid, widthCm: v })} />
                  <Field label={translate("offerBid.heightCm")} type="number" value={offerBid.heightCm} onChange={(v) => setOfferBid({ ...offerBid, heightCm: v })} />
                </div>
                {/* W21-4 (Q79): a trip-offer parcel needs a receiver before pickup, and only the sender can give
                    one - asked for here, where it can still be fixed, not at the driver's `pick_up`. */}
                <Field label={translate("offerBid.receiverName")} value={offerBid.receiverName} onChange={(v) => setOfferBid({ ...offerBid, receiverName: v })} />
                <Field label={translate("offerBid.receiverPhone")} value={offerBid.receiverPhone} onChange={(v) => setOfferBid({ ...offerBid, receiverPhone: v })} placeholder="+998..." />
                <ParcelPolicyNotice />
              </>
            )}

            <BonusConsentPanel
              listingId={offer.id}
              unitPriceMinor={priceSoum * 100}
              quantity={seats}
              choice={offerConsent}
              onChoice={setOfferConsent}
              refreshToken={consentRefresh}
            />

            {/* Section 5.3: an offer reserves nothing. Saying so here is what stops "men taklif berdim" from
                reading as "joy band qilindi". */}
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("offerBid.reservesNothing")}
            </p>

            <div className="mt-auto">
              <PrimaryButton
                disabled={priceSoum <= 0 || !parcelReady || !offer.origin_stop || !offer.destination_stop || busy
                  || intentExpired || fitBlocks(bidIntent ? intentFit : null)}
                onClick={() => void run(async () => {
                  if (!offer.origin_stop || !offer.destination_stop) return;
                  // ADR-0025: parcel data typed here belongs to the request, so it is saved there first and every
                  // later driver's screen starts with it. A material change with open offers asks before closing them.
                  let intent = bidIntent;
                  if (intent && parcelNeeded && parcelDiffers(intent, offerBid)) {
                    intent = await sendIntentEdit(updateBody(intent, { parcel: parcelInput(offerBid) }), "client-offer-bid");
                    if (!intent) return;
                  }
                  const intentParcel = intent?.current_version.parcel ?? null;
                  const promo = consentBody(offerConsent);
                  await submitProposal(
                    offer.id,
                    {
                      // The trip is the offer's own; the window is the one it advertises, which the server
                      // checks against that trip's real ETA at the pickup stop.
                      trip_id: offer.trip_id ?? null,
                      pickup_stop_id: offer.origin_stop.id,
                      dropoff_stop_id: offer.destination_stop.id,
                      pickup_window_start: offer.departure_window_start,
                      pickup_window_end: offer.departure_window_end,
                      price_basis: offer.price_basis,
                      quantity: seats,
                      unit_price_minor: priceSoum * 100,
                      parcel: parcelNeeded
                        ? intentParcel
                          ? {
                              parcel_type: intentParcel.parcel_type ?? null,
                              weight_g: intentParcel.weight_g ?? 0,
                              length_cm: intentParcel.length_cm ?? 0,
                              width_cm: intentParcel.width_cm ?? 0,
                              height_cm: intentParcel.height_cm ?? 0,
                              receiver: intentParcel.receiver ?? null,
                            }
                          : {
                              weight_g: Math.round(Number(offerBid.weightKg) * 1000),
                              length_cm: Math.round(Number(offerBid.lengthCm)),
                              width_cm: Math.round(Number(offerBid.widthCm)),
                              height_cm: Math.round(Number(offerBid.heightCm)),
                              receiver: { name: offerBid.receiverName.trim(), phone: offerBid.receiverPhone.trim() },
                            }
                        : null,
                      ...(intent ? { trip_intent: { id: intent.id, version_no: intent.current_version.version_no } } : {}),
                      ...(promo ? { promo_consent: promo } : {}),
                    },
                    newIdempotencyKey(),
                  ).catch((cause) => {
                    requoteOn(cause);
                    if ((cause as { code?: string }).code?.startsWith("TRIP_INTENT")) void loadIntents();
                    throw cause;
                  });
                  if (intent) rememberIntent({ ...intent, open_offers: intent.open_offers + 1 });
                  setOfferConsent(NO_CONSENT);
                  await loadOfferFeed();
                  go("client-proposals");
                }, translate("offerBid.sent"))}
              >
                {translate("offerBid.submit")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-intent-edit") {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar
            title={activeIntent?.service_type === "parcel" ? translate("offerBid.parcelRequestTitle") : translate("offerBid.tripRequestTitle")}
            back={() => go("client-offers")}
          />
          {activeIntent ? (
            <TripIntentEditor
              key={`${activeIntent.id}:${activeIntent.version}`}
              intent={activeIntent}
              busy={busy}
              onSave={saveIntentEdit}
              onChangeRoute={editIntentRoute}
              onClose={closeActiveIntent}
            />
          ) : (
            <EmptyState icon={MapPin} title={translate("offerBid.noSavedRequest")} action={translate("offerBid.newIntent")} onAction={startNewIntent} />
          )}
        </main>
      );
    }

    if (screen === "client-location-selector") {
      const selectorTitle = locationSelectorMode === "pickup" ? translate("direction.from") : translate("direction.to");
      return (
        <RegionSelector
          title={selectorTitle}
          onSelectRegion={selectRegionForLocation}
          onBack={() => go(directionOwner === "driver" ? "driver-feed" : "client-home")}
        />
      );
    }

    if (screen === "client-district-selector" && activeEnd.region) {
      return (
        <GeoDistrictSelector
          region={activeEnd.region}
          onSelectDistrict={selectGeoDistrict}
          onBack={() => go("client-location-selector")}
        />
      );
    }

    if (screen === "client-point-picker") {
      const title = locationSelectorMode === "pickup" ? translate("direction.from") : translate("direction.to");
      return (
        <MapPointPicker
          title={title}
          initial={activeEnd.point}
          districtCenter={mapCentreFor(activeEnd)}
          districtName={[activeEnd.district?.name_uz, activeEnd.region?.name_uz].filter(Boolean).join(", ")}
          searchDistrict={activeEnd.district?.name_uz ?? activeEnd.region?.name_uz ?? null}
          maxOffsetM={preview?.max_point_offset_m ?? null}
          routeError={previewError}
          busy={previewBusy}
          stops={stopOptions}
          onSelectStop={(option) => selectGeoStop(option.stop, option.corridorId)}
          onConfirm={(point) => void markPoint(point)}
          onBack={() => go(activeEnd.region?.requires_district ? "client-district-selector" : "client-location-selector")}
        />
      );
    }

    if (screen === "client-route-summary") {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("routeSummary.direction")} back={() => go("client-home")} />
          <section className="el-enter min-h-0 flex-1 overflow-y-auto px-5 py-5">
            <div className="overflow-hidden rounded-[18px] border border-border bg-card">
              {/* A Q88 end is a marked place, so its name is the reverse-geocoded address - the stop name is
                  only there for the minority of ends chosen from the verified catalogue. Reading the stop
                  alone is why every marked place used to render as "Manzil kiritilmagan". */}
              <RouteSummaryRow
                label={translate("routeSummary.pickup")}
                address={pickupEnd.stop?.name_uz ?? pickupEnd.point?.address ?? ""}
                fallback={pickupEnd.point ? coordinateLabel(pickupEnd.point.lat, pickupEnd.point.lng) : undefined}
                city={pickupEnd.region?.name_uz}
                district={pickupEnd.district?.name_uz}
                onEdit={() => openLocationSelector("pickup")}
                icon={Navigation}
              />
              <RouteSummaryRow
                label={translate("routeSummary.dropoff")}
                address={dropoffEnd.stop?.name_uz ?? dropoffEnd.point?.address ?? ""}
                fallback={dropoffEnd.point ? coordinateLabel(dropoffEnd.point.lat, dropoffEnd.point.lng) : undefined}
                city={dropoffEnd.region?.name_uz}
                district={dropoffEnd.district?.name_uz}
                onEdit={() => openLocationSelector("dropoff")}
                icon={MapPin}
              />
            </div>
            {preview && (
              <div className="mt-4 flex items-baseline justify-between gap-3 rounded-[16px] bg-accent px-4 py-3">
                <div>
                  <p className="text-[12px] font-semibold text-primary">{translate("routeSummary.estimatedRoute")}</p>
                  <p className="mt-0.5 text-[18px] font-bold text-foreground">
                    {formatKm(preview.leg_distance_m)} · {formatDuration(preview.leg_duration_s)}
                  </p>
                </div>
                <p className="shrink-0 text-right text-[11px] leading-4 text-muted-foreground">
                  {translate("routeSummary.driverProposesTimeLine1")}
                  <br />
                  {translate("routeSummary.driverProposesTimeLine2")}
                </p>
              </div>
            )}
            {offRouteNote && (
              <p className="mt-2 rounded-[12px] bg-warning/14 px-4 py-3 text-[12px] leading-5 text-warning">
                {offRouteNote}
              </p>
            )}
            <div className="mt-4 overflow-hidden rounded-[16px] border border-border bg-slate-50">
              <RouteMap
                geometryPolyline={routeVersion?.geometry_polyline}
                stops={corridorStops}
                routeStops={routeVersion?.stops ?? []}
                highlight={{ originStopId: pickupEnd.stop?.id, destinationStopId: dropoffEnd.stop?.id }}
                note={translate("routeSummary.mapNote")}
              />
            </div>
            {routeDistricts.length > 0 && (
              <div className="mt-4 rounded-[16px] bg-accent p-4">
                <p className="text-[13px] font-semibold text-primary">{translate("routeSummary.districtsTitle")}</p>
                <p className="mt-1 text-[15px] font-semibold leading-6 text-foreground">
                  {routeDistricts.filter((item) => item.on_confirmed_route).map((item) => item.district.name_uz).join(" - ")}
                </p>
                <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                  {translate("routeSummary.districtsHint")}
                </p>
              </div>
            )}
            <div className="mt-4 space-y-4">
              <Field
                label={translate("listingOwner.windowStart")}
                type="datetime-local"
                min={localNowInputValue()}
                value={listingForm.windowStart}
                onChange={(v) => setListingForm({ ...listingForm, windowStart: v })}
              />
              <Field
                label={translate("listingOwner.windowEnd")}
                type="datetime-local"
                min={listingForm.windowStart || localNowInputValue()}
                hint={translate("routeSummary.windowHint")}
                value={listingForm.windowEnd}
                onChange={(v) => setListingForm({ ...listingForm, windowEnd: v })}
              />
              {serviceMode === "passenger" && (
                <SeatPicker selected={selectedSeats} onChange={setSelectedSeats} />
              )}
              <Field
                label={serviceMode === "passenger" ? translate("routeSummary.pricePerPerson") : translate("listingOwner.priceLabel")}
                type="number"
                placeholder="200000"
                value={listingForm.unitPrice}
                onChange={(v) => setListingForm({ ...listingForm, unitPrice: v })}
              />
              {listingUnitMinor > 0 && (
                <div className="rounded-[14px] bg-accent px-4 py-3">
                  <p className="text-[12px] font-semibold text-primary">{translate("common.total")}</p>
                  <p className="mt-0.5 text-[18px] font-bold text-foreground">
                    {formatUzs((listingUnitMinor * (serviceMode === "passenger" ? seatCount : 1)) / 100)}
                  </p>
                  {serviceMode === "passenger" && seatCount > 1 && (
                    <p className="mt-0.5 text-[12px] text-muted-foreground">
                      {seatCount} × {formatUzs(listingUnitMinor / 100)}
                    </p>
                  )}
                  <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{translate("routeSummary.driversSendOffers")}</p>
                </div>
              )}
            </div>
            <div className="mt-6">
              <PrimaryButton
                disabled={saveBlockers.length > 0}
                onClick={() => go(serviceMode === "passenger" ? "client-order-review" : "client-order-address")}
              >
                {translate("common.save")}
              </PrimaryButton>
              {/* ADR-0025: the same answers, kept privately as a request that fills each driver's offer screen. It
                  is not published and sends nothing by itself; the price is optional here. */}
              <div className="mt-2">
                <SecondaryButton
                  disabled={busy || saveBlockers.some((problem) => problem !== translate("listingOwner.invalid.price"))}
                  onClick={() => void run(saveIntentFromHome)}
                >
                  {intentDraftMode === "edit" && activeIntent?.status === "active" && activeIntent.service_type === serviceMode
                    ? translate("routeSummary.updateRequest")
                    : translate("routeSummary.seeDriverOffers")}
                </SecondaryButton>
              </div>
              {saveBlockers.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {saveBlockers.map((problem) => (
                    <li key={problem} className="text-[12px] leading-5 text-destructive">
                      {problem}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-order-address") {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("orderForm.contactTitle")} back={() => go("client-route-summary")} />
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <div className="rounded-[18px] bg-slate-50 p-4">
              <p className="text-[13px] font-semibold text-muted-foreground">{translate("routeSummary.direction")}</p>
              <p className="mt-1 text-[15px] font-semibold text-foreground">{directionEndLabel(pickupEnd)}</p>
              <p className="mt-1 text-[15px] font-semibold text-foreground">{directionEndLabel(dropoffEnd)}</p>
            </div>
            <Field label={translate("orderForm.senderName")} value={listingForm.senderName} onChange={(v) => setListingForm({ ...listingForm, senderName: v })} />
            <Field label={translate("orderForm.senderPhone")} value={orderForm.sender_phone} placeholder="+998 __ ___ __ __" onChange={(v) => setOrderForm({ ...orderForm, sender_phone: v })} />
            <Field label={translate("orderForm.receiverName")} value={listingForm.receiverName} onChange={(v) => setListingForm({ ...listingForm, receiverName: v })} />
            <Field label={translate("orderForm.receiverPhone")} value={orderForm.receiver_phone} placeholder="+998 __ ___ __ __" onChange={(v) => setOrderForm({ ...orderForm, receiver_phone: v })} />
            <Field label={translate("listingOwner.commentLabel")} value={orderForm.comment ?? ""} multiline onChange={(v) => setOrderForm({ ...orderForm, comment: v })} />
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("orderForm.phonesHidden")}
            </p>
            <PrimaryButton
              disabled={
                !orderForm.sender_phone
                || !orderForm.receiver_phone
                || !listingForm.senderName.trim()
                || !listingForm.receiverName.trim()
              }
              onClick={() => go("client-order-parcel")}
            >
              {translate("common.continue")}
            </PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "client-order-parcel") {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("orderForm.parcelTitle")} back={() => go("client-order-address")} />
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <div className="flex flex-col gap-1.5">
              <span className="text-[14px] font-medium text-secondary-foreground">{translate("orderForm.parcelType")}</span>
              <div className="grid grid-cols-3 gap-2">
                {PARCEL_TYPES.map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setListingForm({ ...listingForm, parcelType: value })}
                    className={
                      listingForm.parcelType === value
                        ? "el-press h-11 rounded-[12px] border border-primary bg-primary text-[14px] font-semibold text-primary-foreground"
                        : "el-press h-11 rounded-[12px] border border-border bg-card text-[14px] font-semibold text-foreground"
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <Field label={translate("orderForm.weight")} type="number" placeholder="3" value={listingForm.weightKg} onChange={(v) => setListingForm({ ...listingForm, weightKg: v })} />
            <div className="grid grid-cols-3 gap-2">
              <Field label={translate("orderForm.length")} type="number" placeholder="40" value={listingForm.lengthCm} onChange={(v) => setListingForm({ ...listingForm, lengthCm: v })} />
              <Field label={translate("orderForm.width")} type="number" placeholder="30" value={listingForm.widthCm} onChange={(v) => setListingForm({ ...listingForm, widthCm: v })} />
              <Field label={translate("orderForm.height")} type="number" placeholder="20" value={listingForm.heightCm} onChange={(v) => setListingForm({ ...listingForm, heightCm: v })} />
            </div>
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("orderForm.sizeHint")}
            </p>
            <ParcelPolicyNotice />
            <PrimaryButton disabled={!parcelReady} onClick={() => go("client-order-photo")}>
              {translate("common.continue")}
            </PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "client-order-photo") {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("orderForm.photoTitle")} back={() => go("client-order-parcel")} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <label className="flex cursor-pointer flex-col items-center justify-center rounded-[16px] border border-dashed border-primary bg-accent p-8 text-center">
              <Upload size={30} color="var(--primary)" />
              <span className="mt-3 text-[16px] font-semibold text-foreground">{translate("orderForm.uploadPhoto")}</span>
              <span className="mt-1 text-[13px] text-muted-foreground">{translate("orderForm.uploadPhotoHint")}</span>
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  void run(async () => {
                    const uploaded = await uploadFile(file, "cargo_photo");
                    setOrderForm((current) => ({ ...current, cargo_photo_url: uploaded.file_url }));
                  }, translate("orderForm.photoUploaded"));
                }}
              />
            </label>
            {orderForm.cargo_photo_url && (
              <div className="space-y-2">
                {/* The upload returns a signed link: render it, never print it - a URL with a signature in it
                    is a credential, not a label. */}
                <img src={orderForm.cargo_photo_url} alt={translate("orderForm.photoAlt")} className="h-[180px] w-full rounded-[12px] object-cover" />
                <p className="text-[13px] text-success">{translate("orderForm.photoReady")}</p>
              </div>
            )}
            {!orderForm.cargo_photo_url && <p className="text-[13px] text-destructive">{translate("orderForm.photoRequired")}</p>}
            <div className="mt-auto">
              <PrimaryButton disabled={!orderForm.cargo_photo_url} onClick={() => go("client-order-review")}>
                {translate("orderForm.reviewOrder")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-order-review") {
      const passengerMode = serviceMode === "passenger";
      const canPublish = Boolean(
        directionReady
        && listingForm.windowStart
        && listingForm.windowEnd
        && listingUnitMinor > 0
        && (passengerMode
          || (parcelReady
            && orderForm.sender_phone
            && orderForm.receiver_phone
            && listingForm.senderName.trim()
            && listingForm.receiverName.trim())),
      );

      return (
        <main className="relative flex min-h-0 flex-1 flex-col bg-background">
          <TopBar
            title={translate("orderForm.review.title")}
            back={() => go(passengerMode ? "client-route-summary" : "client-order-photo")}
          />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            {/* Every row carries a fact or it is not here.
                This screen used to print "-" three times over: two stop rows, which a Q88 direction never
                has because its ends are marked places, and the districts on the route, which were read from
                a corridor id that only a stop end ever sets. A review that shows a dash is asking somebody
                to confirm something it did not manage to tell them. */}
            {(() => {
              const endRow = (label: string, end: DirectionEnd): [string, string, string?] => {
                const place =
                  end.stop?.name_uz
                  || end.point?.address
                  || (end.point ? coordinateLabel(end.point.lat, end.point.lng) : "");
                const where = [end.district?.name_uz, end.region?.name_uz].filter(Boolean).join(", ");
                return [label, place || where || "-", end.stop ? translate("orderForm.review.verifiedStop", { where }) : where];
              };
              // The districts come from the preview, which is the answer for *these two places*; the
              // corridor-wide list is only populated when an end was picked from the stop catalogue.
              const onRoute =
                (preview?.districts_on_route ?? []).join(" - ")
                || routeDistricts.filter((item) => item.on_confirmed_route).map((item) => item.district.name_uz).join(" - ");
              const totalMinor = listingUnitMinor * (passengerMode ? seatCount : 1);

              const rows: Array<[string, string, string?]> = [
                [
                  translate("routeSummary.direction"),
                  `${pickupEnd.region?.name_uz ?? "-"} -> ${dropoffEnd.region?.name_uz ?? "-"}`,
                  preview?.corridor_name,
                ],
                endRow(translate("orderForm.review.pickupPlace"), pickupEnd),
                endRow(translate("orderForm.review.dropoffPlace"), dropoffEnd),
              ];
              if (preview) {
                rows.push([
                  translate("routeSummary.estimatedRoute"),
                  `${formatKm(preview.leg_distance_m)} · ${formatDuration(preview.leg_duration_s)}`,
                  offRouteNote ?? undefined,
                ]);
              }
              if (onRoute) rows.push([translate("routeSummary.districtsTitle"), onRoute, translate("orderForm.review.districtsDetail")]);
              rows.push([
                translate("orderForm.review.window"),
                `${formatWindowInput(listingForm.windowStart)} - ${formatWindowInput(listingForm.windowEnd)}`,
              ]);
              rows.push(
                passengerMode
                  ? [translate("common.price"), formatUzs(totalMinor / 100), translate("orderForm.review.perPersonDetail", { count: seatCount, price: formatUzs(listingUnitMinor / 100) })]
                  : [translate("common.price"), formatUzs(totalMinor / 100), translate("orderForm.review.driversSendOffers")],
              );
              if (passengerMode) {
                rows.push([translate("orderForm.review.passengers"), translate("orderForm.review.peopleCount", { count: seatCount }), translate("orderForm.review.seatNegotiated")]);
              } else {
                const parcelName = PARCEL_TYPES.find(([value]) => value === listingForm.parcelType)?.[1] ?? "-";
                rows.push([
                  translate("orderForm.review.parcel"),
                  translate("orderForm.review.parcelWeight", { type: parcelName, weight: listingForm.weightKg || "-" }),
                  translate("orderForm.review.parcelSize", { length: listingForm.lengthCm || "-", width: listingForm.widthCm || "-", height: listingForm.heightCm || "-" }),
                ]);
                rows.push([translate("orderForm.review.sender"), listingForm.senderName || "-", orderForm.sender_phone || translate("orderForm.review.noPhone")]);
                rows.push([translate("orderForm.review.receiver"), listingForm.receiverName || "-", orderForm.receiver_phone || translate("orderForm.review.noPhone")]);
                rows.push([translate("orderForm.photoTitle"), orderForm.cargo_photo_url ? translate("orderForm.review.uploaded") : translate("docState.missing")]);
              }
              if (orderForm.comment) rows.push([translate("listingOwner.commentLabel"), orderForm.comment]);

              return rows.map(([label, value, detail]) => (
                <div key={label} className="rounded-[14px] border border-border bg-card p-4">
                  <p className="text-[12px] text-muted-foreground">{label}</p>
                  <p className="mt-1 break-words text-[15px] font-semibold leading-6 text-foreground">{value}</p>
                  {detail && <p className="mt-0.5 break-words text-[12px] leading-5 text-muted-foreground">{detail}</p>}
                </div>
              ));
            })()}
          </section>
          <div className="absolute inset-x-0 bottom-0 z-20 border-t border-border bg-card px-5 py-4 shadow-[0_-8px_20px_rgba(15,23,42,0.08)]">
            {!canPublish && (
              <p className="mb-2 text-center text-[12px] leading-5 text-destructive">
                {passengerMode
                  ? translate("orderForm.review.incompletePassenger")
                  : translate("orderForm.review.incompleteParcel")}
              </p>
            )}
            <PrimaryButton
              disabled={busy || !canPublish}
              onClick={() => void run(publishListingDraft)}
            >
              {translate("orderForm.review.publish")}
            </PrimaryButton>
            <button
              type="button"
              onClick={() => go(passengerMode ? "client-route-summary" : "client-order-address")}
              className="el-press mt-3 h-10 w-full text-[14px] font-semibold text-primary"
            >
              {translate("listingOwner.edit")}
            </button>
          </div>
        </main>
      );
    }

    if (screen === "client-success") {
      return (
        <main className="flex flex-1 flex-col items-center justify-center bg-card px-6 text-center">
          <CheckCircle size={72} color="var(--success)" />
          <h1 className="mt-5 text-[24px] font-bold text-foreground">{translate("orderForm.success.title")}</h1>
          <p className="mt-2 text-[15px] leading-6 text-muted-foreground">{translate("orderForm.success.waiting")}</p>
          <p className="mt-1 text-[14px] leading-6 text-muted-foreground">{translate("orderForm.success.notify")}</p>
          {listingWarnings.length > 0 && (
            <div className="mt-5 w-full rounded-[14px] bg-warning/14 px-4 py-3 text-left">
              <p className="text-[13px] font-semibold text-warning">{translate("orderForm.success.contactsHidden")}</p>
              <p className="mt-1 text-[12px] leading-5 text-warning">{listingWarnings.join(", ")}</p>
            </div>
          )}
          <div className="mt-8 w-full">
            <PrimaryButton onClick={() => go("client-orders")}>{translate("orderForm.success.toOrders")}</PrimaryButton>
          </div>
        </main>
      );
    }

    if (screen === "client-orders") {
      return (
        <main className="flex flex-1 flex-col bg-background">
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="flex items-center gap-3">
              <SidebarButton className="shadow-none ring-1 ring-border" onClick={() => setSidebarOpen(true)} />
              <h1 className="text-[24px] font-bold text-foreground">{translate("orders.title")}</h1>
            </div>
            {clientBookings.map((raw) => {
              const booking = raw as BookingClientDTO;
              return (
                <button
                  key={booking.id}
                  onClick={() => void run(() => openClientBooking(booking.id))}
                  className="el-press w-full rounded-[16px] border border-border bg-card p-4 text-left"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                      <MapPin size={14} color="var(--primary)" />
                      {endLabel(booking.pickup.stop, booking.pickup.point)} {"->"}{" "}
                  {endLabel(booking.dropoff.stop, booking.dropoff.point)}
                    </span>
                    <StatusBadge status={booking.service_status} />
                  </div>
                  <div className="flex items-center justify-between text-[13px] text-muted-foreground">
                    <span>{shortDate(booking.pickup.window_start ?? undefined)}</span>
                    <span className="font-semibold text-foreground">{formatUzs(booking.total_minor / 100)}</span>
                  </div>
                </button>
              );
            })}
            {myListings.map((listing) => (
              <ListingCard key={listing.id} listing={listing} onClick={() => void run(() => openListing(listing.id))} />
            ))}
            {!myListings.length && !clientBookings.length && !orders.length && <EmptyState icon={Package} title={translate("orders.empty")} />}
            {orders.length > 0 && (
              <>
                <p className="pt-2 text-[13px] font-semibold text-muted-foreground">{translate("orders.legacy")}</p>
                {orders.map((order) => (
                  <OrderCard key={order.id} order={order} onClick={() => void run(() => openClientOrder(order.id))} />
                ))}
              </>
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-order-detail" && orderDetail) {
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("orders.detailTitle")} back={() => go("client-orders")} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <OrderCard order={orderDetail} />
            {[
              [translate("routeSummary.pickup"), orderDetail.pickup_address],
              [translate("routeSummary.dropoff"), orderDetail.dropoff_address],
              [translate("orderForm.review.sender"), orderDetail.sender_phone],
              [translate("orderForm.review.receiver"), orderDetail.receiver_phone],
              [translate("listingOwner.commentLabel"), orderDetail.comment || "-"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{label}</p>
                <p className="mt-1 text-[14px] font-medium text-foreground">{value}</p>
              </div>
            ))}
            {orderDetail.assigned_driver && (
              <div className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{translate("dispute.side.driver")}</p>
                <p className="mt-1 text-[15px] font-semibold text-foreground">{orderDetail.assigned_driver.full_name ?? translate("dispute.side.driver")}</p>
                <p className="text-[13px] text-muted-foreground">{orderDetail.assigned_driver.car_model} / {orderDetail.assigned_driver.plate_number}</p>
              </div>
            )}
            {(hasLocation(orderDetail.pickup_lat, orderDetail.pickup_lng) || hasLocation(orderDetail.dropoff_lat, orderDetail.dropoff_lng)) && (
              <div className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{translate("orders.mapPoints")}</p>
                <p className="mt-1 text-[14px] font-medium text-foreground">
                  {hasLocation(orderDetail.pickup_lat, orderDetail.pickup_lng) ? translate("orders.pickupMarked") : translate("orders.pickupNotMarked")}
                </p>
                <p className="mt-1 text-[14px] font-medium text-foreground">
                  {hasLocation(orderDetail.dropoff_lat, orderDetail.dropoff_lng) ? translate("orders.dropoffMarked") : translate("orders.dropoffNotMarked")}
                </p>
                <button
                  type="button"
                  onClick={() => setReadOnlyMap({
                    pickupLat: orderDetail.pickup_lat,
                    pickupLng: orderDetail.pickup_lng,
                    dropoffLat: orderDetail.dropoff_lat,
                    dropoffLng: orderDetail.dropoff_lng,
                    destinationLat: orderDetail.dropoff_lat,
                    destinationLng: orderDetail.dropoff_lng,
                  })}
                  className="el-press mt-3 h-10 w-full rounded-[10px] bg-accent text-[14px] font-semibold text-primary"
                >
                  {translate("orders.viewOnMap")}
                </button>
              </div>
            )}
            <StatusTimeline status={orderDetail.status} />
            {["published", "bidding"].includes(orderDetail.status) && (orderDetail.bids_count ?? 0) === 0 && (
              <EmptyState icon={Package} title={translate("orders.noBids")} subtitle={translate("orders.noBidsHint")} />
            )}
            {orderDetail.status === "delivered" && <PrimaryButton onClick={() => setConfirmAction({ type: "confirm-delivery" })}>{translate("orders.confirmDelivered")}</PrimaryButton>}
            {["published", "bidding"].includes(orderDetail.status) && <PrimaryButton onClick={() => void run(() => openClientOrder(orderDetail.id, "client-bids"))}>{translate("orders.viewBids")}</PrimaryButton>}
            {["draft", "published", "bidding", "accepted"].includes(orderDetail.status) && (
              <SecondaryButton danger onClick={() => setConfirmAction({ type: "cancel-order" })}>
                {translate("orders.cancel")}
              </SecondaryButton>
            )}
            {["picked_up", "in_transit", "delivered", "disputed"].includes(orderDetail.status) && (
              <SecondaryButton onClick={() => go("client-dispute")}>{translate("orders.reportProblem")}</SecondaryButton>
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-booking-detail" && clientBooking) {
      const booking = clientBooking;
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("orders.detailTitle")} back={() => go("client-orders")} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <div className="rounded-[16px] border border-border bg-card p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                  <MapPin size={14} color="var(--primary)" />
                  {endLabel(booking.pickup.stop, booking.pickup.point)} {"->"}{" "}
                  {endLabel(booking.dropoff.stop, booking.dropoff.point)}
                </span>
                <StatusBadge status={booking.service_status} />
              </div>
              <div className="flex items-center justify-between text-[13px] text-muted-foreground">
                <span>{shortDate(booking.pickup.window_start ?? undefined)}</span>
                <span className="font-semibold text-foreground">{formatUzs(booking.total_minor / 100)}</span>
              </div>
            </div>
            <PromoMoneyCard promo={booking.promo} />
            <div className="rounded-[14px] border border-border bg-card p-4">
              <p className="text-[12px] text-muted-foreground">{translate("bookingDetail.fare")}</p>
              <p className="mt-1 text-[14px] font-medium text-foreground">
                {translate("bookingDetail.fareCash", { amount: formatUzs(cashDueMinor(booking) / 100) })}
              </p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {translate("bookingDetail.fareNote")}
              </p>
            </div>
            {booking.service_type === "parcel" && (
              <ParcelPhoto
                photo={booking.parcel_photo}
                label={translate("orderForm.photoTitle")}
                onRefresh={() => void run(() => openClientBooking(booking.id))}
              />
            )}
            {(bookingCodes?.codes ?? []).map((code) => (
              <div key={code.kind} className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{proofCodeLabel(code.kind)}</p>
                <p className="mt-1 text-[22px] font-bold tracking-[0.2em] text-foreground">{code.code}</p>
                <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                  {proofCodeHint(code.kind)}
                </p>
                {canReissueCode("client", code.kind, booking.service_status) && (
                  <>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => reissueCode(booking.id, code.kind)}
                      className="el-press mt-3 h-10 w-full rounded-[10px] bg-accent text-[14px] font-semibold text-primary disabled:opacity-60"
                    >
                      {translate("reissue.button")}
                    </button>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{translate("reissue.hint")}</p>
                  </>
                )}
                {reissueNotice?.kind === code.kind && (
                  <p className={cls("mt-2 text-[12px] leading-5", reissueNotice.ok ? "text-success" : "text-warning")}>
                    {reissueNotice.text}
                  </p>
                )}
              </div>
            ))}
            {(CASH_RECORDABLE[booking.service_type] ?? []).includes(booking.service_status) && (
              <CashAcknowledgement
                booking={booking}
                side="client"
                busy={busy}
                amount={cashAmount}
                onAmountChange={setCashAmount}
                onReport={() => void run(() => reportCash(booking.id, "client", booking.version), translate("bookingDetail.cashRecorded"))}
                onDecide={(decision) =>
                  booking.cash_receipt && void run(() => decideCash(booking.id, "client", booking.cash_receipt!, decision), translate("bookingDetail.answerSaved"))
                }
              />
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void run(() => openChat(booking.id, "client"))}
                className="el-press h-11 flex-1 rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
              >
                {translate("bookingDetail.messages")}
              </button>
              <button
                type="button"
                onClick={() => void run(() => openTracking(booking.id, "client"))}
                className="el-press h-11 flex-1 rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
              >
                {translate("bookingDetail.tracking")}
              </button>
            </div>
            {/* K5: a live-tracking link for family, the booking owner's only (the server re-checks both). */}
            {canShareTracking(booking.service_status) && (
              <div className="space-y-2">
                <p className="px-1 text-[13px] font-semibold text-muted-foreground">{translate("tracking.shareTitle")}</p>
                <TrackingGrantPanel bookingId={booking.id} />
              </div>
            )}
            {AMENDABLE_STATUSES.includes(booking.service_status) && (
              <SecondaryButton onClick={() => void run(() => openAmendments(booking.id, "client"))}>
                {translate("bookingDetail.changeTerms")}
              </SecondaryButton>
            )}
            {canRate(booking.service_status) && (
              <PrimaryButton disabled={busy} onClick={() => openRating(booking.id, "client")}>
                {translate("rating.rateDriver")}
              </PrimaryButton>
            )}
            {canOpenDispute(booking.service_status) && (
              <SecondaryButton onClick={() => openDisputeForm(booking.id, "client")}>
                {translate("orders.reportProblem")}
              </SecondaryButton>
            )}
            {renderBookingDisputes(booking.id)}
            {renderCancelControls(booking, "client")}
            {booking.service_status === "cancelled" && (() => {
              // ADR-0025: the booking came from a saved request; searching again is an explicit act, and the
              // old offers stay closed. `can_reopen` is the server's answer, re-read when this screen opened.
              const intent = intentOfBooking(myIntents, booking.id);
              return (
                <div className="space-y-2 rounded-[14px] border border-border bg-card p-4">
                  {renderCancelledNote(booking)}
                  {intent?.can_reopen && (
                    <>
                      <p className="text-[12px] leading-5 text-muted-foreground">{translate("bookingCancel.searchAgainHint")}</p>
                      <PrimaryButton disabled={busy} onClick={() => searchAgainFor(intent)}>
                        {translate("bookingCancel.searchAgain")}
                      </PrimaryButton>
                    </>
                  )}
                </div>
              );
            })()}
            {booking.service_status === "delivered" && (
              <PrimaryButton
                disabled={busy}
                onClick={() => void run(async () => {
                  await bookingAction(booking.id, "complete", { expected_version: booking.version });
                  await openClientBooking(booking.id);
                  await loadMyListings();
                }, translate("bookingDetail.completed"))}
              >
                {translate("orders.confirmDelivered")}
              </PrimaryButton>
            )}
            {renderBookingSafety(booking, "client")}
          </section>
        </main>
      );
    }

    if (screen === "driver-proposals" || screen === "client-proposals") {
      // Q92: one negotiation, two authors. Who opened the thread does not decide what this screen shows - what
      // decides it is who spoke last, because AC05 forbids accepting your own version. So the same list serves
      // a driver answering a client's request and a client answering a driver's trip offer.
      const mySide: ActorSide = screen === "client-proposals" ? "client" : "driver";
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("proposals.title")} back={() => go(mySide === "client" ? "client-profile" : "driver-profile")} />
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            {busy && !myProposals.length ? <ListSkeleton /> : myProposals.length ? myProposals.map((thread) => {
              const version = thread.current_version;
              // AC05 and the rest of the auction rules live in `./auction`, so this screen, the listing's bid
              // screen and any future one answer the same way - and the rule is testable without a browser.
              const actions = negotiationActions(thread, mySide);
              const { open, theirTurn } = actions;
              return (
                <div key={thread.id} className="rounded-[16px] border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[15px] font-semibold text-foreground">
                        {version ? `${endLabel(version.pickup_stop, version.pickup_point)} -> ${endLabel(version.dropoff_stop, version.dropoff_point)}` : "-"}
                      </p>
                      <p className="mt-1 text-[13px] text-muted-foreground">
                        {version ? `${shortDate(version.pickup_window_start)} - ${shortDate(version.pickup_window_end)}` : "-"}
                      </p>
                      <p className="mt-1 text-[12px] text-muted-foreground">
                        {turnLabel(actions, mySide)}
                      </p>
                    </div>
                    <p className="shrink-0 text-[17px] font-bold text-primary">
                      {version ? formatUzs(version.total_minor / 100) : "-"}
                    </p>
                  </div>

                  {!open && version && (
                    <p className="mt-3 text-[12px] leading-5 text-muted-foreground">
                      {translate("proposals.closed", { status: proposalStatusLabel(version.status) })}
                    </p>
                  )}

                  {open && version && (
                    <div className="mt-3 empty:hidden">
                      <StaleConfirmation threadId={thread.id} side={mySide} version={version} onDone={() => void loadMyProposals()} />
                    </div>
                  )}

                  {open && version && counterFor === thread.id && (
                    <div className="mt-3 space-y-3">
                      <Field
                        label={translate("proposals.newPrice")}
                        type="number"
                        value={counterPrice}
                        placeholder={String(Math.round(version.total_minor / 100))}
                        onChange={setCounterPrice}
                      />
                      {mySide === "client" && (
                        <BonusConsentPanel
                          listingId={thread.listing_id}
                          unitPriceMinor={soumToMinor(counterPrice)}
                          quantity={version.quantity}
                          choice={counterConsent}
                          onChoice={setCounterConsent}
                          refreshToken={consentRefresh}
                        />
                      )}
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={counterPending || busy || soumToMinor(counterPrice) <= 0}
                          onClick={() => void run(() => sendCounter(thread.id, version.revision, loadMyProposals, mySide === "client"), translate("proposals.counterSent"))}
                          className="h-11 flex-1 rounded-[12px] bg-primary text-[14px] font-semibold text-primary-foreground disabled:bg-slate-400"
                        >
                          {counterPending ? translate("common.sending") : translate("common.send")}
                        </button>
                        <button
                          type="button"
                          onClick={() => { setCounterFor(null); setCounterPrice(""); }}
                          className="el-press h-11 flex-1 rounded-[12px] bg-muted text-[14px] font-semibold text-muted-foreground"
                        >
                          {translate("common.cancel")}
                        </button>
                      </div>
                    </div>
                  )}

                  {open && version && counterFor !== thread.id && (
                    <div className="mt-3 space-y-2">
                      {actions.canAccept && version.promo_quote?.view === "driver" && (
                        // the driver reads the cash to collect, the credit used and the commission before agreeing
                        <PromoMoneyCard promo={version.promo_quote} title={translate("proposals.ifYouAccept")} agreed={false} />
                      )}
                      {actions.canAccept && mySide === "client" && (
                        <AcceptConsentPanel
                          quote={version.promo_quote?.view === "client" ? version.promo_quote : null}
                          choice={acceptConsent[thread.id] ?? NO_CONSENT}
                          onChoice={(choice) => setAcceptConsent((all) => ({ ...all, [thread.id]: choice }))}
                        />
                      )}
                      {actions.canAccept && !version.promo_quote && <NoDiscountNote reason={version.promo_unavailable_reason} />}
                      {actions.canAccept && (
                        <PrimaryButton
                          disabled={busy}
                          onClick={() => void run(async () => {
                            const listing = await getListing(thread.listing_id);
                            const promo = mySide === "client" ? consentBody(acceptConsent[thread.id] ?? NO_CONSENT) : undefined;
                            const shown = mySide === "driver" && version.promo_quote?.view === "driver" ? version.promo_quote : null;
                            const body = acceptBody(version.id, listing.terms_version, promo, shown
                              ? { cash_to_collect_minor: shown.cash_to_collect_minor, commission_charged_minor: shown.commission_charged_minor }
                              : undefined);
                            const booking = await oncePerAction(`accept:${thread.id}:${version.id}`,
                              (key) => acceptProposal(thread.id, body, key)).catch(async (cause) => {
                                // the server's numbers changed: show the new card before anyone confirms again
                                if (needsRequote(cause as { code?: string })) await loadMyProposals().catch(() => undefined);
                                return requoteAndThrow(cause);
                              });
                            await loadMyProposals();
                            if (mySide === "client") await loadMyListings();
                            else await loadDriverBookings();
                            // The price is settled, so the conversation opens here and not before: from this
                            // point the two of them have a booking to arrange, not a number to argue about.
                            // The booking is loaded first so the chat's back button has a screen to return to.
                            if (mySide === "client") await openClientBooking(booking.data.id);
                            else await openDriverBooking(booking.data.id);
                            await openChat(booking.data.id, mySide);
                          }, translate("notification.booking.accepted.title"))}
                        >
                          {mySide === "client" ? translate("proposals.acceptDriverPrice") : translate("proposals.acceptClientPrice")}
                        </PrimaryButton>
                      )}
                      {actions.canCounter ? (
                        <button
                          type="button"
                          onClick={() => { setCounterFor(thread.id); setCounterPrice(String(Math.round(version.total_minor / 100))); }}
                          className="el-press h-11 w-full rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
                        >
                          {translate("proposals.counterAnother", { count: actions.revisionsLeft })}
                        </button>
                      ) : (
                        <p className="text-[12px] leading-5 text-muted-foreground">{translate("proposals.noRevisionsLeft")}</p>
                      )}
                      {actions.canWithdraw && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void run(async () => {
                            await withdrawProposal(thread.id, version.revision);
                            await loadMyProposals();
                          }, translate("notification.proposal.withdrawn.title"))}
                          className="el-press h-11 w-full rounded-[12px] bg-muted text-[14px] font-semibold text-muted-foreground"
                        >
                          {translate("proposals.withdraw")}
                        </button>
                      )}
                      {actions.canReject && (
                        // P7: refuse what the other side wrote; a stale revision is refused by the server and the
                        // list is re-read, so the person always answers the version they can see.
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void run(async () => {
                            try {
                              await rejectProposal(thread.id, version.revision);
                            } finally {
                              await loadMyProposals().catch(() => undefined);
                            }
                          }, translate("proposal.rejected"))}
                          className="el-press h-11 w-full rounded-[12px] bg-destructive/10 text-[14px] font-semibold text-destructive"
                        >
                          {translate("proposal.reject")}
                        </button>
                      )}
                    </div>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(async () => {
                      // P5: this one thread as the server has it now - the other side may have moved.
                      const fresh = await getProposal(thread.id);
                      setMyProposals((list) => list.map((item) => (item.id === fresh.id ? fresh : item)));
                    })}
                    className="el-press mt-2 h-9 w-full rounded-[10px] text-[13px] font-semibold text-muted-foreground"
                  >
                    {translate("proposal.refresh")}
                  </button>
                </div>
              );
            }) : (
              <EmptyState
                icon={Package}
                title={translate("proposals.empty")}
                subtitle={mySide === "client"
                  ? translate("proposals.emptyClient")
                  : translate("proposals.emptyDriver")}
              />
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-bonus") {
      return <BonusScreen role="client" back={() => go("client-profile")} />;
    }

    if (screen === "driver-bonus") {
      return <BonusScreen role="driver" back={() => go("driver-profile")} />;
    }

    if (screen === "booking-rating" && openBooking) {
      // S1 from either side: a client rates the driver, a driver rates the client - never themselves.
      const side = openBooking.side;
      const booking = side === "driver" ? driverBooking : clientBooking;
      if (!booking) return <EmptyState icon={Package} title={translate("bookingRating.bookingNotFound")} />;
      const back = () => go(side === "driver" ? "driver-order-detail" : "client-booking-detail");
      const subject = counterpartSide(side);
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate(subject === "driver" ? "rating.titleDriver" : "rating.titleClient")} back={back} />
          <section className="flex flex-1 flex-col gap-5 px-5 py-6">
            <p className="text-center text-[14px] text-muted-foreground">{translate("bookingRating.prompt")}</p>
            <div className="flex justify-center gap-2">
              {[1, 2, 3, 4, 5].map((value) => (
                <button type="button" className="el-press" key={value} onClick={() => setRating(value)} aria-label={translate("bookingRating.starsAria", { value })}>
                  <Star fill={value <= rating ? "var(--warning)" : "none"} color="var(--warning)" size={34} />
                </button>
              ))}
            </div>
            <Field label={translate("bookingRating.commentLabel")} value={ratingComment} multiline onChange={setRatingComment} />
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("bookingRating.moderationNote")}
            </p>
            <div className="mt-auto">
              <PrimaryButton
                disabled={busy}
                onClick={() => void run(async () => {
                  const result = await rateBooking(
                    booking.id,
                    { subject_side: subject, stars: rating, comment: ratingComment.trim() || null },
                    newIdempotencyKey(),
                  );
                  setListingWarnings(result.warnings.map((warning) => warning.code));
                  await (side === "driver" ? openDriverBooking(booking.id) : openClientBooking(booking.id));
                }, translate("bookingRating.sent"))}
              >
                {translate("bookingRating.submit")}
              </PrimaryButton>
              <button type="button" onClick={back} className="el-press mt-3 h-10 w-full text-[14px] font-semibold text-muted-foreground">
                {translate("bookingRating.later")}
              </button>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "booking-dispute" && openBooking) {
      // S3 from either side. The commission type is the driver's alone (Q16), so the picker depends on the side.
      const side = openBooking.side;
      const booking = side === "driver" ? driverBooking : clientBooking;
      if (!booking) return <EmptyState icon={Package} title={translate("bookingRating.bookingNotFound")} />;
      const back = () => go(side === "driver" ? "driver-order-detail" : "client-booking-detail");
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("bookingDispute.title")} back={back} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <PickSelect
              label={translate("bookingDispute.typeLabel")}
              placeholder={translate("bookingDispute.typePlaceholder")}
              value={disputeType}
              options={disputeTypeOptions(side)}
              onChange={setDisputeType}
            />
            <Field label={translate("listingOwner.commentLabel")} value={disputeComment} multiline onChange={setDisputeComment} />
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("bookingDispute.gpsEvidenceNote")}
            </p>
            <div className="mt-auto">
              <PrimaryButton
                disabled={busy || disputeComment.trim().length < 5}
                onClick={() => void run(async () => {
                  await openDispute(
                    booking.id,
                    { type: disputeType as DisputeDTO["type"], description: disputeComment.trim() },
                    newIdempotencyKey(),
                  );
                  setDisputeComment("");
                  await (side === "driver" ? openDriverBooking(booking.id) : openClientBooking(booking.id));
                }, translate("bookingDispute.opened"))}
              >
                {translate("common.send")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "booking-amendment" && openBooking) {
      // B9 / Q60: after a booking exists, only the quantity and the unit price may still move, and only by
      // agreement. Everything else in the snapshot is frozen in the database - so this screen offers exactly
      // the two fields that can legally change, and nothing that would quietly rewrite what was agreed.
      const side = openBooking.side;
      const booking = side === "driver" ? driverBooking : clientBooking;
      if (!booking) return <EmptyState icon={Package} title={translate("bookingRating.bookingNotFound")} />;
      const back = () => go(side === "driver" ? "driver-order-detail" : "client-booking-detail");
      const quantity = Number(amendmentForm.quantity);
      const unitMinor = soumToMinor(amendmentForm.unitPrice);
      const changed =
        (Number.isFinite(quantity) && quantity >= 1 && quantity !== booking.quantity) ||
        (unitMinor > 0 && unitMinor !== booking.unit_price_minor);
      const newTotal = booking.price_basis === "per_seat" ? unitMinor * Math.max(quantity, 1) : unitMinor;
      const open = amendments.filter((item) => item.status === "proposed");

      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("amendment.title")} back={back} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[12px] text-muted-foreground">{translate("amendment.currentTerms")}</p>
              <p className="mt-1 text-[15px] font-semibold text-foreground">
                {booking.quantity} × {formatUzs(booking.unit_price_minor / 100)} = {formatUzs(booking.total_minor / 100)}
              </p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {translate("amendment.takesEffectNote")}
              </p>
            </div>

            {open.length === 0 && (
              <div className="space-y-3 rounded-[16px] border border-border bg-card p-4">
                <p className="text-[13px] font-semibold text-foreground">{translate("amendment.proposeTitle")}</p>
                <Field
                  label={booking.service_type === "passenger" ? translate("amendment.seatsLabel") : translate("amendment.quantityLabel")}
                  type="number"
                  value={amendmentForm.quantity}
                  onChange={(value) => setAmendmentForm({ ...amendmentForm, quantity: value })}
                />
                <Field
                  label={booking.price_basis === "per_seat" ? translate("amendment.seatPriceLabel") : translate("amendment.priceLabel")}
                  type="number"
                  value={amendmentForm.unitPrice}
                  onChange={(value) => setAmendmentForm({ ...amendmentForm, unitPrice: value })}
                />
                <Field
                  label={translate("common.reason")}
                  value={amendmentForm.reason}
                  onChange={(value) => setAmendmentForm({ ...amendmentForm, reason: value })}
                  placeholder={translate("amendment.reasonPlaceholder")}
                  hint={translate("amendment.reasonHint")}
                />
                {changed && unitMinor > 0 && (
                  <p className="rounded-[12px] bg-accent px-3 py-2.5 text-[13px] font-semibold text-primary">
                    {translate("amendment.newTotal", { total: formatUzs(newTotal / 100) })}
                  </p>
                )}
                {amendConsentAsk && (
                  // Q116/Q125: on a discounted booking the client confirms the new cash amount the server computed
                  <div className="rounded-[12px] border border-warning/30 bg-warning/8 p-3 text-[13px] leading-5 text-foreground">
                    {translate("amendment.consentAsk", {
                      discount: nbsp(formatUzs(amendConsentAsk.passenger_discount_minor / 100)),
                      cash: nbsp(formatUzs(amendConsentAsk.cash_due_minor / 100)),
                    })}
                    {booking.promo?.view === "client" && amendConsentAsk.fare_minor !== undefined && (() => {
                      const note = amendmentCashNote(booking.promo, {
                        fare_minor: amendConsentAsk.fare_minor,
                        passenger_discount_minor: amendConsentAsk.passenger_discount_minor,
                        cash_due_minor: amendConsentAsk.cash_due_minor,
                      });
                      return note ? <span className="mt-1.5 block font-semibold">{note}</span> : null;
                    })()}
                  </div>
                )}
                {amendAckAsk && side === "driver" && (
                  <p className="rounded-[12px] border border-warning/30 bg-warning/8 p-3 text-[13px] leading-5 text-foreground">
                    {translate("amendment.driverAckAsk", {
                      cash: nbsp(formatUzs(amendAckAsk.cash_to_collect_minor / 100)),
                      commission: nbsp(formatUzs(amendAckAsk.commission_charged_minor / 100)),
                    })}
                  </p>
                )}
                <PrimaryButton
                  disabled={busy || !changed || unitMinor <= 0 || amendmentForm.reason.trim().length < 3}
                  onClick={() => void run(async () => {
                    try {
                      await proposeAmendment(
                        booking.id,
                        {
                          expected_version: booking.version,
                          changes: { quantity, unit_price_minor: unitMinor },
                          reason: amendmentForm.reason.trim(),
                          ...(amendConsentAsk && side === "client"
                            ? { promo_consent: { passenger_bonus_minor: amendConsentAsk.passenger_discount_minor, cash_due_minor: amendConsentAsk.cash_due_minor } }
                            : {}),
                          ...(amendAckAsk && side === "driver" ? { promo_driver_ack: amendAckAsk } : {}),
                        },
                        newIdempotencyKey(),
                      );
                      setAmendConsentAsk(null);
                      setAmendAckAsk(null);
                    } catch (cause) {
                      const details = (cause as { code?: string; details?: { passenger_discount_minor?: number; cash_due_minor?: number; fare_minor?: number; party?: string } });
                      const ack = driverAckRequested(cause as { code?: string; details?: Record<string, unknown> });
                      if (ack) {
                        setAmendAckAsk(ack);
                      } else if (needsRequote(details) && typeof details.details?.cash_due_minor === "number") {
                        setAmendConsentAsk({
                          passenger_discount_minor: details.details.passenger_discount_minor ?? 0,
                          cash_due_minor: details.details.cash_due_minor,
                          fare_minor: details.details.fare_minor,
                        });
                      }
                      throw cause;
                    }
                    await loadAmendments(booking.id);
                  }, translate("amendment.sent"))}
                >
                  {amendConsentAsk ? translate("amendment.submitConsent") : amendAckAsk && side === "driver" ? translate("amendment.submitDriverAck") : translate("amendment.submit")}
                </PrimaryButton>
              </div>
            )}

            {amendments.length === 0 ? (
              <p className="text-[13px] leading-5 text-muted-foreground">{translate("amendment.empty")}</p>
            ) : (
              amendments.map((item) => {
                const mine = item.author_side === side;
                const pending = item.status === "proposed";
                return (
                  <div key={item.id} className="rounded-[16px] border border-border bg-card p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[15px] font-semibold text-foreground">
                          {item.new_quantity} × {formatUzs(item.new_unit_price_minor / 100)}
                        </p>
                        <p className="mt-1 text-[12px] text-muted-foreground">
                          {mine ? translate("amendment.mine") : translate("amendment.theirs")}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[17px] font-bold text-primary">{formatUzs(item.new_total_minor / 100)}</p>
                        <StatusBadge status={item.status} />
                      </div>
                    </div>
                    <PromoMoneyCard promo={item.promo} title={translate("amendment.afterChangeTitle")} agreed={item.status === "accepted"} />
                    {pending && side === "client" && item.promo?.view === "client" && booking.promo?.view === "client" && (() => {
                      // Q125: a lower fare that still raises the cash is said out loud, not left to be noticed
                      const note = amendmentCashNote(booking.promo, item.promo);
                      return note ? <p className="mt-2 text-[12px] font-semibold leading-5 text-warning">{note}</p> : null;
                    })()}
                    {pending && !mine && (
                      <div className="mt-3 space-y-2">
                        {side === "client" && item.promo?.view === "client" && (
                          <AcceptConsentPanel
                            quote={item.promo}
                            choice={acceptConsent[item.id] ?? NO_CONSENT}
                            onChoice={(choice) => setAcceptConsent((all) => ({ ...all, [item.id]: choice }))}
                          />
                        )}
                        <PrimaryButton
                          disabled={busy || (side === "client" && item.promo?.view === "client" && !(acceptConsent[item.id]?.useBonus))}
                          onClick={() => void run(async () => {
                            const promo = side === "client" && item.promo?.view === "client"
                              ? { passenger_bonus_minor: item.promo.passenger_discount_minor, cash_due_minor: item.promo.cash_due_minor }
                              : undefined;
                            // Q125: the driver accepts exactly the cash and commission shown on this card
                            const ack = side === "driver" && item.promo?.view === "driver"
                              ? { cash_to_collect_minor: item.promo.cash_to_collect_minor, commission_charged_minor: item.promo.commission_charged_minor }
                              : undefined;
                            await acceptAmendment(item.id, item.version, promo, ack);
                            // Re-open rather than only reloading the list: accepting changes the booking's
                            // terms *and* its version, and the next amendment is proposed against that version.
                            await openAmendments(booking.id, side);
                          }, translate("amendment.accepted"))}
                        >
                          {translate("amendment.accept")}
                        </PrimaryButton>
                        <SecondaryButton
                          danger
                          onClick={() => void run(async () => {
                            await decideAmendment(item.id, "reject", item.version);
                            await loadAmendments(booking.id);
                          }, translate("amendment.rejected"))}
                        >
                          {translate("proposal.reject")}
                        </SecondaryButton>
                      </div>
                    )}
                    {pending && mine && (
                      <div className="mt-3 space-y-2">
                        {item.promo && (
                          // Q126: if the other side is told my confirmation went stale, I renew it from this session
                          <SecondaryButton
                            onClick={() => void run(async () => {
                              const promo = item.promo;
                              await confirmAmendmentPromo(item.id, promo?.view === "client"
                                ? { promo_consent: { passenger_bonus_minor: promo.passenger_discount_minor, cash_due_minor: promo.cash_due_minor } }
                                : promo?.view === "driver"
                                  ? { promo_driver_ack: { cash_to_collect_minor: promo.cash_to_collect_minor, commission_charged_minor: promo.commission_charged_minor } }
                                  : {});
                              await loadAmendments(booking.id);
                            }, translate("amendment.promoReconfirmed"))}
                          >
                            {translate("amendment.promoReconfirm")}
                          </SecondaryButton>
                        )}
                        <SecondaryButton
                          onClick={() => void run(async () => {
                            await decideAmendment(item.id, "withdraw", item.version);
                            await loadAmendments(booking.id);
                          }, translate("amendment.withdrawn"))}
                        >
                          {translate("amendment.withdraw")}
                        </SecondaryButton>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </section>
        </main>
      );
    }

    if (screen === "driver-saved-searches") {
      // The direction currently on the feed is what gets saved - the driver has already chosen it there, and
      // asking for it a second time in a second form is how a screen like this stops being used.
      const canSave = Boolean((pickupEnd.district || pickupEnd.stop) && (dropoffEnd.district || dropoffEnd.stop));
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("savedSearches.title")} back={() => go("driver-feed")} />
          <section className="el-enter el-stagger min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <p className="text-[13px] leading-5 text-muted-foreground">
              {translate("savedSearches.intro")}
            </p>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[13px] font-semibold text-foreground">{translate("savedSearches.currentDirection")}</p>
              <p className="mt-1 text-[14px] text-foreground">
                {directionEndLabel(pickupEnd)} {"->"} {directionEndLabel(dropoffEnd)}
              </p>
              <div className="mt-3">
                <PrimaryButton
                  disabled={busy || !canSave}
                  onClick={() => void run(async () => {
                    const from = new Date();
                    const to = new Date(Date.now() + 14 * 24 * 3600 * 1000);
                    await createSavedSearch(
                      {
                        service_type: driverServiceMode,
                        side: "requests",
                        origin_district_id: pickupEnd.district?.id,
                        origin_stop_id: pickupEnd.district ? undefined : pickupEnd.stop?.id,
                        destination_district_id: dropoffEnd.district?.id,
                        destination_stop_id: dropoffEnd.district ? undefined : dropoffEnd.stop?.id,
                        time_window_start: from.toISOString(),
                        time_window_end: to.toISOString(),
                        quantity: 1,
                        notify: true,
                      } as Parameters<typeof createSavedSearch>[0],
                      newIdempotencyKey(),
                    );
                    await loadSavedSearches();
                  }, translate("savedSearches.saved"))}
                >
                  {translate("savedSearches.save")}
                </PrimaryButton>
                {!canSave && (
                  <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
                    {translate("savedSearches.pickEndsFirst")}
                  </p>
                )}
              </div>
            </div>

            {busy && !saved.length ? <ListSkeleton rows={2} /> : saved.length ? saved.map((item) => (
              <div key={item.id} className="rounded-[16px] border border-border bg-card p-4">
                <p className="text-[14px] font-semibold text-foreground">
                  {savedEndLabel(item.origin_district_id, item.origin_stop_id, districtNames)} {"->"}{" "}
                  {savedEndLabel(item.destination_district_id, item.destination_stop_id, districtNames)}
                </p>
                <p className="mt-1 text-[12px] text-muted-foreground">
                  {shortDate(item.time_window_start)} - {shortDate(item.time_window_end)}
                  {item.notify ? ` · ${translate("savedSearches.notifyOn")}` : ` · ${translate("savedSearches.notifyOff")}`}
                </p>
                <div className="mt-3">
                  <SecondaryButton
                    danger
                    onClick={() => void run(async () => {
                      await deleteSavedSearch(item.id);
                      await loadSavedSearches();
                    }, translate("savedSearches.deleted"))}
                  >
                    {translate("common.delete")}
                  </SecondaryButton>
                </div>
              </div>
            )) : (
              <EmptyState
                icon={Navigation}
                title={translate("savedSearches.emptyTitle")}
                subtitle={translate("savedSearches.emptySubtitle")}
              />
            )}
          </section>
          <div className="absolute inset-x-0 bottom-0 z-20">
            <BottomNav role="driver" active={screen} go={go} />
          </div>
        </main>
      );
    }

    if (screen === "my-disputes") {
      // S6: a dispute is the one place where what the two people say is weighed by a third. Evidence is the
      // part that decides it, so it has to be addable after the first report - people remember the photo late.
      const side = auth.user?.role === "driver" ? "driver" : "client";
      const back = () => go(side === "driver" ? "driver-profile" : "client-profile");
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("disputes.title")} back={back} />
          <section className="el-enter el-stagger min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
            {busy && !bookingDisputes.length ? <ListSkeleton rows={2} /> : bookingDisputes.length ? bookingDisputes.map((item) => {
              const open = !["resolved", "rejected", "withdrawn", "closed"].includes(item.status);
              const editing = evidenceNote?.id === item.id;
              return (
                <div key={item.id} className="rounded-[16px] border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[15px] font-semibold text-foreground">
                        {disputeTypeLabel(item.type)}
                      </p>
                      <p className="mt-1 text-[12px] text-muted-foreground">{shortDate(item.created_at)}</p>
                    </div>
                    <StatusBadge status={item.status} />
                  </div>
                  <p className="mt-2 text-[13px] leading-5 text-secondary-foreground">{item.description}</p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(() => openDisputeDetail(item.id))}
                    className="el-press mt-2 text-[13px] font-semibold text-primary"
                  >
                    {translate("dispute.details")}
                  </button>

                  {item.evidence.length > 0 && (
                    <div className="mt-3 space-y-1.5 rounded-[12px] bg-slate-50 p-3">
                      <p className="text-[12px] font-semibold text-muted-foreground">{translate("disputes.evidence")}</p>
                      {item.evidence.map((entry, index) => (
                        <p key={index} className="text-[12px] leading-5 text-secondary-foreground">
                          {entry.note || translate("disputes.fileAttached")}
                        </p>
                      ))}
                    </div>
                  )}

                  {item.resolution && (
                    <p className="mt-3 rounded-[12px] bg-accent px-3 py-2.5 text-[13px] leading-5 text-primary">
                      {translate("disputes.decisionPrefix")} {item.resolution.text || disputeResolutionLabel(item.resolution.code ?? "") || item.resolution.code}
                    </p>
                  )}

                  {open && !editing && (
                    <div className="mt-3">
                      <SecondaryButton onClick={() => setEvidenceNote({ id: item.id, note: "" })}>
                        {translate("disputes.addEvidence")}
                      </SecondaryButton>
                    </div>
                  )}
                  {open && editing && (
                    <div className="mt-3 space-y-2">
                      <Field
                        label={translate("disputes.extraNoteLabel")}
                        multiline
                        value={evidenceNote.note}
                        onChange={(note) => setEvidenceNote({ id: item.id, note })}
                        hint={translate("disputes.contactsHiddenHint")}
                      />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={busy || evidenceNote.note.trim().length < 3}
                          onClick={() => void run(async () => {
                            await addDisputeEvidence(item.id, { note: evidenceNote.note.trim(), file_ids: [] }, newIdempotencyKey());
                            setEvidenceNote(null);
                            setBookingDisputes(await myDisputes());
                          }, translate("disputes.evidenceAdded"))}
                          className="el-press h-11 flex-1 rounded-[12px] bg-primary text-[14px] font-semibold text-primary-foreground disabled:bg-slate-400"
                        >
                          {translate("common.send")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEvidenceNote(null)}
                          className="el-press h-11 flex-1 rounded-[12px] bg-muted text-[14px] font-semibold text-muted-foreground"
                        >
                          {translate("common.cancel")}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            }) : (
              <EmptyState
                icon={FileText}
                title={translate("disputes.emptyTitle")}
                subtitle={translate("disputes.emptySubtitle")}
              />
            )}
          </section>
        </main>
      );
    }

    if (screen === "dispute-detail" && disputeDetail) {
      // S5: one dispute as its participant sees it. Re-read on open and on demand, because the other side and the
      // operator add to it after the first report - a stale copy would hide the decision.
      const item = disputeDetail;
      const open = !["resolved", "rejected", "withdrawn", "closed"].includes(item.status);
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("dispute.detailTitle")} back={() => go("my-disputes")} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="rounded-[16px] border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[16px] font-semibold text-foreground">{disputeTypeLabel(item.type)}</p>
                  <p className="mt-1 text-[12px] text-muted-foreground">{formatDateTime(item.created_at)}</p>
                </div>
                <StatusBadge status={item.status} />
              </div>
              <p className="mt-2 text-[12px] text-muted-foreground">
                {translate("dispute.openedBy")}: {translateDynamic(`dispute.side.${item.opened_by_side}`) ?? item.opened_by_side}
              </p>
              {item.escalated && open && (
                <p className="mt-1 text-[12px] text-warning">{translate("dispute.escalated")}</p>
              )}
              <p className="mt-3 text-[14px] leading-6 text-secondary-foreground">{item.description}</p>
            </div>
            {item.evidence.length > 0 && (
              <div className="space-y-2 rounded-[16px] border border-border bg-card p-4">
                <p className="text-[13px] font-semibold text-muted-foreground">{translate("disputes.evidence")}</p>
                {item.evidence.map((entry, index) => (
                  <div key={index} className="rounded-[12px] bg-background px-3 py-2">
                    <p className="text-[12px] text-muted-foreground">
                      {translateDynamic(`dispute.side.${entry.author_side}`) ?? entry.author_side} · {formatDateTime(entry.created_at)}
                    </p>
                    <p className="mt-0.5 text-[13px] leading-5 text-secondary-foreground">
                      {entry.note || (entry.file_ids.length ? translate("disputes.filesAttached", { count: entry.file_ids.length }) : "-")}
                    </p>
                  </div>
                ))}
              </div>
            )}
            {item.resolution && (
              <p className="rounded-[12px] bg-accent px-3 py-2.5 text-[13px] leading-5 text-primary">
                {translate("disputes.decisionPrefix")} {item.resolution.text || disputeResolutionLabel(item.resolution.code ?? "") || item.resolution.code}
                {item.resolution.decided_at ? ` · ${formatDateTime(item.resolution.decided_at)}` : ""}
              </p>
            )}
            {open && (
              evidenceNote?.id === item.id ? (
                <div className="space-y-2">
                  <Field
                    label={translate("disputes.extraNoteLabel")}
                    multiline
                    value={evidenceNote.note}
                    onChange={(note) => setEvidenceNote({ id: item.id, note })}
                    hint={translate("disputes.contactsHiddenHint")}
                  />
                  <PrimaryButton
                    disabled={busy || evidenceNote.note.trim().length < 3}
                    onClick={() => void run(async () => {
                      const result = await addDisputeEvidence(item.id, { note: evidenceNote.note.trim(), file_ids: [] }, newIdempotencyKey());
                      setEvidenceNote(null);
                      setDisputeDetail(result.data);
                    }, translate("disputes.evidenceAdded"))}
                  >
                    {translate("common.send")}
                  </PrimaryButton>
                </div>
              ) : (
                <SecondaryButton onClick={() => setEvidenceNote({ id: item.id, note: "" })}>{translate("disputes.addEvidence")}</SecondaryButton>
              )
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => openDisputeDetail(item.id))}
              className="el-press h-10 w-full text-[13px] font-semibold text-muted-foreground"
            >
              {translate("dispute.refresh")}
            </button>
          </section>
        </main>
      );
    }

    if (screen === "listing-edit" && listingEdit) {
      // L3 / Q20: what changes, and whether it closes the open offers, is worked out before anything is sent.
      const { listing, form, back, confirming, openOffers } = listingEdit;
      const plan = planListingPatch(listing, form);
      const setForm = (patch: Partial<ListingEditForm>) =>
        setListingEdit({ ...listingEdit, form: { ...form, ...patch }, confirming: false });
      const allowWindow = windowEditable(listing);
      const save = () => void run(async () => {
        const result = await patchListing(listing.id, { expected_version: listing.version, ...plan.body });
        setListingWarnings(result.warnings.map((warning) => warning.code));
        setListingEdit(null);
        if (back === "client-listing-detail") await openListing(listing.id);
        else {
          await loadDriverTrips();
          go(back);
        }
      }, translate("listingOwner.saved"));
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("listingOwner.editTitle")} back={() => { setListingEdit(null); go(back); }} />
          <section className="el-enter flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
            <Field
              label={translate("listingOwner.priceLabel") + (listing.price_basis === "per_seat" ? translate("listingEdit.perSeatSuffix") : "")}
              type="number"
              value={form.price}
              onChange={(price) => setForm({ price })}
            />
            <Field
              label={translate("listingOwner.commentLabel")}
              value={form.comment}
              multiline
              onChange={(comment) => setForm({ comment })}
              hint={translate("disputes.contactsHiddenHint")}
            />
            {allowWindow ? (
              <>
                <Field
                  label={translate("listingOwner.windowStart")}
                  type="datetime-local"
                  value={form.windowStart}
                  onChange={(windowStart) => setForm({ windowStart })}
                />
                <Field
                  label={translate("listingOwner.windowEnd")}
                  type="datetime-local"
                  value={form.windowEnd}
                  onChange={(windowEnd) => setForm({ windowEnd })}
                />
              </>
            ) : (
              <p className="text-[12px] leading-5 text-muted-foreground">{translate("listingOwner.windowFromTrip")}</p>
            )}
            <p className="text-[12px] leading-5 text-muted-foreground">{translate("listingOwner.nonMaterialNote")}</p>
            {plan.material && (
              <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
                {translate("listingOwner.materialWarning")}
                {openOffers !== null ? ` ${translate("listingOwner.openOffers", { count: openOffers })}` : ""}
              </p>
            )}
            {plan.invalid && (
              <p className="text-[12px] leading-5 text-destructive">
                {translateDynamic(`listingOwner.invalid.${plan.invalid}`) ?? plan.invalid}
              </p>
            )}
            <div className="mt-auto">
              <PrimaryButton
                disabled={busy || plan.empty || Boolean(plan.invalid)}
                onClick={() => (plan.material && !confirming ? setListingEdit({ ...listingEdit, confirming: true }) : save())}
              >
                {plan.material && confirming ? translate("listingOwner.materialConfirm") : translate("common.save")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "listing-matches" && matchesFor) {
      // A request's matches are trip offers; a trip offer's matches are client requests. Same endpoint, same
      // ranking, and in both directions the person picks - nothing here accepts anything on their behalf.
      const isRequest = matchesFor.kind === "request";
      const back = () => go(isRequest ? "client-listing-detail" : "driver-routes");
      // Same two answers as the feed: what matches the published listing, and what is only near it.
      const matchSections = splitFeedGroups(matches);
      const matchCard = (item: MatchDTO, isAlternative = false) => {
        const reason = isAlternative ? alternativeReasonLabel(item.match.reasons) : null;
        return (
          <div
            key={item.listing.id}
            className={cls(
              "rounded-[16px] border bg-card p-4",
              isAlternative ? "border-dashed border-muted-foreground/40" : "border-border",
            )}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="min-w-0 flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                <MapPin size={14} color="var(--primary)" />
                <span className="truncate">
                  {endLabel(item.listing.origin_stop, item.listing.origin_point)} {"->"}{" "}
                  {endLabel(item.listing.destination_stop, item.listing.destination_point)}
                </span>
              </span>
              <span
                className={cls(
                  "shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold",
                  isAlternative ? "bg-warning/14 text-warning" : "bg-accent text-primary",
                )}
              >
                {reason ?? matchLabel(item.match.match_type)}
              </span>
            </div>
            <div className="flex items-center justify-between text-[13px] text-muted-foreground">
              <span>{shortDate(item.listing.departure_window_start)}</span>
              <span className="font-semibold text-foreground">
                {formatUzs((item.comparable_total_minor ?? item.listing.total_minor) / 100)}
              </span>
            </div>
            {item.reputation.completed_bookings > 0 && (
              <p className="mt-1 text-[12px] text-muted-foreground">
                {translate("matches.completedCount", { count: item.reputation.completed_bookings })}
                {/* U6: no invented rating for a new account (§8.2) - the label says which case this is. */}
                {item.reputation.average_rating !== null && item.reputation.average_rating !== undefined
                  ? ` · ${translate("matches.rating", { rating: item.reputation.average_rating.toFixed(1) })}`
                  : ` · ${translate("matches.notRated")}`}
              </p>
            )}
            <div className="mt-3">
              <button
                type="button"
                onClick={() => {
                  if (isRequest) {
                    setSelectedOffer(item as unknown as FeedItemDTO);
                    setOfferBid({ ...offerBid, price: String(Math.round(item.listing.unit_price_minor / 100)), seats: 1 });
                    go("client-offer-bid");
                  } else {
                    setSelectedRequest(item as unknown as FeedItemDTO);
                    setBidPrice(String(Math.round(item.listing.total_minor / 100)));
                    setProposalTripId(trips[0]?.id ?? "");
                    void loadRivalOffers(item.listing.id);
                    go("driver-bid");
                  }
                }}
                className={cls(
                  "el-press h-10 w-full rounded-[10px] text-[14px] font-semibold",
                  isAlternative ? "border border-primary text-primary" : "bg-primary text-primary-foreground",
                )}
              >
                {translate("matches.makeOffer")}
              </button>
            </div>
          </div>
        );
      };
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={isRequest ? translate("matches.titleTrips") : translate("matches.titleRequests")} back={back} />
          <section className="el-enter el-stagger min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <p className="text-[13px] leading-5 text-muted-foreground">
              {isRequest
                ? translate("matches.introTrips")
                : translate("matches.introRequests")}
            </p>
            {matchScope === "confirmed_stops" && matches.length > 0 && (
              <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
                {confirmedStopsNote()}
              </p>
            )}
            {busy && !matches.length ? <ListSkeleton /> : matches.length ? (
              <>
                {matchSections.primary.map((item) => matchCard(item))}
                {matchSections.alternative.length > 0 && (
                  <div className="pt-2">
                    <h2 className="text-[16px] font-bold text-foreground">{translate("match.alternativesTitle")}</h2>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      {translate("match.alternativesNote")}
                    </p>
                  </div>
                )}
                {matchSections.alternative.map((item) => matchCard(item, true))}
              </>
            ) : (
              <EmptyState
                icon={Truck}
                title={isRequest ? translate("matches.emptyTrips") : translate("matches.emptyRequests")}
                subtitle={isRequest
                  ? translate("matches.emptyTripsSubtitle")
                  : translate("matches.emptyRequestsSubtitle")}
              />
            )}
          </section>
        </main>
      );
    }

    if (screen === "booking-chat" && openBooking) {
      const thread = openBooking;
      const back = () => go(thread.side === "driver" ? "driver-order-detail" : "client-booking-detail");
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("bookingChat.title")} back={back} />
          <section className="el-enter min-h-0 flex-1 space-y-2 overflow-y-auto px-5 py-4">
            {chatHasMore && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void run(() => loadChat(thread.id, chatMessages.length + CHAT_PAGE))}
                className="el-press h-9 w-full rounded-[10px] bg-card text-[13px] font-semibold text-primary"
              >
                {translate("bookingChat.olderMessages")}
              </button>
            )}
            {chatMessages.length === 0 && !busy && (
              <EmptyState
                icon={Bell}
                title={translate("bookingChat.emptyTitle")}
                subtitle={translate("bookingChat.emptySubtitle")}
              />
            )}
            {chatMessages.map((message) => (
              <div
                key={message.id}
                className={cls(
                  "max-w-[80%] rounded-[14px] px-3.5 py-2.5",
                  message.is_mine ? "ml-auto bg-primary text-primary-foreground" : "mr-auto bg-card text-foreground",
                )}
              >
                <p className="whitespace-pre-wrap text-[14px] leading-5">
                  {message.moderation_status === "hidden_by_staff"
                    ? translate("bookingChat.hiddenByStaff")
                    : message.quick_reply_code
                      // A quick reply carries a code, not text: it is rendered in the reader's language.
                      ? quickReplyLabel(message.quick_reply_code)
                      : message.text}
                </p>
                <p className={cls("mt-1 text-[11px]", message.is_mine ? "text-primary-foreground/70" : "text-slate-400")}>
                  {formatDateTime(message.created_at)}
                </p>
              </div>
            ))}
          </section>
          {/* The trip is over and the grace period has run out: the conversation stays readable and stops
              taking messages (Q44 / CHAT_WRITABLE_AFTER_TERMINAL). Drawing the composer anyway would make
              the refusal look like a failure to send. */}
          {chatState && !chatState.writable ? (
            <div className="shrink-0 border-t border-border bg-card px-5 py-4">
              <p className="text-[14px] font-semibold text-foreground">{translate("chat.closedTitle")}</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{translate("chat.closedBody")}</p>
            </div>
          ) : (
          <div className="shrink-0 border-t border-border bg-card px-5 py-3">
            {/* Counting down only once the booking is terminal; while the trip runs there is no deadline. */}
            {chatState?.writable_until && (
              <p className="mb-2 text-[11px] leading-4 text-muted-foreground">
                {translate("chat.closesSoon")} {formatDateTime(chatState.writable_until)}
              </p>
            )}
            <div className="mb-2 flex flex-wrap gap-2">
              {quickRepliesFor(thread.side).map((code) => (
                <button
                  key={code}
                  type="button"
                  disabled={chatSending}
                  onClick={() => {
                    if (chatSending) return;
                    setChatSending(true);
                    setChatFailed(null);
                    void sendMessage(thread.id, { quick_reply_code: code }, newIdempotencyKey())
                      .then(() => loadChat(thread.id, Math.max(chatMessages.length + 1, CHAT_PAGE)))
                      .catch(() => setChatFailed(quickReplyLabel(code)))
                      .finally(() => setChatSending(false));
                  }}
                  className="el-press rounded-full border border-border bg-background px-3 py-1.5 text-[12px] font-medium text-foreground disabled:opacity-60"
                >
                  {quickReplyLabel(code)}
                </button>
              ))}
            </div>
            {chatWarnings.length > 0 && (
              <p className="mb-2 text-[12px] leading-5 text-warning">
                {translate("bookingChat.contactsHidden", { codes: chatWarnings.join(", ") })}
              </p>
            )}
            {chatFailed && (
              <div className="mb-2 flex items-center justify-between gap-2 rounded-[10px] bg-destructive/10 px-3 py-2">
                <span className="min-w-0 flex-1 truncate text-[12px] text-destructive">{translate("bookingChat.notSent", { text: chatFailed })}</span>
                <button
                  type="button"
                  onClick={() => { setChatDraft(chatFailed); setChatFailed(null); }}
                  className="el-press shrink-0 text-[12px] font-semibold text-destructive"
                >
                  {translate("common.retry")}
                </button>
              </div>
            )}
            <div className="flex items-end gap-2">
              <textarea
                value={chatDraft}
                onChange={(event) => setChatDraft(event.target.value)}
                rows={1}
                placeholder={translate("bookingChat.placeholder")}
                className="min-h-[44px] flex-1 resize-none rounded-[12px] border border-border bg-card px-4 py-2.5 text-[15px] text-foreground outline-none"
              />
              <button
                type="button"
                disabled={chatSending || !chatDraft.trim()}
                onClick={() => {
                  const text = chatDraft.trim();
                  if (!text || chatSending) return;   // double-submit protection: one send in flight
                  setChatSending(true);
                  setChatDraft("");
                  setChatFailed(null);
                  void sendMessage(thread.id, { text }, newIdempotencyKey())
                    .then((result) => {
                      setChatWarnings(result.warnings.map((warning) => warning.code));
                      return loadChat(thread.id, Math.max(chatMessages.length + 1, CHAT_PAGE));
                    })
                    .catch(() => setChatFailed(text))
                    .finally(() => setChatSending(false));
                }}
                className="el-press flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] bg-primary text-primary-foreground disabled:bg-slate-400"
                aria-label={translate("common.send")}
              >
                <Navigation size={18} />
              </button>
            </div>
            <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
              {translate("bookingChat.autoMaskNote")}
            </p>
          </div>
          )}
        </main>
      );
    }

    if (screen === "booking-tracking" && openBooking) {
      const thread = openBooking;
      const booking = thread.side === "driver" ? driverBooking : clientBooking;
      const back = () => go(thread.side === "driver" ? "driver-order-detail" : "client-booking-detail");
      const liveOpen = Boolean(flags?.tracking_enabled && tracking?.window.is_open && tracking?.last_point);
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("bookingTracking.title")} back={back} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[13px] font-semibold text-secondary-foreground">{translate("bookingTracking.progressTitle")}</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {translate("bookingTracking.progressHint")}
              </p>
              <ol className="mt-3 space-y-2">
                {(booking?.service_type === "passenger" ? PASSENGER_PROGRESS : PARCEL_PROGRESS).map(([status, label]) => {
                  const ladder = booking?.service_type === "passenger" ? PASSENGER_PROGRESS : PARCEL_PROGRESS;
                  const index = ladder.findIndex(([value]) => value === booking?.service_status);
                  const position = ladder.findIndex(([value]) => value === status);
                  const done = index >= 0 && position <= index;
                  return (
                    <li key={status} className="flex items-center gap-3">
                      <span className={cls("h-2.5 w-2.5 shrink-0 rounded-full", done ? "bg-success" : "bg-slate-300")} />
                      <span className={cls("text-[14px]", done ? "font-semibold text-foreground" : "text-slate-400")}>{label}</span>
                    </li>
                  );
                })}
              </ol>
            </div>

            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[13px] font-semibold text-secondary-foreground">{translate("bookingTracking.liveTitle")}</p>
              {trackingError && <p className="mt-1 text-[13px] text-destructive">{trackingError}</p>}
              {!trackingError && !flags?.tracking_enabled && (
                <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                  {translate("bookingTracking.liveDisabled")}
                </p>
              )}
              {!trackingError && flags?.tracking_enabled && !liveOpen && (
                <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                  {trackingWindowText(tracking?.window.reason ?? "")}
                </p>
              )}
              {liveOpen && tracking?.last_point && (
                <>
                  <p className="mt-1 flex items-center gap-2 text-[14px] font-medium text-foreground">
                    {/*
                      The one thing on screen allowed to keep moving, and only while the fix really is current
                      (AC27/AC28): a dot that kept pulsing over a stale point would be the app claiming a live
                      GPS it does not have.
                    */}
                    <span
                      className={cls(
                        "h-2.5 w-2.5 shrink-0 rounded-full",
                        tracking.freshness === "fresh" ? "el-live-dot bg-success" : "bg-slate-400",
                      )}
                    />
                    {translate("bookingTracking.lastPoint", { time: formatDateTime(tracking.last_point.captured_at) })}
                  </p>
                  <p className="mt-1 text-[13px] text-muted-foreground">
                    {tracking.last_point.lat.toFixed(5)}, {tracking.last_point.lng.toFixed(5)}
                    {tracking.last_point.low_accuracy ? ` · ${translate("bookingTracking.lowAccuracy")}` : ""}
                  </p>
                  <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                    {translate("bookingTracking.sourceLine", { freshness: trackingFreshnessLabel(tracking.freshness) })}
                  </p>
                </>
              )}
            </div>

            {tracking?.eta_window_start && (
              <div className="rounded-[16px] bg-accent p-4">
                <p className="text-[13px] font-semibold text-primary">{translate("bookingTracking.etaTitle")}</p>
                <p className="mt-1 text-[15px] font-semibold text-foreground">
                  {shortDate(tracking.eta_window_start)} - {shortDate(tracking.eta_window_end ?? undefined)}
                </p>
                {tracking.eta_is_estimate && (
                  <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{translate("bookingTracking.etaDisclaimer")}</p>
                )}
              </div>
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-listing-detail" && listingDetail) {
      const listing = listingDetail;
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("listingDetail.title")} back={() => go("client-orders")} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <ListingCard listing={listing} />
            {[
              [endRowLabel(listing.origin_stop, translate("listingDetail.pickupStop"), translate("listingDetail.pickupPoint")), endLabel(listing.origin_stop, listing.origin_point)],
              [endRowLabel(listing.destination_stop, translate("listingDetail.dropoffStop"), translate("listingDetail.dropoffPoint")), endLabel(listing.destination_stop, listing.destination_point)],
              [translate("listingDetail.departureWindow"), `${shortDate(listing.departure_window_start)} - ${shortDate(listing.departure_window_end)}`],
              [translate("common.price"), formatUzs(listing.total_minor / 100)],
              [translate("listingDetail.parcel"), listing.parcel
                ? translate("listingDetail.parcelValue", { type: PARCEL_TYPES.find(([value]) => value === listing.parcel?.parcel_type)?.[1] ?? "-", weight: Math.round((listing.parcel.weight_g ?? 0) / 100) / 10 })
                : "-"],
              [translate("listingOwner.commentLabel"), listing.comment || "-"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{label}</p>
                <p className="mt-1 text-[14px] font-medium text-foreground">{value}</p>
              </div>
            ))}
            <ParcelPhoto
              photo={listing.parcel?.photo}
              label={translate("listingDetail.parcelPhoto")}
              onRefresh={() => void run(() => openListing(listing.id))}
            />
            {listing.status === "published" && listingThreads.length === 0 && (
              <EmptyState icon={Package} title={translate("listingBids.emptyTitle")} subtitle={translate("listingBids.emptySubtitle")} />
            )}
            {listingThreads.length > 0 && (
              <PrimaryButton onClick={() => go("client-listing-bids")}>{translate("listingDetail.viewOffers")}</PrimaryButton>
            )}
            {listing.status === "published" && (
              <SecondaryButton onClick={() => void run(() => openMatches(listing.id, listing.kind))}>
                {translate("listingDetail.viewMatches")}
              </SecondaryButton>
            )}
            {["draft", "published", "paused"].includes(listing.status) && (
              <SecondaryButton
                danger
                onClick={() =>
                  void run(async () => {
                    await cancelListing(listing.id, listing.version, "client_changed_plan");
                    await loadMyListings();
                    go("client-orders");
                  }, translate("listingDetail.cancelled"))
                }
              >
                {translate("listingDetail.cancel")}
              </SecondaryButton>
            )}
            {renderListingOwnerControls(listing, "client-listing-detail", () => openListing(listing.id))}
            {canShareListing(listing.status) && (
              <div className="space-y-2">
                <p className="px-1 text-[13px] font-semibold text-muted-foreground">{translate("listingShare.title")}</p>
                <ShareLinkPanel listingId={listing.id} />
              </div>
            )}
          </section>
        </main>
      );
    }

    if (screen === "client-listing-bids" && listingDetail) {
      const listing = listingDetail;
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("listingBids.title")} back={() => go("client-listing-detail")} />
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            {busy && !listingThreads.length ? <ListSkeleton /> : listingThreads.length ? listingThreads.map((thread) => {
              const version = thread.current_version;
              return (
                <div key={thread.id} className="rounded-[16px] border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[16px] font-semibold text-foreground">{thread.driver.label}</p>
                      <p className="text-[13px] text-muted-foreground">
                        {version ? `${endLabel(version.pickup_stop, version.pickup_point)} -> ${endLabel(version.dropoff_stop, version.dropoff_point)}` : "-"}
                      </p>
                      <p className="mt-1 text-[13px] text-muted-foreground">
                        {version ? `${shortDate(version.pickup_window_start)} - ${shortDate(version.pickup_window_end)}` : "-"}
                      </p>
                    </div>
                    <p className="text-[17px] font-bold text-primary">{version ? formatUzs(version.total_minor / 100) : "-"}</p>
                  </div>
                  {version?.message && <p className="mt-2 text-[13px] leading-5 text-secondary-foreground">{version.message}</p>}
                  {version && version.status === "active" && (
                    <div className="mt-3 empty:hidden">
                      <StaleConfirmation
                        threadId={thread.id}
                        side="client"
                        version={version}
                        onDone={() => void listListingProposals(listing.id).then(setListingThreads)}
                      />
                    </div>
                  )}
                  {version && version.status === "active" && version.author_side === "driver" && (
                    <div className="mt-3">
                      {counterFor === thread.id ? (
                        <div className="space-y-3">
                          <Field
                            label={translate("listingBids.yourPrice")}
                            type="number"
                            value={counterPrice}
                            placeholder={String(Math.round(version.total_minor / 100))}
                            onChange={setCounterPrice}
                          />
                          <BonusConsentPanel
                            listingId={listing.id}
                            unitPriceMinor={soumToMinor(counterPrice)}
                            quantity={version.quantity}
                            choice={counterConsent}
                            onChoice={setCounterConsent}
                            refreshToken={consentRefresh}
                          />
                          <div className="flex gap-2">
                            <button
                              type="button"
                              disabled={counterPending || busy || soumToMinor(counterPrice) <= 0}
                              onClick={() => void run(() => sendCounter(thread.id, version.revision, () => openListing(listing.id, "client-listing-bids"), true), translate("listingBids.counterSent"))}
                              className="h-11 flex-1 rounded-[12px] bg-primary text-[14px] font-semibold text-primary-foreground disabled:bg-slate-400"
                            >
                              {counterPending ? translate("common.sending") : translate("common.send")}
                            </button>
                            <button
                              type="button"
                              onClick={() => { setCounterFor(null); setCounterPrice(""); }}
                              className="el-press h-11 flex-1 rounded-[12px] bg-muted text-[14px] font-semibold text-muted-foreground"
                            >
                              {translate("common.cancel")}
                            </button>
                          </div>
                        </div>
                      ) : version.price_revisions_left.client > 0 ? (
                        <button
                          type="button"
                          onClick={() => { setCounterFor(thread.id); setCounterPrice(String(Math.round(version.total_minor / 100))); }}
                          className="el-press h-11 w-full rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
                        >
                          {translate("listingBids.counterButton", { count: version.price_revisions_left.client })}
                        </button>
                      ) : (
                        <p className="text-[12px] leading-5 text-muted-foreground">
                          {translate("listingBids.noRevisionsLeft")}
                        </p>
                      )}
                    </div>
                  )}
                  {version && version.status === "active" && version.author_side === "client" && (
                    <p className="mt-3 text-[12px] leading-5 text-muted-foreground">
                      {translate("listingBids.awaitingDriver")}
                    </p>
                  )}
                  {version && version.status === "active" && version.author_side === "driver" && counterFor !== thread.id && (
                    <div className="mt-3 space-y-2">
                      <AcceptConsentPanel
                        quote={version.promo_quote?.view === "client" ? version.promo_quote : null}
                        choice={acceptConsent[thread.id] ?? NO_CONSENT}
                        onChoice={(choice) => setAcceptConsent((all) => ({ ...all, [thread.id]: choice }))}
                      />
                      {!version.promo_quote && <NoDiscountNote reason={version.promo_unavailable_reason} />}
                      <PrimaryButton
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const promo = consentBody(acceptConsent[thread.id] ?? NO_CONSENT);
                            const body = acceptBody(version.id, listing.terms_version, promo);
                            const accepted = await oncePerAction(`accept:${thread.id}:${version.id}`,
                              (key) => acceptProposal(thread.id, body, key)).catch(requoteAndThrow);
                            await openListing(listing.id);
                            // "Driver chosen" is the moment the two of them need to talk, so the chat is
                            // where this lands rather than back on a list - with the booking behind it, so
                            // back goes to the booking rather than to an empty screen.
                            await openClientBooking(accepted.data.id);
                            await openChat(accepted.data.id, "client");
                          }, translate("listingBids.driverChosen"))
                        }
                      >
                        {translate("listingBids.chooseDriver")}
                      </PrimaryButton>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void run(async () => {
                          try {
                            await rejectProposal(thread.id, version.revision);
                          } finally {
                            setListingThreads(await listListingProposals(listing.id).catch(() => listingThreads));
                          }
                        }, translate("proposal.rejected"))}
                        className="el-press h-11 w-full rounded-[12px] bg-destructive/10 text-[14px] font-semibold text-destructive"
                      >
                        {translate("proposal.reject")}
                      </button>
                    </div>
                  )}
                  {version && version.status !== "active" && (
                    <p className="mt-3 text-[12px] leading-5 text-muted-foreground">
                      {translate("listingBids.closed", { status: proposalStatusLabel(version.status) })}
                    </p>
                  )}
                </div>
              );
            }) : <EmptyState icon={Package} title={translate("listingBids.emptyTitle")} subtitle={translate("listingBids.emptySubtitle")} />}
            <p className="pt-2 text-center text-[12px] leading-5 text-muted-foreground">
              {translate("listingBids.identityHidden")}
            </p>
          </section>
        </main>
      );
    }

    if (screen === "client-bids") {
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("listingBids.title")} back={() => go("client-order-detail")} />
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            {busy && !bids.length ? <ListSkeleton /> : bids.length ? bids.map((bid) => (
              <div key={bid.id ?? bid.bid_id} className="rounded-[16px] border border-border bg-card p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[16px] font-semibold text-foreground">{bid.driver?.full_name ?? translate("dispute.side.driver")}</p>
                    <p className="text-[13px] text-muted-foreground">{bid.driver?.car_model ?? "-"} / {bid.driver?.plate_number ?? "-"}</p>
                    <p className="mt-1 text-[13px] text-muted-foreground">{translate("legacyOrder.rating", { rating: bid.driver?.rating ?? "-" })}</p>
                  </div>
                  <p className="text-[17px] font-bold text-primary">{formatUzs(bid.price)}</p>
                </div>
                <div className="mt-4">
                  <PrimaryButton
                    onClick={() => setConfirmAction({ type: "select-driver", bid })}
                  >
                    {translate("listingBids.chooseDriver")}
                  </PrimaryButton>
                </div>
              </div>
            )) : <EmptyState icon={Package} title={translate("listingBids.emptyTitle")} subtitle={translate("listingBids.emptySubtitle")} />}
          </section>
        </main>
      );
    }

    if (screen === "client-confirm" && orderDetail) {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("legacyOrder.confirmTitle")} back={() => go("client-order-detail")} />
          <section className="flex flex-1 flex-col justify-center gap-5 px-5 text-center">
            <CheckCircle className="mx-auto" size={72} color="var(--success)" />
            <p className="text-[16px] leading-6 text-secondary-foreground">{translate("legacyOrder.confirmBody")}</p>
            <PrimaryButton onClick={() => run(async () => { await confirmClientOrder(orderDetail.id); go("client-rating"); }, translate("legacyOrder.confirmed"))}>{translate("common.confirm")}</PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "client-rating" && selectedOrderId) {
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("rating.titleDriver")} back={() => go("client-orders")} />
          <section className="flex flex-1 flex-col gap-5 px-5 py-6">
            <p className="text-center text-[14px] text-muted-foreground">{translate("legacyOrder.ratingHint")}</p>
            <div className="flex justify-center gap-2">
              {[1, 2, 3, 4, 5].map((value) => (
                <button type="button" className="el-press" key={value} onClick={() => setRating(value)} aria-label={translate("legacyOrder.stars", { value })}>
                  <Star fill={value <= rating ? "var(--warning)" : "none"} color="var(--warning)" size={34} />
                </button>
              ))}
            </div>
            <Field label={translate("legacyOrder.ratingComment")} value={ratingComment} multiline onChange={setRatingComment} />
            <div className="mt-auto">
              <PrimaryButton onClick={() => run(async () => { await rateClientOrder(selectedOrderId, { rating, comment: ratingComment || null }); go("client-orders"); }, translate("legacyOrder.ratingSent"))}>{translate("legacyOrder.ratingSubmit")}</PrimaryButton>
              <button type="button" onClick={() => go("client-orders")} className="el-press mt-3 h-10 w-full text-[14px] font-semibold text-muted-foreground">
                {translate("legacyOrder.later")}
              </button>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-dispute" && orderDetail) {
      // The v1 server stores the Uzbek reason text as sent, so the value stays Uzbek and only the label follows
      // the reader's language.
      const reasons: Array<[string, string]> = [
        ["Haydovchi kelmadi", translate("legacyOrder.dispute.driverNoShow")],
        ["Posilka kechikdi", translate("legacyOrder.dispute.parcelLate")],
        ["Narx bo'yicha kelishmovchilik", translate("legacyOrder.dispute.priceDisagreement")],
        ["Boshqa muammo", translate("disputeType.other")],
      ];
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("legacyOrder.dispute.title")} back={() => go("client-order-detail")} />
          <section className="flex flex-1 flex-col gap-4 px-5 py-5">
            <label className="flex flex-col gap-1.5">
              <span className="text-[14px] font-medium text-secondary-foreground">{translate("legacyOrder.dispute.typeLabel")}</span>
              <select
                value={disputeReason}
                onChange={(event) => setDisputeReason(event.target.value)}
                className="h-[52px] rounded-[12px] border border-border bg-card px-4 text-[15px] text-foreground outline-none"
              >
                {reasons.map(([reason, reasonLabel]) => <option key={reason} value={reason}>{reasonLabel}</option>)}
              </select>
            </label>
            <Field label={translate("listingOwner.commentLabel")} value={disputeComment} multiline onChange={setDisputeComment} />
            <div className="mt-auto">
              <PrimaryButton
                onClick={() => run(async () => {
                  await openClientDispute(orderDetail.id, { reason: disputeReason, comment: disputeComment || null });
                  setDisputeComment("");
                  await openClientOrder(orderDetail.id);
                }, translate("legacyOrder.dispute.opened"))}
              >
                {translate("common.send")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "client-notifications" || screen === "driver-notifications") {
      // One inbox, both sides. There is no push provider yet (Q82), so this screen *is* the delivery channel -
      // a driver without it simply never learns that a client answered.
      const inboxRole: MobileRole = screen === "driver-notifications" ? "driver" : "client";
      return (
        <main className="flex flex-1 flex-col bg-background">
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="flex items-center gap-3">
              {inboxRole === "client" && (
                <SidebarButton className="shadow-none ring-1 ring-border" onClick={() => setSidebarOpen(true)} />
              )}
              <h1 className="text-[24px] font-bold text-foreground">{translate("notifications.title")}</h1>
            </div>
            {busy && !notifications.length ? <ListSkeleton /> : notifications.length ? notifications.map((item) => {
              // N4: the server sends keys, not text; the words are chosen here, in the reader's language.
              const body = inboxBody(item, translateDynamic);
              return (
                <button
                  key={item.id}
                  onClick={() => void run(() => openInboxItem(item))}
                  className={cls("el-press w-full rounded-[14px] border bg-card p-4 text-left", item.is_read ? "border-border" : "border-blue-200")}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-[15px] font-semibold text-foreground">{inboxTitle(item, translateDynamic)}</p>
                    {!item.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-destructive" aria-hidden="true" />}
                  </div>
                  {body && <p className="mt-1 text-[13px] text-muted-foreground">{body}</p>}
                  <p className="mt-1 text-[12px] text-muted-foreground">{formatDateTime(item.created_at)}</p>
                </button>
              );
            }) : <EmptyState icon={Bell} title={translate("notifications.empty")} />}
          </section>
          {inboxRole === "driver" && <BottomNav role={inboxRole} active={screen} go={go} unread={unreadNotifications} />}
        </main>
      );
    }

    if (screen === "client-profile") {
      const activeOrders = orders.filter((order) => !["confirmed", "cancelled"].includes(order.status)).length;
      const completedOrders = orders.filter((order) => order.status === "confirmed").length;
      const totalBids = orders.reduce((sum, order) => sum + (order.bids_count ?? 0), 0);
      const latestOrder = orders[0];
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("clientProfile.title")} back={() => go("client-home")} />
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 pb-24 pt-5">
            <div className="rounded-[18px] border border-border bg-card p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-accent text-primary">
                  <User size={28} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[18px] font-bold text-foreground">{clientName || auth.user?.full_name || translate("dispute.side.client")}</p>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">{auth.user?.phone}</p>
                  <span className="mt-2 inline-flex rounded-full bg-success/10 px-2.5 py-1 text-[11px] font-semibold text-success">
                    {translate("clientProfile.accountBadge")}
                  </span>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                [translate("common.total"), orders.length],
                [translate("clientProfile.statActive"), activeOrders],
                [translate("clientProfile.statBids"), totalBids],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-[12px] border border-border bg-card p-3 text-center">
                  <p className="text-[20px] font-bold text-foreground">{value}</p>
                  <p className="text-[11px] text-muted-foreground">{label}</p>
                </div>
              ))}
            </div>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[13px] font-semibold text-muted-foreground">{translate("clientProfile.ordersTitle")}</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-[12px] bg-slate-50 p-3">
                  <p className="text-[17px] font-bold text-foreground">{completedOrders}</p>
                  <p className="text-[12px] text-muted-foreground">{translate("status.completed")}</p>
                </div>
                <div className="rounded-[12px] bg-slate-50 p-3">
                  <p className="text-[17px] font-bold text-foreground">{latestOrder ? statusLabel(latestOrder.status) : "-"}</p>
                  <p className="text-[12px] text-muted-foreground">{translate("clientProfile.latestOrder")}</p>
                </div>
              </div>
            </div>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[13px] font-semibold text-muted-foreground">{translate("clientProfile.personalTitle")}</p>
              <div className="mt-3 space-y-3">
                <Field label={translate("clientProfile.fullName")} value={clientName} onChange={setClientName} placeholder={translate("clientProfile.fullNamePlaceholder")} />
                <PrimaryButton onClick={() => run(async () => { await updateClientProfile(clientName); await auth.refreshMe(); }, translate("clientProfile.updated"))}>{translate("common.save")}</PrimaryButton>
              </div>
            </div>
            <div className="space-y-2">
              <p className="px-1 text-[13px] font-semibold text-muted-foreground">{translate("clientProfile.quickActions")}</p>
              <ProfileActionRow icon={Package} label={translate("clientProfile.myOrders")} description={translate("clientProfile.myOrdersHint")} onClick={() => go("client-orders")} />
              <ProfileActionRow icon={Truck} label={translate("clientProfile.myProposals")} description={translate("clientProfile.myProposalsHint")} onClick={() => go("client-proposals")} />
              <ProfileActionRow icon={Tag} label={translate("clientProfile.bonus")} description={translate("clientProfile.bonusHint")} onClick={() => go("client-bonus")} />
              <ProfileActionRow icon={Bell} label={translate("notifications.title")} description={translate("clientProfile.notificationsHint")} onClick={() => go("client-notifications")} />
              <ProfileActionRow icon={FileText} label={translate("clientProfile.myDisputes")} description={translate("clientProfile.myDisputesHint")} onClick={() => go("my-disputes")} />
              <ProfileActionRow icon={Shield} label={translate("safety.centerTitle")} description={translate("safety.centerDescription")} onClick={() => go("safety-center")} />
              <ProfileActionRow icon={Headphones} label={translate("clientProfile.help")} description={translate("clientProfile.helpHint")} onClick={() => go("support")} />
              <ProfileActionRow icon={Shield} label={translate("clientProfile.settings")} description={translate("clientProfile.settingsHint")} onClick={() => go("settings")} />
              <ProfileActionRow icon={Home} label={translate("clientProfile.home")} description={translate("clientProfile.homeHint")} onClick={() => go("client-home")} />
              <ProfileActionRow danger icon={X} label={translate("clientProfile.logout")} description={translate("clientProfile.logoutHint")} onClick={() => run(async () => { await auth.logout(); go("role"); })} />
            </div>
          </section>
        </main>
      );
    }

    if (screen === "driver-home") {
      const approved = driverProfile?.verification_status === "approved";
      const showOnboardingActions = Boolean(driverProfile && !approved);
      return (
        <main className="flex flex-1 flex-col bg-background">
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 py-5">
            {pendingCode() && (
              <button
                type="button"
                onClick={() => go("driver-bonus")}
                className="el-press w-full rounded-[14px] border border-primary/30 bg-accent px-4 py-3 text-left text-[13px] font-semibold text-primary"
              >
                {translate("driverHome.pendingReferral", { code: pendingCode() ?? "" })}
              </button>
            )}
            <div className="flex items-start justify-between gap-3">
              <h1 className="min-w-0 flex-1 text-[24px] font-bold text-foreground">{approved ? translate("clientProfile.home") : translate("driverHome.completeProfileTitle")}</h1>
              {/* The driver's way into the inbox, with the unread count on it - the reference client's bell.
                  The nav bar already carries five tabs, and a sixth would be unreadable at this width. */}
              <button
                type="button"
                onClick={() => go("driver-notifications")}
                aria-label={unreadNotifications > 0 ? translate("driverHome.notificationsUnread", { count: unreadNotifications }) : translate("notifications.title")}
                className="el-press relative flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] border border-border bg-card"
              >
                <Bell size={18} className="text-foreground" />
                {unreadNotifications > 0 && (
                  <span className="absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-destructive px-1">
                    <span className="text-[9px] font-bold leading-none text-primary-foreground">
                      {unreadNotifications > 9 ? "9+" : unreadNotifications}
                    </span>
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => go("driver-income")}
                className="el-press shrink-0 rounded-[14px] border border-blue-100 bg-card px-3 py-2 text-right shadow-sm"
                aria-label={translate("driverHome.commissionBalance")}
              >
                <span className="block text-[10px] font-semibold text-muted-foreground">{translate("driverHome.commissionBalance")}</span>
                <span className="mt-0.5 flex items-center justify-end gap-1 text-[13px] font-bold text-foreground">
                  {walletState ? formatUzs(walletState.available_minor / 100) : "-"}
                  <ChevronRight size={14} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
                </span>
              </button>
            </div>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <p className="text-[15px] font-semibold text-foreground">{translate("driverHome.verificationStatus", { status: driverProfile?.verification_status ?? "new" })}</p>
              <p className="mt-2 text-[14px] leading-6 text-muted-foreground">{approved ? translate("driverHome.approvedHint") : translate("driverHome.onboardingHint")}</p>
            </div>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[15px] font-semibold text-foreground">{translate("driverHome.availabilityTitle")}</p>
                  <p className="text-[13px] text-muted-foreground">{approved ? translate("driverHome.available") : translate("driverHome.availabilityLocked")}</p>
                </div>
                <button
                  disabled={!approved || busy}
                  onClick={() => run(async () => { await setDriverAvailability(!driverProfile?.is_available); await loadDriverProfile(); }, translate("driverHome.availabilityUpdated"))}
                  className={cls("el-press h-8 w-14 rounded-full p-1", driverProfile?.is_available ? "bg-primary" : "bg-slate-300", !approved && "opacity-60")}
                >
                  <span className={cls("block h-6 w-6 rounded-full bg-card transition", driverProfile?.is_available && "translate-x-6")} />
                </button>
              </div>
            </div>
            {showOnboardingActions && (
              <>
                <PrimaryButton onClick={() => go("driver-profile-form")}>{translate("driverHome.completeProfile")}</PrimaryButton>
                <SecondaryButton onClick={() => go("driver-documents")}>{translate("driverHome.uploadDocuments")}</SecondaryButton>
              </>
            )}
            {approved && <SecondaryButton onClick={() => go("driver-feed")}>{translate("driverHome.viewMatchingOrders")}</SecondaryButton>}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-profile-form") {
      // Q94: the car is entered once and then belongs to the record, not to the form. v1 refuses a change
      // (`DRIVER_VEHICLE_LOCKED`), so leaving the inputs open would only invite the driver to type a new
      // plate and be told no on save. The lock follows the saved profile, not the approval: a car swapped
      // while "pending" is just as invisible to the client.
      const vehicleLocked = Boolean(driverProfile?.plate_number);
      const lockHint = vehicleLocked ? translate("driverProfileForm.vehicleLockedHint") : undefined;
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("driverProfileForm.title")} back={() => go("driver-home")} />
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <Field label={translate("driverProfileForm.fullName")} value={driverForm.full_name} onChange={(v) => setDriverForm({ ...driverForm, full_name: v })} />
            {vehicleLocked && (
              <div className="rounded-[14px] border border-border bg-background p-4">
                <p className="text-[13px] font-semibold text-foreground">{translate("driverProfileForm.vehicleLockedTitle")}</p>
                <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                  {translate("driverProfileForm.vehicleLockedBody")}
                </p>
              </div>
            )}
            <Field
              label={translate("driverProfileForm.carModel")}
              value={driverForm.car_model}
              placeholder={translate("driverProfileForm.carModelPlaceholder")}
              disabled={vehicleLocked}
              hint={lockHint}
              onChange={(v) => setDriverForm({ ...driverForm, car_model: v })}
            />
            <Field
              label={translate("driverProfileForm.carColor")}
              value={driverForm.car_color}
              placeholder={translate("driverProfileForm.carColorPlaceholder")}
              disabled={vehicleLocked}
              hint={lockHint}
              onChange={(v) => setDriverForm({ ...driverForm, car_color: v })}
            />
            <Field
              label={translate("driverProfileForm.plateNumber")}
              value={driverForm.plate_number}
              placeholder={translate("driverProfileForm.plateNumberPlaceholder")}
              disabled={vehicleLocked}
              hint={lockHint}
              onChange={(v) => setDriverForm({ ...driverForm, plate_number: v })}
            />
            <Field
              label={translate("driverProfileForm.passengerSeats")}
              type="number"
              value={String(driverSeats)}
              disabled={vehicleLocked}
              hint={lockHint}
              onChange={(v) => setDriverSeats(Math.max(1, Number(v) || 1))}
            />
            <div className="grid grid-cols-2 gap-2">
              <Field
                label={translate("driverProfileForm.cargoKg")}
                type="number"
                value={driverCargoKg}
                disabled={vehicleLocked}
                onChange={setDriverCargoKg}
              />
              <Field
                label={translate("driverProfileForm.cargoLitres")}
                type="number"
                value={driverCargoLitres}
                disabled={vehicleLocked}
                onChange={setDriverCargoLitres}
              />
            </div>
            {vehicles.map((vehicle) => (
              <div key={vehicle.id} className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{translate("driverProfileForm.vehicleStatus")}</p>
                <p className="mt-1 text-[14px] font-medium text-foreground">
                  {vehicle.make_model} · {vehicle.plate_masked ?? vehicle.plate_number ?? "-"} · {vehicleStatusLabel(vehicle.verification_status)}
                </p>
              </div>
            ))}
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("driverProfileForm.routesAfterReview")}
            </p>
            <PrimaryButton
              onClick={() => run(async () => {
                // A locked profile sends the name only: the vehicle keys would be refused, and sending them
                // unchanged would still make every save depend on the server's idea of "unchanged".
                await updateDriverProfile(vehicleLocked ? { full_name: driverForm.full_name } : driverForm);
                const plate = driverForm.plate_number.replace(/\s/g, "").toUpperCase();
                const known = vehicles.some((vehicle) => (vehicle.plate_number ?? "").replace(/\s/g, "").toUpperCase() === plate);
                // The same car the v1 profile carries, registered once on the stage-2 side so a trip can use
                // it. `vehicles.length` is where Q94's "once" is enforced for this screen: a second car has
                // to go through staff, who approve it before any trip can use it.
                if (!vehicles.length && plate && driverForm.car_model.trim() && driverForm.car_color.trim() && !known) {
                  await createVehicle({
                    plate_number: plate,
                    make_model: driverForm.car_model.trim(),
                    color: driverForm.car_color.trim(),
                    seat_capacity: driverSeats,
                    // The ceiling every trip of this car is measured against (AC12).
                    cargo_max_weight_g: Math.round(Number(driverCargoKg) * 1000),
                    cargo_max_volume_ml: Math.round(Number(driverCargoLitres) * 1000),
                  });
                }
                await loadDriverProfile();
                await loadDriverTrips();
                go("driver-home");
              }, translate("driverProfileForm.saved"))}
            >
              {translate("common.save")}
            </PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "driver-documents") {
      // §17.1: five named slots, and the screen has to say which one it is *before* the camera opens and
      // which one it was afterwards. A row of identical "Yuklash" buttons is how a passport ends up in the
      // licence slot, and the driver then waits on a rejection that reads as if the document itself is wrong.
      const latestFor = (type: DriverDocumentType) =>
        [...driverDocuments].reverse().find((document) => document.document_type === type);
      const submitted = DRIVER_DOCUMENT_TYPES.filter((type) => latestFor(type)).length;
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("driverDocs.title")} back={() => go("driver-home")} />
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="rounded-[14px] border border-border bg-card p-4">
              <p className="text-[14px] font-semibold text-foreground">
                {translate("driverDocs.submittedCount", { submitted, total: DRIVER_DOCUMENT_TYPES.length })}
              </p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {translate("driverDocs.intro")}
              </p>
            </div>
            {DRIVER_DOCUMENT_TYPES.map((type) => {
              const document = latestFor(type);
              const state = document?.status ?? "missing";
              const tone =
                state === "approved" ? "bg-success/10 text-success"
                : state === "rejected" ? "bg-destructive/10 text-destructive"
                : state === "pending" ? "bg-warning/14 text-warning"
                : "bg-accent text-muted-foreground";
              return (
                <label key={type} className="flex cursor-pointer items-start gap-3 rounded-[14px] border border-border bg-card p-4">
                  <Camera size={24} color="var(--primary)" />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-[15px] font-semibold text-foreground">{docTypeLabel(type)}</span>
                      <span className={cls("rounded-full px-2 py-0.5 text-[11px] font-semibold", tone)}>
                        {translateDynamic(`docState.${state}`) ?? state}
                      </span>
                    </span>
                    <span className="mt-1 block text-[12px] leading-5 text-muted-foreground">{docTypeHint(type)}</span>
                    {/* A rejection without its reason sends the same photo back a second time. */}
                    {state === "rejected" && document?.rejection_reason && (
                      <span className="mt-1 block text-[12px] leading-5 text-destructive">
                        {translate("driverDocs.rejectionReason", { reason: document.rejection_reason })}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-[13px] font-semibold text-primary">
                    {document ? translate("driverDocs.reupload") : translate("driverDocs.upload")}
                  </span>
                  <input
                    type="file"
                    accept="image/*,.pdf"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (!file) return;
                      void run(async () => {
                        const uploaded = await uploadFile(file, type);
                        await submitDriverDocument({ document_type: type, file_url: uploaded.file_url, mime_type: uploaded.mime_type ?? file.type, size_bytes: uploaded.size_bytes ?? file.size });
                        await loadDriverDocuments();
                        await loadDriverProfile();
                        // The toast names the slot: after five uploads "Hujjat yuborildi" says nothing.
                      }, translate("driverDocs.uploadedForReview", { type: docTypeLabel(type) }));
                    }}
                  />
                </label>
              );
            })}
          </section>
        </main>
      );
    }

    if (screen === "driver-routes") {
      // A trip is new business too (`trip.create`), and a trip is what every offer hangs on - so the same
      // refusal covers it, rather than letting the driver plan a route they cannot sell.
      if (!driverApproved) {
        return (
          <main className="flex flex-1 flex-col bg-background">
            <section className="el-enter flex-1 space-y-3 overflow-y-auto px-5 py-5">
              <h1 className="text-[24px] font-bold text-foreground">{translate("driverRoutes.title")}</h1>
              <DriverVerificationGate
                status={driverProfile?.verification_status}
                onProfile={() => go("driver-profile-form")}
                onDocuments={() => go("driver-documents")}
                onSupport={() => go("support")}
              />
            </section>
            <BottomNav role="driver" active={screen} go={go} />
          </main>
        );
      }
      return (
        <main className="flex flex-1 flex-col bg-background">
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <div className="flex items-center justify-between">
              <h1 className="text-[24px] font-bold text-foreground">{translate("driverRoutes.title")}</h1>
              <button
                onClick={() => {
                  setTripForm({ vehicleId: "", corridorId: "", routeId: "", startAt: "", seats: 4, cargoKg: "20", cargoLitres: "100" });
                  setTripRoutes([]);
                  setRouteStopFilter(null);
                  go("driver-add-route");
                }}
                className="el-press flex h-10 w-10 items-center justify-center rounded-full bg-primary text-primary-foreground"
              >
                +
              </button>
            </div>
            {busy && !trips.length ? <ListSkeleton /> : trips.length ? trips.map((trip) => {
              const nextAction = tripNextAction(trip.status);
              return (
              <div key={trip.id} className="rounded-[14px] border border-border bg-card p-4">
                <button
                  type="button"
                  aria-label={translate("trip.detailsTitle")}
                  onClick={() => {
                    setOpenTripId(trip.id);
                    go("driver-trip-detail");
                  }}
                  className="el-press block w-full text-left"
                >
                  <span className="flex items-start justify-between gap-2">
                    <span className="text-[15px] font-semibold leading-6 text-foreground">
                      {trip.stops[0]?.stop.name_uz ?? "-"} {"->"} {trip.stops[trip.stops.length - 1]?.stop.name_uz ?? "-"}
                    </span>
                    <ChevronRight size={18} className="mt-1 shrink-0 text-muted-foreground" />
                  </span>
                  <span className="mt-1 block text-[13px] text-muted-foreground">
                    {translate("driverRoutes.tripMeta", { date: shortDate(trip.planned_start_at), stops: trip.stops.length, seats: trip.seat_capacity })}
                  </span>
                </button>
                <p className="mt-1 text-[13px] text-success">{translate("driverRoutes.status", { status: tripStatusLabel(trip.status) })}</p>
                {nextAction && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(async () => {
                      await tripAction(trip.id, nextAction[0], { expected_version: trip.version });
                      await loadDriverTrips();
                    }, translate("driverRoutes.tripStatusUpdated"))}
                    className="el-press mt-3 h-10 w-full rounded-[10px] bg-accent text-[14px] font-semibold text-primary"
                  >
                    {nextAction[1]}
                  </button>
                )}
                {trip.status === "planned" && (
                  <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
                    {translate("driverRoutes.boardingWindowHint")}
                  </p>
                )}
                {/* Q92: the driver is an author in this market, not only an answerer. A planned trip can be
                    put up with the driver's own starting price, and clients answer it with theirs. */}
                {tripOffers(trip.id).map((offer) => (
                  <div key={offer.id} className="mt-2 rounded-[12px] bg-slate-50 px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-semibold text-foreground">
                        {offer.service_type === "passenger" ? translate("driverRoutes.passengerOffer") : translate("driverRoutes.parcelOffer")}
                      </span>
                      <span className="text-[13px] font-bold text-primary">
                        {formatUzs(offer.unit_price_minor / 100)}
                        {offer.price_basis === "per_seat" ? translate("driverRoutes.perSeatSuffix") : ""}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[12px] text-muted-foreground">
                      {translate("driverRoutes.offerStatusLine", { status: listingStatusLabel(offer.status) })}
                    </p>
                    {/* Q98: published only - a draft nobody can open would always read "nobody has looked". */}
                    {offer.status === "published" && (
                      <p className="mt-0.5 text-[12px] text-muted-foreground">{viewCountLabel(offer.view_count)}</p>
                    )}
                    {offer.status === "draft" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void run(async () => {
                          await publishListing(offer.id, offer.version);
                          await loadDriverTrips();
                        }, translate("driverRoutes.published"))}
                        className="el-press mt-2 h-9 w-full rounded-[10px] bg-primary text-[13px] font-semibold text-primary-foreground"
                      >
                        {translate("driverRoutes.publish")}
                      </button>
                    )}
                    {offer.status === "published" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void run(() => openMatches(offer.id, offer.kind))}
                        className="el-press mt-2 h-9 w-full rounded-[10px] bg-accent text-[13px] font-semibold text-primary"
                      >
                        {translate("driverRoutes.viewMatches")}
                      </button>
                    )}
                    <div className="mt-2">
                      {renderListingOwnerControls(offer, "driver-routes", loadDriverTrips)}
                    </div>
                  </div>
                ))}
                {trip.status === "planned" && availableOfferServices(trip.id).length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      const first = trip.stops[0]?.stop.id ?? "";
                      const last = trip.stops[trip.stops.length - 1]?.stop.id ?? "";
                      setOfferForm({
                        tripId: trip.id,
                        // Open on a service this trip does not already advertise, so the second offer on a
                        // journey is one tap rather than a refusal.
                        serviceType: availableOfferServices(trip.id)[0],
                        originStopId: first,
                        destinationStopId: last,
                        price: "",
                      });
                      go("driver-offer-create");
                    }}
                    className="el-press mt-3 h-10 w-full rounded-[10px] border border-primary text-[14px] font-semibold text-primary"
                  >
                    {tripOffers(trip.id).length > 0 ? translate("driverRoutes.addAnotherOffer") : translate("driverRoutes.publishWithPrice")}
                  </button>
                )}
              </div>
              );
            }) : <EmptyState icon={Navigation} title={translate("driverRoutes.empty")} action={translate("driverRoutes.addRoute")} onAction={() => go("driver-add-route")} />}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-trip-detail" && openTripId) {
      // The trip's own view (availability, manifest), then O1 share links for the offers on it that are open.
      const shareable = tripOffers(openTripId).filter((offer) => canShareListing(offer.status));
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("trip.detailsTitle")} back={() => go("driver-routes")} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <DriverTripDetail tripId={openTripId} />
            {shareable.map((offer) => (
              <div key={offer.id} className="space-y-2">
                <p className="px-1 text-[13px] font-semibold text-muted-foreground">
                  {translate("listingShare.title")}: {offer.service_type === "passenger" ? translate("driverRoutes.passengerOffer") : translate("driverRoutes.parcelOffer")}
                </p>
                <ShareLinkPanel listingId={offer.id} />
              </div>
            ))}
          </section>
        </main>
      );
    }

    if (screen === "safety-center") {
      const back = () => go(auth.user?.role === "driver" ? "driver-profile" : "client-profile");
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("safety.centerTitle")} back={back} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <BlockPanel />
            <MyReportsList />
          </section>
        </main>
      );
    }

    if (screen === "driver-add-route") {
      const approvedVehicles = vehicles.filter((vehicle) => vehicle.verification_status === "approved");
      const chosenRoute = tripRoutes.find((route) => route.id === tripForm.routeId);
      const filteredTripRoutes = routesThroughStop(tripRoutes, routeStopFilter?.id);
      const tripReady = Boolean(
        tripForm.vehicleId && chosenRoute && tripForm.startAt && tripForm.seats > 0
        && Number(tripForm.cargoKg) > 0 && Number(tripForm.cargoLitres) > 0,
      );
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("driverRoutes.addRoute")} back={() => go("driver-routes")} />
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 py-5">
            <PickSelect
              label={translate("addRoute.vehicle")}
              placeholder={approvedVehicles.length ? translate("addRoute.vehiclePlaceholder") : translate("addRoute.noApprovedVehicle")}
              value={tripForm.vehicleId}
              options={approvedVehicles.map((vehicle) => [
                vehicle.id,
                translate("addRoute.vehicleOption", { model: vehicle.make_model, plate: vehicle.plate_masked ?? vehicle.plate_number ?? "-", seats: vehicle.seat_capacity }),
              ] as [string, string])}
              onChange={(value) => {
                const picked = approvedVehicles.find((vehicle) => vehicle.id === value);
                setTripForm({
                  ...tripForm,
                  vehicleId: value,
                  seats: picked?.seat_capacity ?? tripForm.seats,
                  cargoKg: picked?.cargo_max_weight_g ? String(Math.round(picked.cargo_max_weight_g / 1000)) : tripForm.cargoKg,
                  cargoLitres: picked?.cargo_max_volume_ml ? String(Math.round(picked.cargo_max_volume_ml / 1000)) : tripForm.cargoLitres,
                });
              }}
            />
            {approvedVehicles.length === 0 && (
              <p className="text-[12px] leading-5 text-destructive">
                {translate("addRoute.vehicleNeedsReview")}
              </p>
            )}
            <PickSelect
              label={translate("addRoute.corridor")}
              placeholder={translate("addRoute.corridorPlaceholder")}
              value={tripForm.corridorId}
              options={corridors.map((corridor) => [corridor.id, corridor.name] as [string, string])}
              onChange={(value) => {
                setTripForm({ ...tripForm, corridorId: value, routeId: "" });
                setTripRoutes([]);
                setRouteStopFilter(null);
                if (value) void run(async () => setTripRoutes(await listCorridorRoutes(value)));
              }}
            />
            {/* A corridor can have several approved routes; finding a stop by name shows which of them pass it.
                The stops themselves stay the route's own (the trip is planned on an operator-approved route). */}
            {tripRoutes.length > 1 && (
              <div className="space-y-2 rounded-[14px] border border-border p-3">
                {routeStopFilter ? (
                  <>
                    <p className="text-[13px] font-medium text-foreground">
                      {translate("tripPlan.stopFilter", { name: routeStopFilter.name })}
                    </p>
                    {filteredTripRoutes.length === 0 && (
                      <p className="text-[12px] leading-5 text-warning">
                        {translate("tripPlan.stopFilterNone", { name: routeStopFilter.name })}
                      </p>
                    )}
                    <button
                      type="button"
                      onClick={() => setRouteStopFilter(null)}
                      className="el-press text-[13px] font-semibold text-primary"
                    >
                      {translate("tripPlan.stopFilterClear")}
                    </button>
                  </>
                ) : (
                  <StopSearch
                    label={translate("tripPlan.stopSearchLabel")}
                    onSelect={(stop) => {
                      setRouteStopFilter({ id: stop.id, name: stop.name_uz });
                      const through = routesThroughStop(tripRoutes, stop.id);
                      const keep = through.some((route) => route.id === tripForm.routeId);
                      setTripForm({ ...tripForm, routeId: keep ? tripForm.routeId : through.length === 1 ? through[0].id : "" });
                    }}
                  />
                )}
              </div>
            )}
            <PickSelect
              label={translate("addRoute.route")}
              placeholder={tripForm.corridorId ? translate("addRoute.routePlaceholder") : translate("addRoute.pickCorridorFirst")}
              disabled={!tripForm.corridorId}
              value={tripForm.routeId}
              options={filteredTripRoutes.map((route) => [
                route.id,
                translate("addRoute.routeOption", { stops: route.stops.length, km: Math.round(route.distance_m / 1000), hours: Math.round(route.duration_s / 3600) }),
              ] as [string, string])}
              onChange={(value) => setTripForm({ ...tripForm, routeId: value })}
            />
            {Boolean(tripForm.corridorId) && tripRoutes.length === 0 && (
              <p className="text-[12px] leading-5 text-destructive">
                {translate("addRoute.noApprovedRoute")}
              </p>
            )}
            <Field
              label={translate("addRoute.departureTime")}
              type="datetime-local"
              value={tripForm.startAt}
              onChange={(v) => setTripForm({ ...tripForm, startAt: v })}
            />
            <Field
              label={translate("addRoute.freeSeats")}
              type="number"
              value={String(tripForm.seats)}
              onChange={(v) => setTripForm({ ...tripForm, seats: Math.max(1, Number(v) || 1) })}
            />
            <div className="grid grid-cols-2 gap-2">
              <Field
                label={translate("driverProfileForm.cargoKg")}
                type="number"
                value={tripForm.cargoKg}
                onChange={(v) => setTripForm({ ...tripForm, cargoKg: v })}
              />
              <Field
                label={translate("driverProfileForm.cargoLitres")}
                type="number"
                value={tripForm.cargoLitres}
                onChange={(v) => setTripForm({ ...tripForm, cargoLitres: v })}
              />
            </div>
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("addRoute.plannedOnApprovedRoute")}
            </p>
            <PrimaryButton
              disabled={!tripReady || busy}
              onClick={() => void run(async () => {
                if (!chosenRoute) return;
                const start = new Date(tripForm.startAt);
                await createTrip({
                  vehicle_id: tripForm.vehicleId,
                  route_version_id: chosenRoute.id,
                  planned_start_at: start.toISOString(),
                  planned_end_at: new Date(start.getTime() + chosenRoute.duration_s * 1000).toISOString(),
                  seat_capacity: tripForm.seats,
                  // AC12: the capacity the trip really offers; without it no parcel proposal can be sent.
                  cargo_capacity_weight_g: Math.round(Number(tripForm.cargoKg) * 1000),
                  cargo_capacity_volume_ml: Math.round(Number(tripForm.cargoLitres) * 1000),
                  max_detour_minutes: 15,
                  max_detour_m: 5000,
                  pickup_wait_minutes: 10,
                  stops: chosenRoute.stops.map((stop, index) => ({
                    stop_id: stop.stop_id,
                    seq: index + 1,
                    planned_arrival_at: new Date(start.getTime() + (stop.cumulative_duration_s ?? 0) * 1000).toISOString(),
                    dwell_minutes: 5,
                  })),
                });
                await loadDriverTrips();
                go("driver-routes");
              }, translate("addRoute.added"))}
            >
              {translate("common.save")}
            </PrimaryButton>
          </section>
        </main>
      );
    }

    if (screen === "driver-offer-create") {
      if (!driverApproved) {
        return (
          <main className="flex flex-1 flex-col bg-card">
            <TopBar title={translate("offerCreate.gateTitle")} back={() => go("driver-routes")} />
            <section className="el-enter flex-1 space-y-3 overflow-y-auto px-5 py-5">
              <DriverVerificationGate
                status={driverProfile?.verification_status}
                onProfile={() => go("driver-profile-form")}
                onDocuments={() => go("driver-documents")}
                onSupport={() => go("support")}
              />
            </section>
          </main>
        );
      }
      const trip = trips.find((item) => item.id === offerForm.tripId);
      const offerableServices = availableOfferServices(offerForm.tripId);
      const alreadyOffered = tripOffers(offerForm.tripId).map((offer) => offer.service_type);
      const stopOptions = (trip?.stops ?? []).map((stop) => [stop.stop.id, stop.stop.name_uz] as [string, string]);
      const window = offerWindowForTrip(trip, offerForm.originStopId);
      const seatsOrOne = offerForm.serviceType === "passenger" ? (trip?.seat_capacity ?? 1) : 1;
      const priceSoum = Math.round(Number(offerForm.price));
      const hasCargoRoom = Boolean(trip?.cargo_capacity_weight_g || trip?.cargo_capacity_volume_ml);
      const offerReady = Boolean(
        trip && offerForm.originStopId && offerForm.destinationStopId
        && offerForm.originStopId !== offerForm.destinationStopId
        && window && priceSoum > 0
        && (offerForm.serviceType === "passenger" || hasCargoRoom),
      );
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("offerCreate.title")} back={() => go("driver-routes")} />
          <section className="el-enter flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
            <div className="rounded-[14px] bg-background p-4">
              <p className="font-semibold text-foreground">
                {(trip?.stops[0]?.stop.name_uz ?? "-")} {"->"} {(trip?.stops[(trip?.stops.length ?? 1) - 1]?.stop.name_uz ?? "-")}
              </p>
              <p className="mt-1 text-[13px] text-muted-foreground">
                {translate("offerCreate.tripMeta", { date: trip ? shortDate(trip.planned_start_at) : "-", seats: trip?.seat_capacity ?? 0 })}
              </p>
            </div>

            {/* Q92: both service types are the driver's to publish. Passenger stays behind its flag (K7/Q91) -
                the model is always there, only the way in is gated. A service this trip already advertises is
                left out rather than shown and refused on send. */}
            {offerableServices.length > 1 && (
              <SegmentedControl
                value={offerForm.serviceType}
                options={[["passenger", translate("offerCreate.servicePassenger")], ["parcel", translate("offerCreate.serviceParcel")]] as const}
                onChange={(value) => setOfferForm({ ...offerForm, serviceType: value })}
              />
            )}
            {alreadyOffered.length > 0 && (
              <p className="text-[12px] leading-5 text-muted-foreground">
                {translate("offerCreate.alreadyOffered", {
                  services: alreadyOffered
                    .map((service) => (service === "passenger" ? translate("offerCreate.servicePassengerLower") : translate("offerCreate.serviceParcelLower")))
                    .join(translate("offerCreate.and")),
                })}
              </p>
            )}

            <PickSelect
              label={translate("offerCreate.from")}
              placeholder={translate("offerCreate.stopPlaceholder")}
              value={offerForm.originStopId}
              options={stopOptions}
              onChange={(value) => setOfferForm({ ...offerForm, originStopId: value })}
            />
            <PickSelect
              label={translate("offerCreate.to")}
              placeholder={translate("offerCreate.stopPlaceholder")}
              value={offerForm.destinationStopId}
              options={stopOptions}
              onChange={(value) => setOfferForm({ ...offerForm, destinationStopId: value })}
            />
            {offerForm.originStopId === offerForm.destinationStopId && offerForm.originStopId !== "" && (
              <p className="text-[12px] leading-5 text-destructive">{translate("offerCreate.sameStops")}</p>
            )}
            {window && (
              <div className="rounded-[14px] bg-accent px-4 py-3">
                <p className="text-[12px] font-semibold text-primary">{translate("offerCreate.departureWindow")}</p>
                <p className="mt-0.5 text-[15px] font-semibold text-foreground">
                  {shortDate(window.start)} - {shortDate(window.end)}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                  {translate("offerCreate.windowHint")}
                </p>
              </div>
            )}

            <Field
              label={offerForm.serviceType === "passenger" ? translate("offerCreate.pricePerSeat") : translate("offerCreate.priceParcel")}
              type="number"
              value={offerForm.price}
              onChange={(value) => setOfferForm({ ...offerForm, price: value })}
              placeholder={translate("offerCreate.pricePlaceholder")}
            />
            {offerForm.serviceType === "passenger" && priceSoum > 0 && (
              <p className="text-[12px] leading-5 text-muted-foreground">
                {translate("offerCreate.totalForSeats", { seats: seatsOrOne, total: formatUzs(priceSoum * seatsOrOne) })}
              </p>
            )}
            {offerForm.serviceType === "parcel" && !hasCargoRoom && (
              <p className="text-[12px] leading-5 text-destructive">
                {translate("offerCreate.noCargoRoom")}
              </p>
            )}
            {/* §5.3 / Q90: this is a starting price in an auction, not a tariff. Saying so here is what keeps
                the driver from reading the number back as a guaranteed fare. */}
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("offerCreate.startingPriceNote")}
            </p>

            <div className="mt-auto">
              <PrimaryButton
                disabled={!offerReady || busy}
                onClick={() => void run(async () => {
                  if (!trip || !window) return;
                  const created = await createListing(
                    {
                      kind: "trip_offer",
                      service_type: offerForm.serviceType,
                      trip_id: trip.id,
                      origin_stop_id: offerForm.originStopId,
                      destination_stop_id: offerForm.destinationStopId,
                      departure_window_start: window.start,
                      departure_window_end: window.end,
                      price_basis: offerForm.serviceType === "passenger" ? "per_seat" : "total",
                      unit_price_minor: priceSoum * 100,
                    } as ListingCreate,
                    newIdempotencyKey(),
                  );
                  // L1 creates a draft; the market only sees it once it is published (§5.3).
                  await publishListing(created.data.id, created.data.version);
                  await loadDriverTrips();
                  go("driver-routes");
                }, translate("driverRoutes.published"))}
              >
                {translate("offerCreate.submit")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "driver-feed") {
      // The tab is reachable from the bottom bar at any time, so the refusal lives here rather than in the
      // navigation: hiding the tab would leave an unverified driver wondering where the work is.
      if (!driverApproved) {
        return (
          <main className="flex flex-1 flex-col bg-background">
            <section className="el-enter flex-1 space-y-3 overflow-y-auto px-5 py-5">
              <h1 className="text-[24px] font-bold text-foreground">{translate("driverFeed.title")}</h1>
              <DriverVerificationGate
                status={driverProfile?.verification_status}
                onProfile={() => go("driver-profile-form")}
                onDocuments={() => go("driver-documents")}
                onSupport={() => go("support")}
              />
            </section>
            <BottomNav role="driver" active={screen} go={go} />
          </main>
        );
      }
      // One ordered page, two answers. The server ranks alternatives last, so the split preserves its order.
      const feedSections = splitFeedGroups(requestFeed);
      const requestCard = (item: FeedItemDTO, isAlternative = false) => {
        const reason = isAlternative ? alternativeReasonLabel(item.match.reasons) : null;
        return (
          <div
            key={item.listing.id}
            className={cls(
              "rounded-[16px] border bg-card p-4",
              // A suggestion is drawn as one: dashed edge, muted badge, same actions.
              isAlternative ? "border-dashed border-muted-foreground/40" : "border-border",
            )}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                <MapPin size={14} color="var(--primary)" />
                {endLabel(item.listing.origin_stop, item.listing.origin_point)} {"->"} {endLabel(item.listing.destination_stop, item.listing.destination_point)}
              </span>
              <span
                className={cls(
                  "shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold",
                  isAlternative ? "bg-warning/14 text-warning" : "bg-accent text-primary",
                )}
              >
                {reason ?? matchLabel(item.match.match_type)}
              </span>
            </div>
            <div className="flex items-center justify-between text-[13px] text-muted-foreground">
              <span>{shortDate(item.listing.departure_window_start)}</span>
              <span className="font-semibold text-foreground">{formatUzs(item.listing.total_minor / 100)}</span>
            </div>
            <div className="mt-3">
              <button
                onClick={() => {
                  setSelectedRequest(item);
                  setBidPrice(String(Math.round(item.listing.total_minor / 100)));
                  setProposalTripId(trips[0]?.id ?? "");
                  void loadRivalOffers(item.listing.id);
                  go("driver-bid");
                }}
                className={cls(
                  "el-press h-10 w-full rounded-[10px] text-[14px] font-semibold",
                  isAlternative
                    ? "border border-primary text-primary"
                    : "bg-primary text-primary-foreground",
                )}
              >
                {translate("driverFeed.sendOffer")}
              </button>
            </div>
          </div>
        );
      };
      return (
        <main className="flex flex-1 flex-col bg-background">
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <h1 className="text-[24px] font-bold text-foreground">{translate("driverFeed.title")}</h1>
            {/* Q92: a client request exists for both services, so the driver's feed has to be askable for both.
                Passenger stays behind its flag (Q91) - the model is never removed, only the way in is gated. */}
            {flags?.passenger_enabled && (
              <SegmentedControl
                value={driverServiceMode}
                options={[["passenger", translate("driverFeed.modeTaxi")], ["parcel", translate("driverFeed.modeParcel")]] as const}
                onChange={(value) => {
                  setDriverServiceMode(value);
                  void run(() => loadRequestFeed(value));
                }}
              />
            )}
            <div className="overflow-hidden rounded-[18px] border border-border bg-card">
              <LocationPointRow
                label={translate("driverFeed.from")}
                address={directionEndLabel(pickupEnd)}
                hasPoint={Boolean(pickupEnd.district || pickupEnd.stop)}
                onClick={() => openLocationSelector("pickup", "driver")}
                node="origin"
              />
              <DirectionLink />
              <LocationPointRow
                label={translate("driverFeed.to")}
                address={directionEndLabel(dropoffEnd)}
                hasPoint={Boolean(dropoffEnd.district || dropoffEnd.stop)}
                onClick={() => openLocationSelector("dropoff", "driver")}
                node="destination"
              />
            </div>
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("driverFeed.districtHint")}
            </p>
            <button
              type="button"
              onClick={() => go("driver-saved-searches")}
              className="el-press flex h-10 w-full items-center justify-center rounded-[10px] bg-accent text-[14px] font-semibold text-primary"
            >
              {translate("driverFeed.savedSearches")}
            </button>
            {matchScope === "confirmed_stops" && requestFeed.length > 0 && (
              <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
                {confirmedStopsNote()}
              </p>
            )}
            {busy && !requestFeed.length ? <ListSkeleton /> : requestFeed.length ? (
              <>
                {feedSections.primary.map((item) => requestCard(item))}
                {/* §6.4: the near misses are a second answer, not more of the first one. Their own heading and
                    their own sentence are what stop a driver reading a 09:00 trip as the 06:00 they asked for. */}
                {feedSections.alternative.length > 0 && (
                  <div className="pt-2">
                    <h2 className="text-[16px] font-bold text-foreground">{translate("match.alternativesTitle")}</h2>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      {translate("match.alternativesNote")}
                    </p>
                  </div>
                )}
                {feedSections.alternative.map((item) => requestCard(item, true))}
              </>
            ) : (
              <EmptyState
                icon={Package}
                title={translate("driverFeed.emptyTitle")}
                subtitle={pickupEnd.stop || pickupEnd.district ? translate("driverFeed.emptyTryOther") : translate("driverFeed.emptyPickFirst")}
              />
            )}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-orders") {
      return (
        <main className="flex flex-1 flex-col bg-background">
          <section className="el-enter el-stagger flex-1 space-y-3 overflow-y-auto px-5 py-5">
            <h1 className="text-[24px] font-bold text-foreground">{translate("driverOrders.title")}</h1>
            {busy && !driverBookings.length ? <ListSkeleton /> : driverBookings.length ? driverBookings.map((raw) => {
              const booking = raw as BookingDTO;
              return (
                <button
                  key={booking.id}
                  onClick={() => void run(() => openDriverBooking(booking.id))}
                  className="el-press w-full rounded-[16px] border border-border bg-card p-4 text-left"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                      <MapPin size={14} color="var(--primary)" />
                      {endLabel(booking.pickup.stop, booking.pickup.point)} {"->"}{" "}
                  {endLabel(booking.dropoff.stop, booking.dropoff.point)}
                    </span>
                    <StatusBadge status={booking.service_status} />
                  </div>
                  <div className="flex items-center justify-between text-[13px] text-muted-foreground">
                    <span>{shortDate(booking.pickup.window_start ?? undefined)}</span>
                    <span className="font-semibold text-foreground">{formatUzs(booking.total_minor / 100)}</span>
                  </div>
                </button>
              );
            }) : <EmptyState icon={Package} title={translate("driverOrders.empty")} />}
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    if (screen === "driver-bid" && selectedRequest) {
      const request = selectedRequest;
      // Same rule one screen deeper: a stale feed, a back button or a revoked approval can all land an
      // ineligible driver here, and the price field must not be the thing that tells them.
      if (!driverApproved) {
        return (
          <main className="flex flex-1 flex-col bg-card">
            <TopBar title={translate("driverBid.title")} back={() => go("driver-feed")} />
            <section className="el-enter flex-1 space-y-3 overflow-y-auto px-5 py-5">
              <DriverVerificationGate
                status={driverProfile?.verification_status}
                onProfile={() => go("driver-profile-form")}
                onDocuments={() => go("driver-documents")}
                onSupport={() => go("support")}
              />
            </section>
          </main>
        );
      }
      const plannedTrips = trips.filter((trip) => trip.status === "planned");
      // The offered pickup window is when this trip is actually at that stop, clipped to what the client asked
      // for. The server refuses a window the trip cannot keep, so the screen says so before sending.
      const chosenTrip = plannedTrips.find((trip) => trip.id === proposalTripId);
      const pickupWindow = proposalPickupWindow(chosenTrip, request);
      return (
        <main className="flex flex-1 flex-col bg-card">
          <TopBar title={translate("driverBid.title")} back={() => go("driver-feed")} />
          <section className="el-enter flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
            <div className="rounded-[14px] bg-background p-4">
              <p className="font-semibold text-foreground">
                {endLabel(request.listing.origin_stop, request.listing.origin_point)} {"->"}{" "}
                {endLabel(request.listing.destination_stop, request.listing.destination_point)}
              </p>
              <p className="text-[13px] text-muted-foreground">{translate("driverBid.clientPrice", { price: formatUzs(request.listing.total_minor / 100) })}</p>
              <p className="mt-1 text-[13px] text-muted-foreground">
                {translate("driverBid.departure", {
                  start: shortDate(request.listing.departure_window_start),
                  end: shortDate(request.listing.departure_window_end),
                })}
              </p>
            </div>
            <RivalOfferBoard offers={rivalOffers} unavailable={rivalOffersError} />
            <PickSelect
              label={translate("driverBid.trip")}
              placeholder={plannedTrips.length ? translate("driverBid.tripPlaceholder") : translate("driverBid.noPlannedTrips")}
              value={proposalTripId}
              options={plannedTrips.map((trip) => [
                trip.id,
                (trip.stops[0]?.stop.name_uz ?? "-") + " -> " + (trip.stops[trip.stops.length - 1]?.stop.name_uz ?? "-") + " · " + shortDate(trip.planned_start_at),
              ] as [string, string])}
              onChange={setProposalTripId}
            />
            {plannedTrips.length === 0 && (
              <p className="text-[12px] leading-5 text-destructive">
                {translate("driverBid.planTripFirst")}
              </p>
            )}
            {chosenTrip && !pickupWindow && (
              <p className="text-[12px] leading-5 text-destructive">
                {translate("driverBid.tripWindowMismatch")}
              </p>
            )}
            {pickupWindow && (
              <div className="rounded-[14px] bg-accent px-4 py-3">
                <p className="text-[12px] font-semibold text-primary">{translate("driverBid.pickupWindow")}</p>
                <p className="mt-0.5 text-[15px] font-semibold text-foreground">
                  {shortDate(pickupWindow.start)} - {shortDate(pickupWindow.end)}
                </p>
              </div>
            )}
            <Field label={translate("driverBid.priceLabel")} type="number" value={bidPrice} onChange={setBidPrice} placeholder={translate("driverBid.pricePlaceholder")} />
            {feeQuote && (
              // W11: an estimate under today's policy, held only when a client accepts - never money received (§9).
              <div className="rounded-[14px] border border-border bg-background p-4">
                <p className="text-[13px] font-semibold text-foreground">{translate("commissionPreview.title")}</p>
                <p className="mt-1 text-[14px] text-foreground">
                  {translate("commissionPreview.line", {
                    amount: formatUzs(feeQuote.quote.commission_minor / 100),
                    percent: bpsPercent(feeQuote.quote.fee_bps),
                    total: formatUzs(feeQuote.totalMinor / 100),
                  })}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{translate("commissionPreview.note")}</p>
              </div>
            )}
            {feeQuoteFailed && (
              <p className="text-[12px] leading-5 text-muted-foreground">{translate("commissionPreview.unavailable")}</p>
            )}
            <p className="text-[12px] leading-5 text-muted-foreground">
              {translate("driverBid.noHoldNote")}
            </p>
            <div className="mt-auto">
              <PrimaryButton
                disabled={!Number(bidPrice) || Number(bidPrice) <= 0 || !proposalTripId || !pickupWindow || busy}
                onClick={() => void run(async () => {
                  await submitProposal(
                    request.listing.id,
                    {
                      trip_id: proposalTripId,
                      // Q88: a point-ended request supplies its own places; sending stop ids is refused.
                      pickup_stop_id: request.listing.origin_stop?.id ?? null,
                      dropoff_stop_id: request.listing.destination_stop?.id ?? null,
                      pickup_window_start: pickupWindow?.start ?? request.listing.departure_window_start,
                      pickup_window_end: pickupWindow?.end ?? request.listing.departure_window_end,
                      price_basis: request.listing.price_basis,
                      quantity: request.listing.quantity,
                      unit_price_minor: Math.round(Number(bidPrice)) * 100,
                    },
                    newIdempotencyKey(),
                  );
                  await loadRequestFeed();
                  go("driver-feed");
                }, translate("driverBid.sent"))}
              >
                {translate("driverBid.send")}
              </PrimaryButton>
            </div>
          </section>
        </main>
      );
    }

    if (screen === "driver-order-detail" && driverBooking) {
      const booking = driverBooking;
      // The order the parcel machine really takes (verified against the API, 17.09.2026):
      // confirmed -> arrive_at_pickup -> pick_up (code) -> start_transit -> deliver (code) -> client completes.
      const nextAction =
        booking.service_status === "confirmed" ? ["arrive_at_pickup", translate("driverBooking.action.arrive")] :
        booking.service_status === "awaiting_pickup" ? ["pick_up", translate("driverBooking.action.pickUp")] :
        booking.service_status === "picked_up" ? ["start_transit", translate("driverBooking.action.startTransit")] :
        booking.service_status === "in_transit" ? ["deliver", translate("driverBooking.action.deliver")] : null;
      // B5: pick-up and delivery both need the code the client holds.
      const needsCode = nextAction?.[0] === "pick_up" || nextAction?.[0] === "deliver";
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("driverBooking.title")} back={() => go("driver-orders")} />
          <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
            <div className="rounded-[16px] border border-border bg-card p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
                  <MapPin size={14} color="var(--primary)" />
                  {endLabel(booking.pickup.stop, booking.pickup.point)} {"->"}{" "}
                  {endLabel(booking.dropoff.stop, booking.dropoff.point)}
                </span>
                <StatusBadge status={booking.service_status} />
              </div>
              <div className="flex items-center justify-between text-[13px] text-muted-foreground">
                <span>{shortDate(booking.pickup.window_start ?? undefined)}</span>
                <span className="font-semibold text-foreground">{formatUzs(booking.total_minor / 100)}</span>
              </div>
            </div>
            <PromoMoneyCard promo={booking.promo} />
            {[
              [endRowLabel(booking.pickup.stop, translate("driverBooking.pickupStop"), translate("driverBooking.pickupPoint")),
               endLabel(booking.pickup.stop, booking.pickup.point)],
              [endRowLabel(booking.dropoff.stop, translate("driverBooking.dropoffStop"), translate("driverBooking.dropoffPoint")),
               endLabel(booking.dropoff.stop, booking.dropoff.point)],
              [translate("dispute.side.client"), booking.client?.display_name ?? translate("driverBooking.clientHidden")],
              // Q44: the participant phones open when the service starts, not at accept.
              [translate("driverBooking.phone"), booking.client?.contact_phone ?? translate("driverBooking.phoneHidden")],
              // §9: the fare is cash between the two people; it never passes through ELCHI or the wallet.
              [translate("driverBooking.fare"), translate("driverBooking.fareCash", { amount: formatUzs(cashDueMinor(booking) / 100) })],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[14px] border border-border bg-card p-4">
                <p className="text-[12px] text-muted-foreground">{label}</p>
                <p className="mt-1 text-[14px] font-medium text-foreground">{value}</p>
              </div>
            ))}
            {booking.service_type === "parcel" && (
              <ParcelPhoto
                photo={booking.parcel_photo}
                label={translate("driverBooking.parcelPhoto")}
                onRefresh={() => void run(() => openDriverBooking(booking.id))}
              />
            )}
            {needsCode && (
              <>
                <Field
                  label={nextAction?.[0] === "pick_up" ? translate("driverBooking.handoverCode") : translate("driverBooking.deliveryCode")}
                  value={proofCode}
                  onChange={setProofCode}
                  placeholder={translate("driverBooking.codePlaceholder")}
                />
                <p className="text-[12px] leading-5 text-muted-foreground">
                  {nextAction?.[0] === "pick_up"
                    ? translate("driverBooking.codeFromSender")
                    : translate("driverBooking.codeFromRecipient")}
                </p>
              </>
            )}
            {(CASH_RECORDABLE[booking.service_type] ?? []).includes(booking.service_status) && (
              <CashAcknowledgement
                booking={booking}
                side="driver"
                busy={busy}
                amount={cashAmount}
                onAmountChange={setCashAmount}
                onReport={() => void run(() => reportCash(booking.id, "driver", booking.version), translate("driverBooking.cashRecorded"))}
                onDecide={(decision) =>
                  booking.cash_receipt && void run(() => decideCash(booking.id, "driver", booking.cash_receipt!, decision), translate("driverBooking.cashAnswered"))
                }
              />
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void run(() => openChat(booking.id, "driver"))}
                className="el-press h-11 flex-1 rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
              >
                {translate("driverBooking.messages")}
              </button>
              <button
                type="button"
                onClick={() => void run(() => openTracking(booking.id, "driver"))}
                className="el-press h-11 flex-1 rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
              >
                {translate("driverBooking.tracking")}
              </button>
            </div>
            {AMENDABLE_STATUSES.includes(booking.service_status) && (
              <SecondaryButton onClick={() => void run(() => openAmendments(booking.id, "driver"))}>
                {translate("driverBooking.amend")}
              </SecondaryButton>
            )}
            {canRate(booking.service_status) && (
              <PrimaryButton disabled={busy} onClick={() => openRating(booking.id, "driver")}>
                {translate("rating.rateClient")}
              </PrimaryButton>
            )}
            {canOpenDispute(booking.service_status) && (
              <SecondaryButton onClick={() => openDisputeForm(booking.id, "driver")}>
                {translate("driverBooking.reportProblem")}
              </SecondaryButton>
            )}
            {renderBookingDisputes(booking.id)}
            {renderCancelControls(booking, "driver")}
            {booking.service_status === "cancelled" && (
              <div className="rounded-[14px] border border-border bg-card p-4">{renderCancelledNote(booking)}</div>
            )}
            {nextAction && (
              <PrimaryButton
                disabled={busy || (needsCode && proofCode.trim().length < 4)}
                onClick={() => void run(async () => {
                  await bookingAction(booking.id, nextAction[0], {
                    expected_version: booking.version,
                    code: needsCode ? proofCode.trim() : null,
                  });
                  await openDriverBooking(booking.id);
                  await loadDriverBookings();
                }, translate("driverBooking.statusUpdated"))}
              >
                {nextAction[1]}
              </PrimaryButton>
            )}
            {renderBookingSafety(booking, "driver")}
          </section>
        </main>
      );
    }

    if (screen === "driver-income") {
      // §9.1-9.3: only the commission account is real money here. `capture` is what ELCHI took, `reversal` what
      // it gave back; the fare never enters this ledger because ELCHI never handles it.
      const approvedTopups = walletLines
        .filter((line) => line.kind === "topup" && line.direction === "credit")
        .reduce((sum, line) => sum + line.amount_minor, 0);
      const reversedCommission = walletLines
        .filter((line) => line.kind === "reversal" && line.direction === "credit")
        .reduce((sum, line) => sum + line.amount_minor, 0);
      /**
       * The reference client charts a driver's *earnings*. Stage 2 cannot: the fare is cash between the
       * client and the driver and never touches ELCHI, so an earnings figure here would be invented money
       * (AGENTS.md section 9). What this platform genuinely recorded is the commission it captured, which is
       * what the chart shows - and it says so above the bars.
       */
      const buckets = new Map<string, number>();
      const now = new Date();
      const span = incomePeriod === "daily" ? 7 : 6;
      for (let back = span - 1; back >= 0; back -= 1) {
        const at = new Date(now);
        if (incomePeriod === "daily") at.setDate(at.getDate() - back);
        else at.setMonth(at.getMonth() - back);
        buckets.set(incomeBucketKey(at, incomePeriod), 0);
      }
      for (const line of walletLines) {
        if (line.kind !== "commission_capture" || line.direction !== "debit") continue;
        const key = incomeBucketKey(new Date(line.occurred_at), incomePeriod);
        if (buckets.has(key)) buckets.set(key, (buckets.get(key) ?? 0) + line.amount_minor);
      }
      const chart = [...buckets].map(([label, value]) => ({ label, value }));
      return (
        <main className="flex min-h-0 flex-1 flex-col bg-background">
          <TopBar title={translate("income.title")} back={() => go("driver-home")} />
          <section className="el-enter min-h-0 flex-1 space-y-4 overflow-y-auto px-5 pb-24 pt-5">
            <div className="rounded-[18px] border border-border bg-card p-4">
              <p className="text-[13px] font-semibold text-muted-foreground">{translate("income.available")}</p>
              <p className="mt-1 text-[30px] font-bold text-foreground">
                {walletState ? formatUzs(walletState.available_minor / 100) : "-"}
              </p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {translate("income.balanceNote")}
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-[12px] bg-slate-50 p-3">
                  <p className="text-[15px] font-bold text-foreground">
                    {walletState ? formatUzs(walletState.held_minor / 100) : "-"}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{translate("income.held")}</p>
                </div>
                <div className="rounded-[12px] bg-slate-50 p-3">
                  <p className="text-[15px] font-bold text-foreground">{formatUzs(reversedCommission / 100)}</p>
                  <p className="text-[11px] text-muted-foreground">{translate("income.reversed")}</p>
                </div>
                <div className="rounded-[12px] bg-slate-50 p-3">
                  <p className="text-[15px] font-bold text-foreground">{formatUzs(approvedTopups / 100)}</p>
                  <p className="text-[11px] text-muted-foreground">{translate("income.topups")}</p>
                </div>
                <div className="rounded-[12px] bg-slate-50 p-3">
                  <p className="text-[15px] font-bold text-foreground">
                    {walletState ? formatUzs(walletState.pending_topups_minor / 100) : "-"}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{translate("income.pendingTopups")}</p>
                </div>
              </div>
            </div>
            <div className="rounded-[18px] border border-border bg-card p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-[15px] font-semibold text-foreground">{translate("income.capturedTitle")}</p>
                <div className="flex gap-1 rounded-lg bg-secondary p-0.5">
                  {(["daily", "monthly"] as const).map((period) => (
                    <button
                      key={period}
                      type="button"
                      onClick={() => setIncomePeriod(period)}
                      className={cls(
                        "el-press rounded-md px-3 py-1 text-xs font-medium",
                        incomePeriod === period ? "bg-card text-foreground" : "text-muted-foreground",
                      )}
                    >
                      {period === "daily" ? translate("income.period.daily") : translate("income.period.monthly")}
                    </button>
                  ))}
                </div>
              </div>
              <BarChart data={chart} formatValue={(value) => formatUzs(value / 100)} empty={translate("income.chartEmpty")} />
              <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
                {translate("income.chartNote")}
              </p>
            </div>
            <div className="rounded-[18px] border border-border bg-card p-4">
              <p className="text-[15px] font-semibold text-foreground">{translate("income.topupTitle")}</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                {translate("income.topupNote")}
              </p>
              <div className="mt-3 space-y-3">
                <Field label={translate("income.amountLabel")} type="number" value={topupAmount} placeholder="100000" onChange={setTopupAmount} />
                <PrimaryButton
                  disabled={busy || soumToMinor(topupAmount) <= 0}
                  onClick={() => void run(async () => {
                    await createTopup({ amount_minor: soumToMinor(topupAmount), method: "bank_transfer" }, newIdempotencyKey());
                    setTopupAmount("");
                    await loadWallet();
                  }, translate("income.topupSent"))}
                >
                  {translate("income.topupSend")}
                </PrimaryButton>
              </div>
            </div>
            <div className="space-y-2">
              <p className="px-1 text-[13px] font-semibold text-muted-foreground">{translate("income.requestsTitle")}</p>
              {topups.length ? topups.map((topup) => (
                <div key={topup.id} className="flex items-center justify-between gap-3 rounded-[14px] border border-border bg-card p-4">
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-semibold text-foreground">{formatUzs(topup.amount_minor / 100)}</span>
                    <span className="mt-0.5 block text-[12px] text-muted-foreground">{shortDate(topup.created_at)}</span>
                  </span>
                  <StatusBadge status={topup.status} />
                </div>
              )) : (
                <EmptyState icon={Package} title={translate("income.requestsEmpty")} subtitle={translate("income.requestsEmptyHint")} />
              )}
            </div>
          </section>
          <BottomNav role="driver" active="driver-home" go={go} />
        </main>
      );
    }

    if (screen === "driver-profile") {
      const vehicleInfo = [driverProfile?.car_model, driverProfile?.car_color, driverProfile?.plate_number].filter(Boolean).join(" / ") || translate("driverProfile.noVehicle");
      const verificationLabel = driverVerificationLabels[driverProfile?.verification_status ?? "new"] ?? driverProfile?.verification_status ?? translate("driverProfile.statusNew");
      return (
        <main className="flex flex-1 flex-col bg-background">
          <TopBar title={translate("driverProfile.title")} back={() => go("driver-home")} />
          <section className="el-enter flex-1 space-y-4 overflow-y-auto px-5 pb-24 pt-5">
            <div className="rounded-[18px] border border-border bg-card p-4">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-accent text-primary">
                  <Truck size={28} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[18px] font-bold text-foreground">{driverProfile?.full_name ?? driverProfile?.user?.full_name ?? translate("dispute.side.driver")}</p>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">{driverProfile?.user?.phone ?? auth.user?.phone}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span className={cls(
                      "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                      driverProfile?.verification_status === "approved" ? "bg-success/10 text-success" : "bg-warning/14 text-warning",
                    )}>
                      {verificationLabel}
                    </span>
                    <span className={cls(
                      "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                      driverProfile?.is_available ? "bg-accent text-primary" : "bg-muted text-muted-foreground",
                    )}>
                      {driverProfile?.is_available ? translate("driverProfile.active") : translate("driverProfile.inactive")}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                [translate("driverProfile.rating"), driverProfile?.rating ? Number(driverProfile.rating).toFixed(1) : "-"],
                [translate("driverProfile.completed"), driverProfile?.completed_orders ?? 0],
                [translate("common.total"), driverProfile?.total_orders ?? 0],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded-[12px] border border-border bg-card p-3 text-center">
                  <p className="text-[20px] font-bold text-foreground">{value}</p>
                  <p className="text-[11px] text-muted-foreground">{label}</p>
                </div>
              ))}
            </div>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[15px] font-semibold text-foreground">{translate("driverProfile.availabilityTitle")}</p>
                  <p className="mt-1 text-[13px] text-muted-foreground">
                    {driverProfile?.verification_status === "approved" ? (driverProfile?.is_available ? translate("driverProfile.availabilityOn") : translate("driverProfile.availabilityOff")) : translate("driverProfile.availabilityNeedsApproval")}
                  </p>
                </div>
                <button
                  disabled={driverProfile?.verification_status !== "approved" || busy}
                  onClick={() => run(async () => { await setDriverAvailability(!driverProfile?.is_available); await loadDriverProfile(); }, translate("driverProfile.availabilityUpdated"))}
                  className={cls("el-press h-8 w-14 rounded-full p-1", driverProfile?.is_available ? "bg-primary" : "bg-slate-300", driverProfile?.verification_status !== "approved" && "opacity-60")}
                >
                  <span className={cls("block h-6 w-6 rounded-full bg-card transition", driverProfile?.is_available && "translate-x-6")} />
                </button>
              </div>
            </div>
            <div className="rounded-[16px] border border-border bg-card p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-secondary-foreground">
                  <Truck size={19} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-muted-foreground">{translate("driverProfile.vehicle")}</p>
                  <p className="mt-1 break-words text-[15px] font-semibold text-foreground">{vehicleInfo}</p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {[
                  [translate("driverProfile.status"), verificationLabel],
                  [translate("driverProfile.routes"), trips.length],
                  [translate("dispute.detailTitle"), driverProfile?.dispute_count ?? 0],
                ].map(([label, value]) => (
                  <div key={label as string} className="rounded-[12px] bg-slate-50 p-2.5 text-center">
                    <p className="break-words text-[13px] font-bold text-foreground">{value}</p>
                    <p className="text-[11px] text-muted-foreground">{label}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <p className="px-1 text-[13px] font-semibold text-muted-foreground">{translate("driverProfile.quickActions")}</p>
              <ProfileActionRow icon={User} label={translate("driverProfile.action.edit")} description={translate("driverProfile.action.editHint")} onClick={() => go("driver-profile-form")} />
              <ProfileActionRow icon={FileText} label={translate("driverProfile.action.documents")} description={translate("driverProfile.action.documentsHint")} onClick={() => go("driver-documents")} />
              <ProfileActionRow icon={Navigation} label={translate("driverProfile.action.routes")} description={translate("driverProfile.action.routesHint")} onClick={() => go("driver-routes")} />
              <ProfileActionRow icon={Package} label={translate("driverProfile.action.proposals")} description={translate("driverProfile.action.proposalsHint")} onClick={() => go("driver-proposals")} />
              <ProfileActionRow icon={Tag} label={translate("driverProfile.action.bonus")} description={translate("driverProfile.action.bonusHint")} onClick={() => go("driver-bonus")} />
              <ProfileActionRow icon={Package} label={translate("driverProfile.action.orders")} description={translate("driverProfile.action.ordersHint")} onClick={() => go("driver-orders")} />
              <ProfileActionRow icon={FileText} label={translate("driverProfile.action.disputes")} description={translate("driverProfile.action.disputesHint")} onClick={() => go("my-disputes")} />
              <ProfileActionRow icon={Shield} label={translate("safety.centerTitle")} description={translate("safety.centerDescription")} onClick={() => go("safety-center")} />
              <ProfileActionRow icon={Headphones} label={translate("driverProfile.action.support")} description={translate("driverProfile.action.supportHint")} onClick={() => go("support")} />
              <ProfileActionRow icon={Shield} label={translate("driverProfile.action.settings")} description={translate("driverProfile.action.settingsHint")} onClick={() => go("settings")} />
              <ProfileActionRow icon={Home} label={translate("driverProfile.action.home")} description={translate("driverProfile.action.homeHint")} onClick={() => go("driver-home")} />
              <ProfileActionRow danger icon={X} label={translate("driverProfile.action.logout")} description={translate("driverProfile.action.logoutHint")} onClick={() => run(async () => { await auth.logout(); go("role"); })} />
            </div>
          </section>
          <BottomNav role="driver" active={screen} go={go} />
        </main>
      );
    }

    return <EmptyState icon={Package} title={translate("driverProfile.notFound")} action={translate("common.back")} onAction={() => go(auth.user?.role === "driver" ? "driver-home" : "client-home")} />;
  })();

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--shell-canvas)] p-4 font-[Inter]">
      <div className="relative flex h-[844px] w-[390px] max-w-full flex-col overflow-hidden rounded-[36px] border-[7px] border-[var(--shell-bezel)] bg-background shadow-2xl">
        <div className="flex h-11 shrink-0 items-center justify-between bg-card px-6 text-[13px] font-semibold text-foreground">
          <span>9:41</span>
          <span>LTE 100%</span>
        </div>
        {(message || error || busy) && (
          <div className={cls("px-5 py-2 text-[13px] font-medium", error ? "bg-destructive/10 text-destructive" : "bg-success/12 text-success")}>
            {busy ? translate("common.loading") : error || message}
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col">{content}</div>
        {/* One drawer for the whole client side, mounted over the shell rather than inside each screen, so
            it keeps its open state while `content` swaps underneath it. */}
        {auth.isAuthenticated && selectedRole === "client" && (
          <AppSidebar
            open={sidebarOpen}
            active={screen}
            items={clientSidebarItems(unreadNotifications)}
            subtitle={auth.user?.full_name || auth.user?.phone || undefined}
            onSelect={(id) => {
              setSidebarOpen(false);
              go(id as Screen);
            }}
            onClose={() => setSidebarOpen(false)}
            onLogout={() => {
              setSidebarOpen(false);
              void run(async () => {
                await auth.logout();
                go("role");
              });
            }}
          />
        )}
        {mapPicker && (mapPicker === "pickup" ? fromCity : toCity) && (
          <MapAddressPicker
            mode={mapPicker}
            city={(mapPicker === "pickup" ? fromCity : toCity)!}
            district={mapPicker === "pickup" ? fromDistrict : toDistrict}
            initialLat={mapPicker === "pickup" ? Number(orderForm.pickup_lat) || null : Number(orderForm.dropoff_lat) || null}
            initialLng={mapPicker === "pickup" ? Number(orderForm.pickup_lng) || null : Number(orderForm.dropoff_lng) || null}
            initialAddress={mapPicker === "pickup" ? orderForm.pickup_address : orderForm.dropoff_address}
            onBack={() => setMapPicker(null)}
            onConfirm={(location) => {
              const isPickup = mapPicker === "pickup";
              const willHavePickup = isPickup ? Boolean(location.address) : Boolean(orderForm.pickup_address);
              const willHaveDropoff = isPickup ? Boolean(orderForm.dropoff_address) : Boolean(location.address);
              const willHaveCities = Boolean(orderForm.from_city_id && orderForm.to_city_id);
              if (mapPicker === "pickup") {
                setOrderForm((current) => ({
                  ...current,
                  from_district_id: fromDistrict?.id ?? null,
                  pickup_lat: location.lat,
                  pickup_lng: location.lng,
                  pickup_address: location.address || current.pickup_address,
                }));
              } else {
                setOrderForm((current) => ({
                  ...current,
                  to_district_id: toDistrict?.id ?? null,
                  dropoff_lat: location.lat,
                  dropoff_lng: location.lng,
                  dropoff_address: location.address || current.dropoff_address,
                }));
              }
              setMapPicker(null);
              go(willHavePickup && willHaveDropoff && willHaveCities ? "client-route-summary" : "client-home");
            }}
          />
        )}
        {readOnlyMap && (
          <div className="absolute inset-0 z-50 flex flex-col bg-card">
            <TopBar title={translate("mapSheet.title")} back={() => setReadOnlyMap(null)} />
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <ReadOnlyOrderMap
                pickupLat={readOnlyMap.pickupLat}
                pickupLng={readOnlyMap.pickupLng}
                dropoffLat={readOnlyMap.dropoffLat}
                dropoffLng={readOnlyMap.dropoffLng}
              />
              {hasLocation(readOnlyMap.pickupLat, readOnlyMap.pickupLng) && (
                <a
                  href={createMapsSearchUrl(Number(readOnlyMap.pickupLat), Number(readOnlyMap.pickupLng))}
                  target="_blank"
                  rel="noreferrer"
                  className="flex h-[48px] items-center justify-center rounded-[12px] bg-accent text-[14px] font-semibold text-primary"
                >
                  {translate("mapSheet.openPickup")}
                </a>
              )}
              {hasLocation(readOnlyMap.destinationLat, readOnlyMap.destinationLng) && (
                <a
                  href={createMapsDirectionsUrl(Number(readOnlyMap.destinationLat), Number(readOnlyMap.destinationLng))}
                  target="_blank"
                  rel="noreferrer"
                  className="flex h-[48px] items-center justify-center rounded-[12px] bg-primary text-[14px] font-semibold text-primary-foreground"
                >
                  {translate("mapSheet.open")}
                </a>
              )}
            </div>
          </div>
        )}
        {intentEditPending && (
          <ConfirmSheet
            title={translate("confirmDialog.intentEdit.title")}
            text={offersAffectedText(intentEditPending.openOffers)}
            confirmText={translate("common.save")}
            cancelText={translate("confirmDialog.back")}
            onCancel={() => setIntentEditPending(null)}
            onConfirm={() => {
              const pending = intentEditPending;
              setIntentEditPending(null);
              void run(async () => {
                const saved = await sendIntentEdit({ ...pending.body, acknowledge_open_offers: true }, pending.then);
                if (saved) go(pending.then);
              }, translate("confirmDialog.intentEdit.saved"));
            }}
          />
        )}
        {confirmAction && (
          <ConfirmSheet
            title={
              confirmAction.type === "select-driver"
                ? translate("confirmDialog.selectDriver.title")
                : confirmAction.type === "confirm-delivery"
                  ? translate("confirmDialog.confirmDelivery.title")
                  : translate("confirmDialog.cancelOrder.title")
            }
            text={
              confirmAction.type === "select-driver"
                ? translate("confirmDialog.selectDriver.text")
                : confirmAction.type === "confirm-delivery"
                  ? translate("confirmDialog.confirmDelivery.text")
                  : orderDetail?.status === "accepted"
                    ? translate("confirmDialog.cancelOrder.acceptedText")
                    : translate("confirmDialog.cancelOrder.text")
            }
            confirmText={confirmAction.type === "select-driver" ? translate("confirmDialog.selectDriver.confirm") : confirmAction.type === "confirm-delivery" ? translate("common.confirm") : translate("common.cancel")}
            cancelText={confirmAction.type === "cancel-order" ? translate("confirmDialog.back") : translate("common.cancel")}
            danger={confirmAction.type === "cancel-order"}
            onCancel={() => setConfirmAction(null)}
            onConfirm={() => run(async () => runConfirmAction(confirmAction), confirmAction.type === "cancel-order" ? translate("confirmDialog.cancelOrder.done") : undefined)}
          />
        )}
        <div className="flex h-[34px] shrink-0 items-center justify-center bg-card">
          <div className="h-1.5 w-32 rounded-full bg-slate-300" />
        </div>
      </div>
    </div>
  );
}
