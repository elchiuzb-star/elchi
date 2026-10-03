import Contacts
import ContactsUI
import SwiftUI

// The BOSQICH 02 design's building blocks for the request flow: the error list, the departure-window tiles and their
// bottom sheet (also on the taxi home), the people buttons, the ±5 000 price stepper, the total bar, the contact card
// and its sheet, the option sheets and the comment field.

// MARK: - Error list

/// The red box a tap on an incomplete step puts at the top (`errsFor`): one line per problem.
struct ErrorList: View {
    let lines: [String]
    var compact = false
    @Environment(\.elchi) private var c

    var body: some View {
        let tone = c.tone(.err)
        HStack(alignment: .top, spacing: 10) {
            ElchiIcon.alert.image(size: compact ? 16 : 18).foregroundStyle(tone.fg).padding(.top, 1)
            VStack(alignment: .leading, spacing: compact ? 1 : 2) {
                ForEach(lines, id: \.self) { Text($0) }
            }
            .font(ElchiFont.poppins(compact ? 12.5 : 13)).lineSpacing(2)
            .foregroundStyle(tone.noteText)
            .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14).padding(.vertical, compact ? 10 : 12)
        .background(tone.bg, in: RoundedRectangle(cornerRadius: compact ? 14 : ElchiShape.note))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.order.errors")
    }
}

/// The error-tone border of a field that a validation tap marked.
private struct ErrorBorder: ViewModifier {
    let on: Bool
    let radius: CGFloat
    @Environment(\.elchi) private var c

    func body(content: Content) -> some View {
        content.overlay { if on { RoundedRectangle(cornerRadius: radius).strokeBorder(c.tone(.err).fg.opacity(0.75), lineWidth: 1.5) } }
    }
}

extension View {
    func errorBorder(_ on: Bool, radius: CGFloat) -> some View { modifier(ErrorBorder(on: on, radius: radius)) }
}

/// A 13 pt medium label above a block (the design's section labels).
struct BlockLabel: View {
    let text: String
    var trailing: String?
    @Environment(\.elchi) private var c

    var body: some View {
        HStack {
            Text(text).font(ElchiFont.label).foregroundStyle(c.text)
            Spacer(minLength: 8)
            if let trailing { Text(trailing).font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.accentText) }
        }
    }
}

// MARK: - Departure window tiles

/// Two tiles side by side (`09:00 Ertaga, 28 sen → 18:00 …`); a tap opens the window sheet on that edge. `onCard`:
/// the route step's white card; otherwise the taxi home's field-coloured track.
struct WindowTiles: View {
    let start: Date?
    let end: Date?
    var errorStart = false
    var errorEnd = false
    var onCard = false
    let onTap: (WindowEdge) -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(spacing: 0) {
            tile(.start, start, error: errorStart)
            Text("→").font(ElchiFont.poppins(14)).foregroundStyle(Color(hex: 0x9AA6B5)).accessibilityHidden(true)
            tile(.end, end, error: errorEnd)
        }
        .padding(4)
        .background(onCard ? c.card : c.page, in: RoundedRectangle(cornerRadius: 16))
        .shadow(color: onCard ? c.shadow.opacity(0.6) : .clear, radius: 12, y: 6)
    }

    private func tile(_ edge: WindowEdge, _ value: Date?, error: Bool) -> some View {
        let label = strings.t(edge == .start ? "client.order.windowStartShort" : "client.order.windowEndShort")
        return Button { onTap(edge) } label: {
            HStack(spacing: 6) {
                Text(value.map(strings.clock) ?? "--:--").font(ElchiFont.poppins(15, .semibold)).monospacedDigit()
                    .foregroundStyle(value == nil ? c.placeholder : c.text)
                Text(value.map { strings.tileDate($0) } ?? strings.t(edge == .start ? "client.order.windowStartEmpty" : "client.order.windowEndEmpty"))
                    .font(ElchiFont.caption).foregroundStyle(value == nil ? c.placeholder : c.accentText)
                    .lineLimit(1).minimumScaleFactor(0.8)
            }
            .padding(.horizontal, 6)
            .frame(maxWidth: .infinity, minHeight: 44)
            .contentShape(Rectangle())
            .errorBorder(error, radius: 12)
        }
        .buttonStyle(PressFade())
        .accessibilityLabel(label)
        .accessibilityValue(value.map { "\(strings.clock($0)), \(strings.tileDate($0))" } ?? "--:--")
        .accessibilityIdentifier("elchi.window.\(edge.rawValue)")
    }
}

