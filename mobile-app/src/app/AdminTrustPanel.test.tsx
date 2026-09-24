/**
 * Staff trust & operations panel: states, capability gating and that every command goes out only after an
 * explicit confirmation, through the right wrapper, with an idempotency key.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../types/api";

vi.mock("../api/v2/admin-trust.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/v2/admin-trust.api")>();
  return {
    ...actual,
    listAdminBookings: vi.fn(),
    adminBookingCommand: vi.fn(),
    adminBookingMessages: vi.fn(),
    adminProposalMessages: vi.fn(),
    hideChatMessage: vi.fn(),
    listReports: vi.fn(),
    reviewReport: vi.fn(),
    listFraudSignals: vi.fn(),
    reviewFraudSignal: vi.fn(),
    userStrikes: vi.fn(),
    adminTripTracking: vi.fn(),
    createListingOnBehalf: vi.fn(),
    listSupportTicketsAdmin: vi.fn(),
  };
});

vi.mock("../api/v2/ops.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/v2/ops.api")>();
  return {
    ...actual,
    capabilities: vi.fn(),
    listTrustReviews: vi.fn(),
    ticketCommand: vi.fn(),
    trustReviewCommand: vi.fn(),
  };
});

import * as trust from "../api/v2/admin-trust.api";
import * as ops from "../api/v2/ops.api";
import { AdminSupportPanel } from "./AdminOpsPanel";
import { AdminTrustPanel, applicableCommands, onBehalfBody, tashkentIso } from "./AdminTrustPanel";

const m = <T,>(fn: T) => fn as unknown as ReturnType<typeof vi.fn>;

const OPERATOR = ["ops.view", "ops.booking_command", "ops.dispute_resolve", "ops.trust_review"];
const ADMIN = [...OPERATOR, "ops.booking_cancel", "ops.dispute_decide"];

function caps(list: string[]) {
  m(ops.capabilities).mockResolvedValue({ roles: [], capabilities: list, driver_eligibility: null });
}

const booking = {
  id: "bkg_1",
  viewer_side: "operator",
  service_type: "passenger",
  service_status: "awaiting_pickup",
  cash_status: "not_due",
  commission_status: "held",
  version: 4,
  trip_id: "trp_1",
  listing_ids: [],
  accepted_proposal_version_id: "pv_1",
  quantity: 1,
  price_basis: "per_seat",
  unit_price_minor: 10_000_000,
  total_minor: 10_000_000,
  currency: "UZS",
  payment_method: "cash",
  pickup: { occurrence_seq: 0, stop: { id: "stp_1", name_uz: "Toshkent", name_ru: "Ташкент" } },
  dropoff: { occurrence_seq: 1, stop: { id: "stp_2", name_uz: "Samarqand", name_ru: "Самарканд" } },
  contact: { phones_visible: false },
  policy_versions: {},
  cancellation_policy_summary: "",
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-20T08:00:00Z",
  fee: { commission_minor: 0, fee_bps: 0, net_minor: 0, policy_id: "p", policy_kind: "standard" },
  client: { id: "usr_c", display_name: "Mijoz A", contact_phone: null },
  no_show_review: { status: "pending", reported_at: "2026-09-20T09:00:00Z", decided_at: null },
};

async function openBooking() {
  await screen.findByText("bkg_1");
  fireEvent.click(screen.getByRole("button", { name: "Ochish" }));
}

function options(label: string): string[] {
  return within(screen.getByLabelText(label)).getAllByRole("option").map((option) => option.textContent ?? "");
}

beforeEach(() => {
  vi.clearAllMocks();
  m(trust.listAdminBookings).mockResolvedValue([booking]);
  m(trust.adminBookingCommand).mockResolvedValue({ data: booking, warnings: [], meta: null });
  m(trust.listReports).mockResolvedValue([]);
  m(trust.listFraudSignals).mockResolvedValue([]);
  m(trust.adminBookingMessages).mockResolvedValue([]);
  m(trust.adminProposalMessages).mockResolvedValue([]);
});

describe("bookings (B12/B13)", () => {
  it("shows the empty and the error state", async () => {
    caps(OPERATOR);
    m(trust.listAdminBookings).mockResolvedValueOnce([]);
    render(<AdminTrustPanel />);
    expect(await screen.findByText("Bu navbatda bron yo'q")).toBeInTheDocument();

    m(trust.listAdminBookings).mockRejectedValueOnce(new ApiError(403, { code: "FORBIDDEN", message: "Ruxsat yo'q" }));
    fireEvent.change(screen.getByLabelText("Navbat"), { target: { value: "finance_review" } });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("hides cancel and fee finalisation from an operator (Q10, Q17) and confirms before sending", async () => {
    caps(OPERATOR);
    render(<AdminTrustPanel />);
    await openBooking();
    const commands = options("Buyruq");
    expect(commands).toContain("Kelmaganini tasdiqlash");
    expect(commands).not.toContain("Bronni bekor qilish");
    expect(commands).not.toContain("Komissiyani yakunlash");
    expect(screen.getByText(/faqat admin va undan yuqori/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Sabab"), { target: { value: "Mijoz kelmadi, qo'ng'iroq qilindi" } });
    fireEvent.click(screen.getByRole("button", { name: "Kelmaganini tasdiqlash" }));
    expect(trust.adminBookingCommand).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));

    await waitFor(() => expect(trust.adminBookingCommand).toHaveBeenCalledTimes(1));
    const [id, command, body, key] = m(trust.adminBookingCommand).mock.calls[0];
    expect(id).toBe("bkg_1");
    expect(command).toBe("confirm_no_show");
    expect(body).toMatchObject({ expected_version: 4, reason: "Mijoz kelmadi, qo'ng'iroq qilindi", cancel_fault_side: null });
    expect(typeof key).toBe("string");
    expect(key.length).toBeGreaterThan(8);
  });

  it("lets admin+ cancel with an explicit cause or leave it undetermined (Q129)", async () => {
    caps(ADMIN);
    render(<AdminTrustPanel />);
    await openBooking();
    fireEvent.change(screen.getByLabelText("Buyruq"), { target: { value: "cancel" } });
    expect(options("Bekor qilish sababi kimda")[0]).toMatch(/Aniqlanmagan/);
    fireEvent.change(screen.getByLabelText("Bekor qilish sababi kimda"), { target: { value: "driver" } });
    fireEvent.change(screen.getByLabelText("Sabab"), { target: { value: "Haydovchi safarni bekor qildi" } });
    fireEvent.click(screen.getByRole("button", { name: "Bronni bekor qilish" }));
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() => expect(trust.adminBookingCommand).toHaveBeenCalled());
    expect(m(trust.adminBookingCommand).mock.calls[0][1]).toBe("cancel");
    expect(m(trust.adminBookingCommand).mock.calls[0][2]).toMatchObject({ cancel_fault_side: "driver" });
  });

  it("shows the server's refusal and retries with the same idempotency key", async () => {
    caps(OPERATOR);
    m(trust.adminBookingCommand).mockRejectedValueOnce(
      new ApiError(409, { code: "VERSION_CONFLICT", message: "Versiya eskirgan" }),
    );
    render(<AdminTrustPanel />);
    await openBooking();
    fireEvent.change(screen.getByLabelText("Sabab"), { target: { value: "sabab" } });
    fireEvent.click(screen.getByRole("button", { name: "Kelmaganini tasdiqlash" }));
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Qayta urinish" }));
    await waitFor(() => expect(trust.adminBookingCommand).toHaveBeenCalledTimes(2));
    const calls = m(trust.adminBookingCommand).mock.calls;
    expect(calls[1][3]).toBe(calls[0][3]);
  });

  it("offers only commands that fit the booking", () => {
    const parcel = { ...booking, service_type: "parcel", no_show_review: null, commission_status: "hold_pending" };
    const commands = applicableCommands(parcel as never);
    expect(commands).toContain("require_return");
    expect(commands).not.toContain("drop_off");
    expect(commands).not.toContain("confirm_no_show");
    expect(commands).not.toContain("finalize_fee");
  });
});

describe("reports and fraud signals", () => {
  it("records a report decision after confirmation", async () => {
    caps(OPERATOR);
    m(trust.listReports).mockResolvedValue([
      { id: "rpt_1", subject_type: "user", subject_id: "usr_9", reason_code: "harassment", status: "open", created_at: "2026-09-20T08:00:00Z", version: 2 },
    ]);
    m(trust.reviewReport).mockResolvedValue({});
    render(<AdminTrustPanel initialTab="reports" />);
    await screen.findByText("rpt_1");
    fireEvent.change(screen.getByLabelText("Izoh"), { target: { value: "dalil yetarli emas" } });
    fireEvent.click(screen.getByRole("button", { name: "Rad etish" }));
    expect(trust.reviewReport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() => expect(trust.reviewReport).toHaveBeenCalled());
    const [id, body, key] = m(trust.reviewReport).mock.calls[0];
    expect(id).toBe("rpt_1");
    expect(body).toEqual({ expected_version: 2, status: "dismissed", note: "dalil yetarli emas" });
    expect(typeof key).toBe("string");
  });

  it("confirms a fraud signal and hides actions without ops.trust_review", async () => {
    caps(OPERATOR);
    const signal = {
      id: "frd_1", signal_type: "shared_device_accounts", subject_user_id: "usr_5", status: "under_review",
      evidence: { accounts: 3 }, detected_at: "2026-09-20T08:00:00Z", version: 1,
    };
    m(trust.listFraudSignals).mockResolvedValue([signal]);
    m(trust.reviewFraudSignal).mockResolvedValue(signal);
    const { unmount } = render(<AdminTrustPanel initialTab="fraud" />);
    await screen.findByText("frd_1");
    expect(screen.queryByRole("button", { name: "Ko'rikka olish" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Tasdiqlash" }));
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() => expect(trust.reviewFraudSignal).toHaveBeenCalled());
    expect(m(trust.reviewFraudSignal).mock.calls[0][1]).toEqual({ expected_version: 1, status: "confirmed", note: null });
    expect(typeof m(trust.reviewFraudSignal).mock.calls[0][2]).toBe("string");
    unmount();

    caps(["ops.view"]);
    render(<AdminTrustPanel initialTab="fraud" />);
    await screen.findByText("frd_1");
    expect(screen.queryByRole("button", { name: "Tasdiqlash" })).toBeNull();
  });
});

describe("chat, strikes, tracking", () => {
  const message = {
    id: "msg_1", author_side: "client", author_user_id: "usr_c", contact_filter_categories: { phone: 1 },
    moderation_status: "visible", created_at: "2026-09-20T08:00:00Z", text: "*** ***",
  };

  it("hides a booking chat message with a reason; the proposal thread is read-only (Q100)", async () => {
    caps(OPERATOR);
    m(trust.adminBookingMessages).mockResolvedValue([message]);
    m(trust.adminProposalMessages).mockResolvedValue([message]);
    m(trust.hideChatMessage).mockResolvedValue({ ...message, moderation_status: "hidden_by_staff" });
    render(<AdminTrustPanel initialTab="chat" />);
    fireEvent.change(await screen.findByLabelText("Yozishma ID"), { target: { value: "bkg_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Ochish" }));
    await screen.findByText("*** ***");
    const hide = screen.getByRole("button", { name: "Yashirish" });
    expect(hide).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Yashirish sababi/), { target: { value: "telefon raqami" } });
    fireEvent.click(hide);
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() => expect(trust.hideChatMessage).toHaveBeenCalled());
    expect(m(trust.hideChatMessage).mock.calls[0].slice(0, 2)).toEqual(["msg_1", { reason: "telefon raqami" }]);
    expect(typeof m(trust.hideChatMessage).mock.calls[0][2]).toBe("string");

    fireEvent.change(screen.getByLabelText("Yozishma turi"), { target: { value: "proposal" } });
    fireEvent.change(screen.getByLabelText("Yozishma ID"), { target: { value: "pth_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Ochish" }));
    await waitFor(() => expect(trust.adminProposalMessages).toHaveBeenCalledWith("pth_1", { limit: 50 }));
    await screen.findByText("*** ***");
    expect(screen.queryByRole("button", { name: "Yashirish" })).toBeNull();
  });

  it("loads strikes for a user", async () => {
    caps(OPERATOR);
    m(trust.userStrikes).mockResolvedValue({
      user_id: "usr_5", window_days: 30, strikes_in_window: 2,
      strikes: [{ subject_type: "chat_message", categories: ["phone"], reason_code: "contact_filter", occurred_at: "2026-09-19T08:00:00Z" }],
    });
    render(<AdminTrustPanel initialTab="strikes" />);
    fireEvent.change(await screen.findByLabelText("Foydalanuvchi ID"), { target: { value: "usr_5" } });
    fireEvent.click(screen.getByRole("button", { name: "Ko'rish" }));
    expect(await screen.findByText(/contact_filter/)).toBeInTheDocument();
    expect(trust.userStrikes).toHaveBeenCalledWith("usr_5");
  });

  it("shows the last point's freshness and the audit note, never a 'GPS active' claim (Q86)", async () => {
    caps(OPERATOR);
    m(trust.adminTripTracking).mockResolvedValue({
      trip_id: "trp_1", active_session: false, freshness: "lost", session_started_at: null,
      last_point: { lat: 41.3, lng: 69.2, accuracy_m: 25, low_accuracy: false, captured_at: "2026-09-20T08:00:00Z", received_at: "2026-09-20T08:00:02Z" },
    });
    const { container } = render(<AdminTrustPanel initialTab="tracking" />);
    fireEvent.change(await screen.findByLabelText("Safar ID"), { target: { value: "trp_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Ko'rish" }));
    expect(await screen.findByText(/Aloqa uzilgan/)).toBeInTheDocument();
    expect(container.textContent).toMatch(/audit jurnaliga/);
    expect(container.textContent).not.toMatch(/GPS faol/i);
  });
});

describe("listing on behalf (O7)", () => {
  it("requires the owner and a consent reference, then sends them with a key", async () => {
    caps(OPERATOR);
    m(trust.createListingOnBehalf).mockResolvedValue({ data: { id: "lst_1", status: "draft" }, warnings: [], meta: null });
    render(<AdminTrustPanel initialTab="on_behalf" />);
    const create = await screen.findByRole("button", { name: "E'lon yaratish" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Egasi"), { target: { value: "usr_c" } });
    fireEvent.change(screen.getByLabelText("Jo'nash bekati"), { target: { value: "stp_1" } });
    fireEvent.change(screen.getByLabelText("Borish bekati"), { target: { value: "stp_2" } });
    fireEvent.change(screen.getByLabelText("Oyna boshi"), { target: { value: "2026-09-25T08:00" } });
    fireEvent.change(screen.getByLabelText("Oyna oxiri"), { target: { value: "2026-09-25T10:00" } });
    fireEvent.change(screen.getByLabelText("Narx"), { target: { value: "100000" } });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Rozilik dalili"), { target: { value: "murojaat #42" } });
    expect(create).toBeEnabled();
    fireEvent.click(create);
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() => expect(trust.createListingOnBehalf).toHaveBeenCalled());
    const [body, key] = m(trust.createListingOnBehalf).mock.calls[0];
    expect(body).toMatchObject({
      owner_user_id: "usr_c", consent_reference: "murojaat #42", unit_price_minor: 10_000_000,
      departure_window_start: "2026-09-25T08:00:00+05:00",
    });
    expect(typeof key).toBe("string");
    expect(await screen.findByText(/lst_1/)).toBeInTheDocument();
  });

  it("is not offered without ops.booking_command", async () => {
    caps(["ops.view"]);
    render(<AdminTrustPanel initialTab="on_behalf" />);
    expect(await screen.findByText(/rolingizda yo'q/)).toBeInTheDocument();
  });

  it("builds no body without consent and reads times as Tashkent", () => {
    expect(tashkentIso("2026-09-25T08:00")).toBe("2026-09-25T08:00:00+05:00");
    expect(tashkentIso("")).toBeNull();
    expect(
      onBehalfBody({
        owner: "usr_c", consent: "", kind: "request", service: "passenger", tripId: "", originStop: "a",
        destinationStop: "b", start: "2026-09-25T08:00", end: "2026-09-25T09:00", basis: "per_seat", price: "1000",
        seats: "1", parcelType: "box", weightKg: "", comment: "",
      }),
    ).toBeNull();
  });
});

describe("AdminSupportPanel actions (S17, S19)", () => {
  const ticket = {
    id: "tkt_1", kind: "sos", status: "open", version: 3, created_at: "2026-09-20T08:00:00Z", user_id: "usr_c",
    message: "Yordam", press_count: 2,
  };
  const review = {
    id: "trv_1", subject_user_id: "usr_5", signal_type: "contact_filter_strikes", status: "open", evidence: { strikes: 3 },
    signal_count: 3, last_signal_at: "2026-09-20T08:00:00Z", version: 1, created_at: "2026-09-20T08:00:00Z",
  };

  beforeEach(() => {
    m(trust.listSupportTicketsAdmin).mockResolvedValue([ticket]);
    m(ops.listTrustReviews).mockResolvedValue([review]);
    m(ops.ticketCommand).mockResolvedValue(ticket);
    m(ops.trustReviewCommand).mockResolvedValue(review);
  });

  it("acknowledges a ticket and acts on a trust review after confirmation", async () => {
    caps(OPERATOR);
    render(<AdminSupportPanel />);
    await screen.findByText("tkt_1");
    await screen.findByText("trv_1");
    const [ticketOpen, reviewOpen] = screen.getAllByRole("button", { name: "Ko'rish" });

    fireEvent.click(ticketOpen);
    expect(screen.getByRole("button", { name: "Hal qilish" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Qabul qilish" }));
    expect(ops.ticketCommand).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() =>
      expect(ops.ticketCommand).toHaveBeenCalledWith("tkt_1", "acknowledge", { expected_version: 3, note: null }),
    );

    fireEvent.click(reviewOpen);
    fireEvent.change(screen.getByLabelText("Ko'rik izohi"), { target: { value: "raqam yuborgan" } });
    fireEvent.click(screen.getByRole("button", { name: "Chora ko'rish" }));
    fireEvent.click(screen.getByRole("button", { name: "Ha, bajarish" }));
    await waitFor(() =>
      expect(ops.trustReviewCommand).toHaveBeenCalledWith("trv_1", "action", {
        expected_version: 1, note: "raqam yuborgan", decision: "warning_issued",
      }),
    );
  });

  it("is read-only without ops.trust_review", async () => {
    caps(["ops.view"]);
    render(<AdminSupportPanel />);
    await screen.findByText("tkt_1");
    fireEvent.click(screen.getAllByRole("button", { name: "Ko'rish" })[0]);
    expect(screen.queryByRole("button", { name: "Qabul qilish" })).toBeNull();
    expect(screen.getByText(/rolingizda yo'q/)).toBeInTheDocument();
  });
});
