import SwiftUI

// MARK: - BOSQICH 08 v3 ("Elchi Haydovchi Bron"): the driver's booking detail pieces

/// The 150 pt map hero (tap -> "Kuzatuv (siz yuborayotgan)"): both ends when the booking has map points, else the
/// route sketch; the pill says "Jonli" (green) only while the service runs and this phone sends the location,
/// "GPS o'chiq" (amber) while it runs without sending, otherwise "Kuzatuv" (grey). Never a server claim (§9/Q148).
struct DriverMapHero: View {
    let markers: [MapMarker]
    let chip: DriverBookingLayout.Chip
    let label: String
    let accessibility: String
    let action: () -> Void
    @Environment(\.elchi) private var c

    var body: some View {
        Button(action: action) {
            ZStack(alignment: .bottomTrailing) {
                Group {
                    if markers.count == 2 {
                        ElchiMap(markers: markers, zoom: 9, interactive: false, placeholder: label)
                    } else {
                        RouteSketch()
                    }
                }
                .allowsHitTesting(false)
                HStack(spacing: 6) {
                    Circle().fill(dot).frame(width: 8, height: 8)
                    Text(label).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(chip == .gpsOff ? c.tone(.warn).fg : c.text)
                }
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(chip == .gpsOff ? c.tone(.warn).bg : c.card, in: Capsule())
                .shadow(color: c.shadow, radius: 7, y: 4)
                .padding(.trailing, 12).padding(.bottom, 46)
            }
            .frame(height: 150)
            .frame(maxWidth: .infinity)
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .contentShape(RoundedRectangle(cornerRadius: 24))
        }
        .buttonStyle(PressFade())
        .padding(.horizontal, -4)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(accessibility), \(label)")
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("elchi.driver.booking.hero")
    }

    private var dot: Color {
        switch chip {
        case .live: Color(hex: 0x1E8E4E)
        case .gpsOff: Color(hex: 0xE0A100)
        case .tracking: Color(hex: 0x9AA6B5)
        }
    }
}

/// The five dots: reached ones azure with a tick, the current one ringed; a stopped booking (cancelled, no-show, or a
/// no-show report under review) carries a red cross on its pickup step.
struct DriverLadderDots: View {
    let ladder: DriverBookingLayout.Ladder
    let label: String
    @Environment(\.elchi) private var c