// MARK: - Departure window sheet (6.5)

/// The design's window sheet: Boshlanishi | Tugashi tabs, a 21-day strip, hour and quarter-hour wheels, quick end
/// lengths, the past / order checks, and "Keyingi: tugash vaqti" or "Tayyor". Asia/Tashkent whatever the phone says.
struct DepartureWindowSheet: View {
    let onDone: (Date?, Date?) -> Void
    @State private var edge: WindowEdge
    @State private var start: Date?
    @State private var end: Date?
    @State private var day = 0
    @State private var hour = 9
    @State private var minute = 0
    @State private var height: CGFloat = 640
    private let days: [Date]
    private let now: Date
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    init(edge: WindowEdge, start: Date?, end: Date?, now: Date = Date(), onDone: @escaping (Date?, Date?) -> Void) {
        self.onDone = onDone
        self.now = now
        days = WindowPicker.days(now: now)
        _edge = State(initialValue: edge)
        _start = State(initialValue: start)
        _end = State(initialValue: end)
        let (d, h, m) = Self.initial(edge: edge, start: start, end: end, days: days)
        _day = State(initialValue: d)
        _hour = State(initialValue: h)
        _minute = State(initialValue: m)
    }

    /// Where the wheels start: the edge's value, else six hours after the start (end), else today 12:00.
    private static func initial(edge: WindowEdge, start: Date?, end: Date?, days: [Date]) -> (Int, Int, Int) {
        if let value = edge == .start ? start : end { return WindowPicker.parts(value, days: days) }
        if edge == .end, let start {
            let p = WindowPicker.parts(start, days: days)
            return (p.day, min(23, p.hour + 6), p.minute)
        }
        return (0, 12, 0)
    }

    private var selected: Date { WindowPicker.compose(day: days[min(day, days.count - 1)], hour: hour, minute: minute) }
    private var problem: String? { WindowPicker.problemKey(edge: edge, value: selected, start: edge == .end ? start : nil, now: now) }