    var body: some View {
        let count = DriverBookingLayout.Ladder.count
        HStack(spacing: 0) {
            ForEach(0..<count, id: \.self) { index in
                dot(index)
                if index < count - 1 {
                    Line().stroke(reached(index + 1) ? c.brand : c.outline, style: StrokeStyle(lineWidth: 3, lineCap: .round, dash: [0.1, 6]))
                        .frame(height: 3).padding(.horizontal, 4)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityIdentifier("elchi.driver.booking.ladder")
    }

    private func reached(_ index: Int) -> Bool { ladder.current.map { index <= $0 } ?? false }

    private func dot(_ index: Int) -> some View {
        let cross = ladder.cross == index
        let done = reached(index) && !cross
        let fill = done ? c.brand : cross ? c.tone(.err).bg : c.field
        let tint = done ? c.onBrand : cross ? c.tone(.err).fg : Color(hex: 0x9AA6B5)
        return (cross ? ElchiIcon.x : ElchiIcon.check).image(size: 13).foregroundStyle(tint)
            .frame(width: 26, height: 26)
            .background(fill, in: Circle())
            .overlay {
                if ladder.current == index && ladder.cross == nil {
                    Circle().strokeBorder(c.isDark ? c.soft : Color(hex: 0xBFE3FF), lineWidth: 3)
                }
            }
    }

    private struct Line: Shape {
        func path(in rect: CGRect) -> Path {
            var path = Path()
            path.move(to: CGPoint(x: 0, y: rect.midY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            return path
        }
    }
}

/// The sheet card over the hero (design-04 layout, driver side): "Holat" + the long badge, the five dots, "Olib
/// ketish, 27 sen" / "Taxminan, 27 sen" (only from `planned_arrival_at`, never an ETA) with the two places, the
/// two-column facts (Pochta with the photo column), and the driver-only lines under the grid: the cash to collect
/// and the commission (Q103). No "Bron ID": there is no public booking code (BLOCKED).
struct DriverBookingSheet: View {
    let booking: DriverBookingDTO
    let photoURL: URL?
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    private var base: ClientBookingDTO { booking.base }

    var body: some View {
        let status = strings.status(DriverBookingBadge.of(base, short: false))
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .center, spacing: 12) {
                Text(strings.t("support.statusLabel")).font(ElchiFont.caption).foregroundStyle(c.muted)
                Spacer(minLength: 8)
                Text(status.text).font(ElchiFont.poppins(12.5, .semibold)).foregroundStyle(c.tone(status.tone).fg)
                    .multilineTextAlignment(.trailing)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(c.tone(status.tone).bg, in: RoundedRectangle(cornerRadius: 16))
            }
            .padding(.top, 4)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("elchi.driver.booking.status")
            if let ladder = DriverBookingLayout.ladder(base) {
                DriverLadderDots(ladder: ladder, label: ladderLabel(ladder, statusText: status.text))
            }
            ends
            Rectangle().fill(c.field).frame(height: 1)
            facts
            Rectangle().fill(c.field).frame(height: 1)
            money
        }
        .padding(.horizontal, 18).padding(.vertical, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { RoundedRectangle(cornerRadius: 28).fill(c.card).shadow(color: c.shadow, radius: 12, y: 6) }
        .overlay(alignment: .top) { Capsule().fill(c.outline).frame(width: 44, height: 5).padding(.top, 8).accessibilityHidden(true) }
        .padding(.top, -34)
        .accessibilityIdentifier("elchi.driver.booking.card")
    }

    private func ladderLabel(_ ladder: DriverBookingLayout.Ladder, statusText: String) -> String {
        guard ladder.cross == nil, let current = ladder.current else { return statusText }
        let keys = base.serviceType == .passenger ? PassengerStatus.ladder : StatusLadder.keys
        return keys.indices.contains(current) ? strings.t(keys[current]) : statusText
    }

    private var ends: some View {
        let pickup = ServerTime.parse(base.pickup.windowStart)
        let planned = ServerTime.parse(base.dropoff.plannedArrivalAt)
        return HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(pickup.map { strings.t("driver.v3bkg.pickupOn", ("date", strings.dayMonth($0))) } ?? strings.t("ui.from"))
                    .font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(PlaceShort.of(strings.endAddress(base.pickup.point))).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
            }
            .accessibilityElement(children: .combine)
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 4) {
                Text(planned.map { strings.t("client.booking.plannedArrival", ("date", strings.dayMonth($0))) } ?? strings.t("ui.to"))
                    .font(ElchiFont.caption).foregroundStyle(c.muted)
                Text(PlaceShort.of(strings.endAddress(base.dropoff.point))).font(ElchiFont.poppins(15, .medium)).foregroundStyle(c.text)
            }
            .multilineTextAlignment(.trailing)
            .accessibilityElement(children: .combine)
        }
    }

    /// Taksi: from, to, the passenger (the client's first name), final price (n × unit under it), seats, pickup
    /// window. Pochta: from, to, receiver (the phone only after departure, Q142; never the sender's, Q44), final price,
    /// quantity and size, weight - with the photo column.
    private var facts: some View {
        let parcel = base.serviceType == .parcel
        let perSeat = !parcel && PassengerMoney.perSeat(base.priceBasis)
        let price = (strings.t("client.booking.finalPrice"), strings.money(base.totalMinor),
                     perSeat ? strings.seatsTotal(base.quantity, unitMinor: base.unitPriceMinor) : nil)
        var items: [(String, String, String?)] = [
            (strings.t("ui.from"), strings.endAddress(base.pickup.point), nil),
            (strings.t("ui.to"), strings.endAddress(base.dropoff.point), nil),
        ]
        if parcel {
            if let receiver = ReceiverReveal.of(booking) {
                items.append((strings.t("driverBooking.receiver"), receiver.name ?? UzPhone.display(receiver.phone),
                              receiver.name == nil ? nil : UzPhone.display(receiver.phone)))
            } else {
                // Opens when the trip departs (Q142) - said as such, never the sender's number (Q44).
                let terminal = BookingActions.of(base.serviceStatus).terminal
                items.append((strings.t("driverBooking.receiver"), booking.parcelContacts?.receiverName ?? "—",
                              terminal ? nil : strings.t("driverBooking.receiverHidden")))
            }
            items.append(price)
            let pieces = strings.t("client.booking.quantityPieces", ("count", base.quantity))
            let size = base.parcelCategory.map(strings.name)
            items.append((strings.t("amendment.quantityLabel"), [pieces, size].compactMap { $0 }.joined(separator: " · "), nil))
            items.append((strings.t("client.booking.weight"),
                          base.parcelCategory.map { strings.t("client.booking.weightUpTo", ("weight", BookingDetailRules.weightText(grams: $0.maxWeightG))) } ?? "—",
                          nil))
        } else {
            items.append((strings.t("client.taxi.passenger"), clientName, nil))
            items.append(price)
            items.append((strings.t("client.taxi.seats"), strings.t("seatPicker.peopleCount", ("count", base.quantity)), nil))
            items.append((strings.t("driverBid.pickupWindow"), strings.bookingWhen(base) ?? "—", nil))
        }
        let rows = stride(from: 0, to: items.count, by: 2).map { Array(items[$0..<min($0 + 2, items.count)]) }
        return HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    HStack(alignment: .top, spacing: 12) {
                        fact(row[0])
                        if row.count > 1 { fact(row[1]) } else { Color.clear.frame(maxWidth: .infinity, maxHeight: 1) }
                    }
                }
            }
            if parcel { photo }
        }
        .accessibilityIdentifier("elchi.driver.booking.facts")
    }

    private var clientName: String {
        let name = booking.client?.displayName.trimmingCharacters(in: .whitespaces) ?? ""
        return name.isEmpty ? strings.t("driver.booking.clientFallback") : name
    }

    private func fact(_ item: (String, String, String?)) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(item.0).font(ElchiFont.caption).foregroundStyle(c.muted)
            Text(item.1).font(ElchiFont.poppins(14.5, .medium)).foregroundStyle(c.text).lineSpacing(1).lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            if let detail = item.2 { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    /// The cash the driver collects (the fare never goes through ELCHI) and the commission this booking costs (Q103).
    private var money: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(strings.t("driverBooking.fareCash", ("amount", strings.money(DriverBookingMoney.cashToCollect(booking)))))
                .font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.text).fixedSize(horizontal: false, vertical: true)
            if let commission = DriverBookingMoney.commission(booking) {
                Text("\(strings.t("driver.booking.commission")): \(strings.t("driver.booking.commissionValue", ("amount", strings.money(commission.minor)), ("percent", commission.percent)))")
                    .font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
            }
            Text(strings.t("bookingDetail.fareNote")).font(ElchiFont.caption).foregroundStyle(c.muted).fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.driver.booking.money")
    }

    /// The parcel photo's signed link (Q6: short-lived - pulling to refresh fetches a new one).
    private var photo: some View {
        Group {
            if let photoURL {
                AsyncImage(url: photoURL) { phase in
                    switch phase {
                    case .success(let image): image.resizable().scaledToFill()
                    case .failure: caption(strings.t("app.photo.reload"))
                    default: ProgressView()
                    }
                }
            } else {
                caption(strings.t("app.photo.none"))
            }
        }
        .frame(width: 92, height: 150)
        .background(c.field)
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .accessibilityElement()
        .accessibilityLabel(strings.t("driverBooking.parcelPhoto"))
    }

    private func caption(_ text: String) -> some View {
        Text(text).font(ElchiFont.poppins(10.5)).foregroundStyle(c.muted).multilineTextAlignment(.center).padding(6)
    }
}