    var body: some View {
        VStack(spacing: 14) {
            tabs
            HStack(alignment: .firstTextBaseline) {
                Text(strings.monthTitle(days[min(day, days.count - 1)])).font(ElchiFont.poppins(15, .semibold)).foregroundStyle(c.text)
                Spacer()
                Text(strings.t("client.order.picker.swipe")).font(ElchiFont.caption).foregroundStyle(c.muted)
            }
            .padding(.horizontal, 16)
            dayStrip
            wheels
            if edge == .end, let start {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(WindowPicker.quickHours, id: \.self) { hours in
                            quick(strings.t("client.order.picker.plusHours", ("hours", hours))) { set(WindowPicker.quick(hours: hours, from: start)) }
                        }
                        quick(strings.t("client.order.picker.endOfDay")) { set(WindowPicker.quick(hours: nil, from: start)) }
                    }
                    .padding(.horizontal, 16)
                }
            }
            if let problem {
                Text(strings.t(problem)).font(ElchiFont.poppins(12.5)).foregroundStyle(c.tone(.err).fg)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16)
                    .accessibilityIdentifier("elchi.window.problem")
            }
            ElchiButton(edge == .end || end != nil ? strings.t("client.keyboard.done") : strings.t("client.order.picker.next"),
                        dimmed: problem != nil, action: done)
                .padding(.horizontal, 16)
                .accessibilityIdentifier("elchi.window.done")
        }
        .padding(.top, 22).padding(.bottom, 12)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height = $0 + 20 }
        .frame(maxHeight: .infinity, alignment: .top)
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.height(height)])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(ElchiShape.sheet)
    }

    private var tabs: some View {
        HStack(spacing: 4) {
            tab(.start, value: edge == .start ? selected : start)
            tab(.end, value: edge == .end ? selected : end)
        }
        .padding(4)
        .background(c.field, in: Capsule())
        .padding(.horizontal, 16)
    }

    private func tab(_ which: WindowEdge, value: Date?) -> some View {
        let active = which == edge
        return Button { switchTo(which) } label: {
            VStack(spacing: 0) {
                Text(strings.t(which == .start ? "client.order.windowStartShort" : "client.order.windowEndShort"))
                    .font(ElchiFont.poppins(11)).foregroundStyle(c.muted)
                Text(value.map { "\(strings.shortDay($0)), \(strings.clock($0))" } ?? "—")
                    .font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.text).lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .background(active ? c.card : .clear, in: Capsule())
            .shadow(color: active ? c.shadow.opacity(0.5) : .clear, radius: 3, y: 1)
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(active ? .isSelected : [])
        .accessibilityIdentifier("elchi.window.tab.\(which.rawValue)")
    }

    private var dayStrip: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Array(days.enumerated()), id: \.offset) { index, date in
                        let on = index == day
                        Button { day = index } label: {
                            VStack(spacing: 2) {
                                Text(strings.dayName(date, now: now)).font(ElchiFont.poppins(11, .medium)).lineLimit(1).minimumScaleFactor(0.7)
                                    .foregroundStyle(on ? c.onBrand : c.muted)
                                Text("\(DepartureWindow.calendar.component(.day, from: date))").font(ElchiFont.poppins(20, .semibold))
                                    .foregroundStyle(on ? c.onBrand : c.text)
                                Text(strings.monthShort(date)).font(ElchiFont.poppins(10)).foregroundStyle(on ? c.onBrand : c.muted)
                            }
                            .padding(.horizontal, 2)
                            .frame(width: 58, height: 74)
                            .background(on ? c.brand : c.page, in: RoundedRectangle(cornerRadius: 18))
                            .overlay { if !on { RoundedRectangle(cornerRadius: 18).strokeBorder(c.line, lineWidth: 1) } }
                        }
                        .buttonStyle(.plain)
                        .id(index)
                        .accessibilityLabel("\(strings.dayName(date, now: now)), \(strings.shortDay(date))")
                        .accessibilityAddTraits(on ? .isSelected : [])
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 2)
            }
            .onAppear { proxy.scrollTo(max(day - 1, 0), anchor: .leading) }
            .onChange(of: edge) { _, _ in withAnimation { proxy.scrollTo(max(day - 1, 0), anchor: .leading) } }
        }
    }

    private var wheels: some View {
        HStack(spacing: 0) {
            Picker("", selection: $hour) {
                ForEach(0..<24, id: \.self) { Text(String(format: "%02d", $0)).font(ElchiFont.poppins(22, .semibold)).tag($0) }
            }
            .pickerStyle(.wheel).frame(width: 96)
            .accessibilityLabel(strings.t(edge == .start ? "client.order.windowStartShort" : "client.order.windowEndShort"))
            Text(":").font(ElchiFont.poppins(24, .semibold)).foregroundStyle(c.text).padding(.bottom, 4)
            Picker("", selection: $minute) {
                ForEach(WindowPicker.minuteOptions(including: minute), id: \.self) {
                    Text(String(format: "%02d", $0)).font(ElchiFont.poppins(22, .semibold)).tag($0)
                }
            }
            .pickerStyle(.wheel).frame(width: 96)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 200)
        .clipped()
        .background(c.page, in: RoundedRectangle(cornerRadius: 20))
        .padding(.horizontal, 16)
    }

    private func quick(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(ElchiFont.poppins(13, .medium)).foregroundStyle(c.softText)
                .padding(.horizontal, 14).frame(minHeight: 36)
                .background(c.soft, in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private func set(_ date: Date) {
        let p = WindowPicker.parts(date, days: days)
        day = p.day
        hour = p.hour
        minute = p.minute
    }

    private func commit() {
        if edge == .start { start = selected } else { end = selected }
    }

    private func switchTo(_ which: WindowEdge) {
        guard which != edge else { return }
        if problem == nil { commit() }
        edge = which
        let (d, h, m) = Self.initial(edge: which, start: start, end: end, days: days)
        day = d
        hour = h
        minute = m
    }

    private func done() {
        guard problem == nil else { return }
        commit()
        if edge == .start && end == nil {
            switchTo(.end)
        } else {
            onDone(start, end)
        }
    }
}

// MARK: - People (Taksi)

/// "Necha kishi": 1 / 2 / 3 / Butun salon (= 4 seats), the whole cabin a wider button.
struct SeatCountPicker: View {
    @Binding var count: Int?
    var error = false
    var height: CGFloat = 46
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        GeometryReader { geo in
            let unit = (geo.size.width - 24) / 4.6
            HStack(spacing: 8) {
                ForEach(TaxiSeats.options, id: \.self) { n in
                    let on = count == n
                    let whole = TaxiSeats.isWholeCabin(n)
                    Button { count = n } label: {
                        Text(whole ? strings.t("client.taxi.wholeCabin") : "\(n)")
                            .font(ElchiFont.poppins(whole ? 14 : 18, .semibold)).lineLimit(1).minimumScaleFactor(0.7)
                            .foregroundStyle(on ? c.onBrand : c.text)
                            .padding(.horizontal, 6)
                            .frame(width: whole ? unit * 1.6 : unit, height: height)
                            .background(on ? c.brand : c.card, in: RoundedRectangle(cornerRadius: 14))
                            .overlay { if !on { RoundedRectangle(cornerRadius: 14).strokeBorder(c.outline, lineWidth: 1.5) } }
                    }
                    .buttonStyle(PressFade())
                    .accessibilityLabel(whole ? strings.t("client.taxi.wholeCabinSeats") : strings.t("orderForm.review.peopleCount", ("count", n)))
                    .accessibilityAddTraits(on ? .isSelected : [])
                    .accessibilityIdentifier("elchi.seats.\(n)")
                }
            }
        }
        .frame(height: height)
        .errorBorder(error, radius: 18)
    }
}

// MARK: - Price stepper

/// `−  [ 120 000 so'm ]  +`: ±5 000 a tap, typing allowed (8 digits). `onCard`: the route step's white card; the taxi
/// home uses the field colour.
struct PriceStepper: View {
    @Binding var digits: String
    let label: String
    var error = false
    var onCard = false
    var onFocus: ((Bool) -> Void)?
    @State private var text = ""
    @FocusState private var focused: Bool
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let positive = (Int(digits) ?? 0) > 0
        HStack(spacing: 8) {
            Button { digits = PriceStep.apply(digits, delta: -1) } label: {
                Text("−").font(.system(size: 24, weight: .medium))
                    .foregroundStyle(positive ? c.text : c.placeholder.opacity(0.7))
                    .frame(width: 46, height: 46)
                    .background(onCard ? (positive ? c.field : c.page) : c.card, in: RoundedRectangle(cornerRadius: 14))
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(strings.t("client.order.priceDec"))
            .accessibilityIdentifier("elchi.price.dec")
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                TextField("", text: $text, prompt: Text("0").foregroundStyle(c.placeholder))
                    .font(ElchiFont.poppins(onCard ? 22 : 21, .semibold)).monospacedDigit()
                    .multilineTextAlignment(.center)
                    .foregroundStyle(c.text)
                    .keyboardType(.numberPad)
                    .tint(c.brand)
                    .focused($focused)
                    .accessibilityLabel(label)
                    .accessibilityIdentifier("elchi.price")
                    .onChange(of: text) { _, typed in
                        let clean = PriceStep.digits(typed)
                        if digits != clean { digits = clean }
                        let formatted = Money.grouped(clean)
                        if text != formatted { text = formatted }
                    }
                    .onChange(of: focused) { _, now in onFocus?(now) }
                Text(strings.t("common.soum")).font(ElchiFont.secondary).foregroundStyle(c.muted).fixedSize()
            }
            .frame(maxWidth: .infinity)
            Button { digits = PriceStep.apply(digits, delta: 1) } label: {
                Text("+").font(.system(size: 24, weight: .medium)).foregroundStyle(c.onBrand)
                    .frame(width: 46, height: 46)
                    .background(c.brand, in: RoundedRectangle(cornerRadius: 14))
            }
            .buttonStyle(PressFade())
            .accessibilityLabel(strings.t("client.order.priceInc"))
            .accessibilityIdentifier("elchi.price.inc")
        }
        .padding(.horizontal, 5)
        .frame(height: onCard ? 60 : 56)
        .background(onCard ? c.card : c.page, in: RoundedRectangle(cornerRadius: 18))
        .shadow(color: onCard ? c.shadow.opacity(0.6) : .clear, radius: 12, y: 6)
        .errorBorder(error, radius: 18)
        .onAppear { text = Money.grouped(digits) }
        .onChange(of: digits) { _, value in
            let formatted = Money.grouped(value)
            if text != formatted { text = formatted }
        }
    }
}

/// "Jami · 2 kishi            300 000 so'm" (taxi home).
struct TotalBar: View {
    let who: String
    let total: String
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(strings.t("client.order.totalFor", ("who", who))).font(ElchiFont.poppins(13))
                .foregroundStyle(c.isDark ? c.tone(.blue).noteText : Color(hex: 0x0B3E73))
            Spacer(minLength: 8)
            Text(total).font(ElchiFont.poppins(18, .semibold)).foregroundStyle(c.text)
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xEAF5FF), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("elchi.taxi.total")
    }
}

// MARK: - Contacts

/// A person on the contact step (design 7.2): avatar, name, `+998 90 123 45 67`, "O'zgartirish" - or, empty, "Kontaktdan
/// tanlang / Ism va telefon raqami / Tanlash". The whole card opens the contact sheet.
struct ContactCard: View {
    let label: String
    let name: String
    let phone: String
    var error = false
    let action: () -> Void
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        let filled = ContactBlocker.validName(name) && UzPhone.isValid(phone)
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(ElchiFont.label).foregroundStyle(c.text)
            Button(action: action) {
                HStack(spacing: 12) {
                    Group {
                        if filled {
                            Text(Initials.of(name) ?? "").font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.softText)
                        } else {
                            ElchiIcon.users.image(size: 20).foregroundStyle(c.accentText)
                        }
                    }
                    .frame(width: 40, height: 40)
                    .background(filled ? c.soft : (c.isDark ? Color(hex: 0x1D2A3A) : Color(hex: 0xEEF4FA)), in: Circle())
                    VStack(alignment: .leading, spacing: 1) {
                        Text(filled ? name : strings.t("client.order.contactEmpty")).font(ElchiFont.poppins(15, .semibold))
                            .foregroundStyle(filled ? c.text : c.placeholder).lineLimit(1)
                        Text(filled ? "+998 \(UzPhone.formatLocal(phone))" : strings.t("client.order.contactEmptyHint"))
                            .font(filled ? .system(size: 12.5, design: .monospaced) : ElchiFont.caption).foregroundStyle(c.muted)
                    }
                    Spacer(minLength: 0)
                    Text(strings.t(filled ? "app.route.change" : "client.order.choosePick")).font(ElchiFont.poppins(12.5, .semibold))
                        .foregroundStyle(c.accentText)
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .frame(minHeight: 62)
                .background(c.card, in: RoundedRectangle(cornerRadius: 18))
                .shadow(color: c.shadow.opacity(0.6), radius: 12, y: 6)
                .errorBorder(error, radius: 18)
                .contentShape(Rectangle())
            }
            .buttonStyle(PressFade())
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
        }
    }
}

/// The contact sheet (7.3): search, "Telefon kontaktlari" (the system picker - no contacts permission), "+ Yangi raqam"
/// (name + 9 digits), and the signed-in person under "SIZ". Recent receivers and an in-app contact list have no
/// endpoint and are not shown.
struct ContactPickerSheet: View {
    let title: String
    let meName: String
    let mePhone: String
    let currentPhone: String
    let onPick: (String, String) -> Void
    @State private var query = ""
    /// "Tanlash" was tapped with a short name or an incomplete number.
    @State private var invalidTap = false
    @State private var manual = false
    @State private var manualName = ""
    @State private var manualPhone = ""
    @State private var phoneText = ""
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text(title).font(ElchiFont.poppins(19, .medium)).foregroundStyle(c.text).accessibilityAddTraits(.isHeader)
                HStack(spacing: 10) {
                    ElchiIcon.search.image(size: 18).foregroundStyle(c.muted)
                    TextField("", text: $query, prompt: Text(strings.t("client.order.contactSearch")).foregroundStyle(c.placeholder))
                        .font(ElchiFont.body).foregroundStyle(c.text).tint(c.brand)
                        .accessibilityLabel(strings.t("client.order.contactSearch"))
                }
                .padding(.horizontal, 14).frame(height: 48)
                .background(c.field, in: RoundedRectangle(cornerRadius: 16))
                HStack(spacing: 8) {
                    Button { DeviceContactPicker.present(onPick: fromDevice) } label: {
                        HStack(spacing: 6) {
                            ElchiIcon.phone.image(size: 16)
                            Text(strings.t("client.order.deviceContacts")).lineLimit(1).minimumScaleFactor(0.8)
                        }
                        .font(ElchiFont.poppins(13.5, .medium)).foregroundStyle(c.softText)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(c.soft, in: Capsule())
                    }
                    .buttonStyle(PressFade())
                    Button { manual.toggle() } label: {
                        Text(strings.t("client.order.newNumber")).font(ElchiFont.poppins(13.5, .medium)).lineLimit(1)
                            .foregroundStyle(manual ? .white : c.text)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(manual ? (c.isDark ? Color(hex: 0x1B3563) : c.navy) : c.field, in: Capsule())
                    }
                    .buttonStyle(PressFade())
                    .accessibilityAddTraits(manual ? .isSelected : [])
                    .accessibilityIdentifier("elchi.contact.new")
                }
                if manual { manualForm }
                if showsMe {
                    Text(strings.t("client.order.groupYou")).font(ElchiFont.poppins(12, .semibold)).tracking(0.7).foregroundStyle(c.muted)
                        .padding(.top, 4)
                    Button { onPick(meName, mePhone) } label: { meRow }
                        .buttonStyle(PressFade())
                } else if !manual {
                    Text(strings.t("client.order.contactNone")).font(ElchiFont.poppins(13)).foregroundStyle(c.muted)
                        .multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.vertical, 14)
                }
            }
            .padding(EdgeInsets(top: 24, leading: 16, bottom: 28, trailing: 16))
        }
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(ElchiShape.sheet)
    }

    private var showsMe: Bool {
        guard ContactBlocker.validName(meName), UzPhone.isValid(mePhone) else { return false }
        let q = SearchText.normalized(query).replacingOccurrences(of: " ", with: "")
        return q.isEmpty || SearchText.normalized(meName).replacingOccurrences(of: " ", with: "").contains(q) || mePhone.contains(q)
    }

    private var meRow: some View {
        let on = currentPhone == mePhone
        return HStack(spacing: 12) {
            Text(Initials.of(meName) ?? "").font(ElchiFont.poppins(13, .semibold)).foregroundStyle(c.onBrand)
                .frame(width: 38, height: 38).background(c.brand, in: Circle())
            VStack(alignment: .leading, spacing: 1) {
                Text(strings.t("client.order.me", ("name", meName))).font(ElchiFont.poppins(14.5, .semibold)).foregroundStyle(c.text)
                Text("+998 \(UzPhone.formatLocal(mePhone))").font(.system(size: 12.5, design: .monospaced)).foregroundStyle(c.muted)
            }
            Spacer(minLength: 0)
            if on { ElchiIcon.checkC.image(size: 18).foregroundStyle(c.tone(.ok).fg) }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(on ? (c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xF0F8FF)) : c.card, in: RoundedRectangle(cornerRadius: 18))
        .overlay { RoundedRectangle(cornerRadius: 18).strokeBorder(c.line, lineWidth: 1) }
        .contentShape(Rectangle())
    }

    private var manualForm: some View {
        let valid = ContactBlocker.validName(manualName) && UzPhone.isValid(manualPhone)
        return VStack(spacing: 8) {
            TextField("", text: $manualName, prompt: Text(strings.t("client.order.manualName")).foregroundStyle(c.placeholder))
                .font(ElchiFont.body).foregroundStyle(c.text).tint(c.brand).textContentType(.name)
                .padding(.horizontal, 14).frame(height: 46)
                .background(c.card, in: RoundedRectangle(cornerRadius: 14))
                .accessibilityLabel(strings.t("client.order.manualName"))
                .accessibilityIdentifier("elchi.contact.manualName")
            HStack(spacing: 10) {
                Text("+998").font(ElchiFont.poppins(14, .semibold)).foregroundStyle(c.muted)
                TextField("", text: $phoneText, prompt: Text("90 123 45 67").foregroundStyle(c.placeholder))
                    .font(.system(size: 15, design: .monospaced)).foregroundStyle(c.text).tint(c.brand)
                    .keyboardType(.phonePad).textContentType(.telephoneNumber)
                    .accessibilityLabel(strings.t("orderForm.receiverPhone"))
                    .accessibilityIdentifier("elchi.contact.manualPhone")
                    .onChange(of: phoneText) { _, typed in
                        manualPhone = UzPhone.localDigits(typed)
                        let formatted = UzPhone.formatLocal(manualPhone)
                        if phoneText != formatted { phoneText = formatted }
                    }
            }
            .padding(.horizontal, 14).frame(height: 46)
            .background(c.card, in: RoundedRectangle(cornerRadius: 14))
            ElchiButton(strings.t("client.order.choosePick"), size: .medium, dimmed: !valid) {
                if valid { onPick(manualName.trimmingCharacters(in: .whitespacesAndNewlines), manualPhone) } else { invalidTap = true }
            }
            .accessibilityIdentifier("elchi.contact.manualPick")
            if invalidTap && !valid {
                Text(strings.t("client.order.manualInvalid")).font(ElchiFont.poppins(12.5)).foregroundStyle(c.tone(.err).fg)
            }
        }
        .padding(12)
        .background(c.page, in: RoundedRectangle(cornerRadius: 18))
    }

    /// A contact from the phone: straight in when it has a full Uzbek number, else into "+ Yangi raqam" to finish.
    private func fromDevice(_ name: String, _ phone: String) {
        let digits = UzPhone.localDigits(phone)
        if ContactBlocker.validName(name) && UzPhone.isValid(digits) {
            onPick(name, digits)
        } else {
            manual = true
            manualName = name
            phoneText = UzPhone.formatLocal(digits)
        }
    }
}

/// The system contact picker (`CNContactPickerViewController`): it runs out of process, so the app needs no contacts
/// permission. Presented from UIKit - SwiftUI sheets dismiss it at once.
@MainActor
enum DeviceContactPicker {
    private static var delegate: Delegate?

    static func present(onPick: @escaping (String, String) -> Void) {
        let picker = CNContactPickerViewController()
        picker.displayedPropertyKeys = [CNContactPhoneNumbersKey]
        picker.predicateForEnablingContact = NSPredicate(format: "phoneNumbers.@count > 0")
        picker.predicateForSelectionOfContact = NSPredicate(format: "phoneNumbers.@count == 1")
        let delegate = Delegate(onPick: onPick)
        Self.delegate = delegate
        picker.delegate = delegate
        topController()?.present(picker, animated: true)
    }

    private static func topController() -> UIViewController? {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first { $0.activationState == .foregroundActive }
            ?? UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        var top = scene?.windows.first { $0.isKeyWindow }?.rootViewController
        while let next = top?.presentedViewController { top = next }
        return top
    }

    @MainActor
    private final class Delegate: NSObject, @preconcurrency CNContactPickerDelegate {
        let onPick: (String, String) -> Void
        init(onPick: @escaping (String, String) -> Void) { self.onPick = onPick }

        private func name(_ contact: CNContact) -> String {
            CNContactFormatter.string(from: contact, style: .fullName) ?? "\(contact.givenName) \(contact.familyName)".trimmingCharacters(in: .whitespaces)
        }

        func contactPicker(_ picker: CNContactPickerViewController, didSelect contact: CNContact) {
            onPick(name(contact), contact.phoneNumbers.first?.value.stringValue ?? "")
        }

        func contactPicker(_ picker: CNContactPickerViewController, didSelect contactProperty: CNContactProperty) {
            onPick(name(contactProperty.contact), (contactProperty.value as? CNPhoneNumber)?.stringValue ?? "")
        }
    }
}

// MARK: - Option sheet

/// A bottom sheet of radio options ("Posilka turi", "Jo'natma o'lchami") with an optional badge and note.
struct OptionSheet<Extra: View>: View {
    struct Option: Identifiable {
        let id: String
        let icon: ElchiIcon?
        let title: String
        let detail: String?
        let selected: Bool
        var enabled = true
    }

    let title: String
    var badge: String?
    let options: [Option]
    var note: String?
    let onPick: (String) -> Void
    @ViewBuilder let extra: () -> Extra
    @Environment(\.elchi) private var c

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Text(title).font(ElchiFont.poppins(19, .medium)).foregroundStyle(c.text).accessibilityAddTraits(.isHeader)
                    Spacer(minLength: 0)
                    if let badge {
                        Text(badge).font(ElchiFont.badge).foregroundStyle(c.accentText).lineLimit(1)
                            .padding(.horizontal, 10).padding(.vertical, 4).background(c.soft, in: Capsule())
                    }
                }
                extra()
                ForEach(options) { option in
                    Button { onPick(option.id) } label: { row(option) }
                        .buttonStyle(.plain)
                        .disabled(!option.enabled)
                        .accessibilityElement(children: .combine)
                        .accessibilityAddTraits(option.selected ? [.isButton, .isSelected] : .isButton)
                        .accessibilityIdentifier("elchi.option.\(option.id)")
                }
                if let note { Text(note).font(ElchiFont.caption).foregroundStyle(c.tone(.warn).fg) }
            }
            .padding(EdgeInsets(top: 24, leading: 16, bottom: 28, trailing: 16))
        }
        .background(c.card.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(ElchiShape.sheet)
    }

    private func row(_ option: Option) -> some View {
        HStack(spacing: 12) {
            if let icon = option.icon {
                icon.image(size: 20).foregroundStyle(c.accentText)
                    .frame(width: 38, height: 38)
                    .background(c.card, in: RoundedRectangle(cornerRadius: 12))
                    .overlay { RoundedRectangle(cornerRadius: 12).strokeBorder(c.line, lineWidth: 1) }
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(option.title).font(ElchiFont.poppins(14.5, .semibold)).foregroundStyle(c.text)
                if let detail = option.detail { Text(detail).font(ElchiFont.caption).foregroundStyle(c.muted) }
            }
            Spacer(minLength: 0)
            Circle().strokeBorder(option.selected ? c.brand : Color(hex: 0xB8C2CE), lineWidth: option.selected ? 6 : 2).frame(width: 20, height: 20)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(option.selected ? (c.isDark ? Color(hex: 0x0E2A45) : Color(hex: 0xF0F8FF)) : c.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(option.selected ? c.brand : c.line, lineWidth: option.selected ? 2 : 1) }
        .opacity(option.enabled ? 1 : 0.5)
        .contentShape(Rectangle())
    }
}

extension OptionSheet where Extra == EmptyView {
    init(title: String, badge: String? = nil, options: [Option], note: String? = nil, onPick: @escaping (String) -> Void) {
        self.init(title: title, badge: badge, options: options, note: note, onPick: onPick) { EmptyView() }
    }
}

// MARK: - The comment

/// "Izoh (ixtiyoriy)": up to 300 characters; a phone number or link in it gets the masking warning.
struct NoteField: View {
    @Binding var text: String
    @Environment(LocaleStore.self) private var strings
    @Environment(\.elchi) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(strings.t("client.order.noteLabel")).font(ElchiFont.label).foregroundStyle(c.text)
            TextField("", text: Binding(get: { text }, set: { text = NoteText.limited($0) }),
                      prompt: Text(strings.t("client.order.notePlaceholder")).foregroundStyle(c.placeholder), axis: .vertical)
                .lineLimit(2...6)
                .font(ElchiFont.body).foregroundStyle(c.text).tint(c.brand)
                .accessibilityLabel(strings.t("client.order.noteLabel"))
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(c.card, in: RoundedRectangle(cornerRadius: 18))
                .shadow(color: c.shadow.opacity(0.6), radius: 12, y: 6)
            if NoteText.carriesContact(text) {
                Text(strings.t("client.order.noteMasked")).font(ElchiFont.caption).foregroundStyle(c.tone(.warn).fg)
                    .accessibilityIdentifier("elchi.note.masked")
            }
        }
    }
}
