/**
 * How many seats, chosen on a picture of the cabin instead of typed into a number box.
 *
 * **What is actually booked is the count.** A listing carries `seat_count`; there is no seat map in the
 * contract, no seat id on a booking and nothing that obliges a driver to seat anyone in a particular place.
 * So this screen lets a person mark the seats they picture themselves in - which is how people think about
 * "three of us, two in the back" - and then says plainly, once, that the exact seat is settled with the
 * driver rather than reserved here. Drawing a cabin and quietly implying a reservation would be the kind of
 * promise AGENTS.md section 9 rules out.
 *
 * The driver's seat is drawn because a cabin without one is not a cabin, and it is never selectable.
 */
import { cls } from "../../app/ui/mobile";
import { translate } from "../../i18n";

/** Passenger seats in a normal sedan, in the order a person reads them. */
const SEATS = [
  { id: "front", get label() { return translate("seatPicker.front"); }, row: 1 },
  { id: "rear-left", get label() { return translate("seatPicker.rearLeft"); }, row: 2 },
  { id: "rear-middle", get label() { return translate("seatPicker.rearMiddle"); }, row: 2 },
  { id: "rear-right", get label() { return translate("seatPicker.rearRight"); }, row: 2 },
] as const;

export type SeatId = (typeof SEATS)[number]["id"];

export const MAX_SEATS = SEATS.length;

function SeatButton({
  label,
  index,
  selected,
  onToggle,
}: {
  label: string;
  index: number | null;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      aria-label={label}
      title={label}
      className={cls(
        "el-press relative flex h-[62px] w-full flex-col items-center justify-center gap-1 rounded-[14px] border-2 transition-colors",
        selected ? "border-primary bg-primary/12" : "border-border bg-card",
      )}
    >
      {/* A seat, drawn rather than iconified: a back, a cushion and two arms read as a seat at this size. */}
      <span
        className={cls(
          "block h-4 w-7 rounded-t-[7px] border-2 border-b-0",
          selected ? "border-primary bg-primary/25" : "border-slate-300 bg-slate-100",
        )}
      />
      <span
        className={cls(
          "block h-2.5 w-9 rounded-b-[5px] border-2 border-t-0",
          selected ? "border-primary bg-primary/25" : "border-slate-300 bg-slate-100",
        )}
      />
      {selected && index !== null && (
        <span className="absolute right-1.5 top-1.5 flex h-[18px] w-[18px] items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">
          {index}
        </span>
      )}
    </button>
  );
}

export function SeatPicker({
  selected,
  onChange,
  label = translate("seatPicker.howMany"),
}: {
  selected: SeatId[];
  onChange: (seats: SeatId[]) => void;
  label?: string;
}) {
  const toggle = (id: SeatId) => {
    const next = selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id];
    // At least one: a passenger request for nobody is not a request. The cap is the cabin itself.
    onChange(next.length === 0 ? selected : next);
  };
  const orderOf = (id: SeatId) => {
    const index = selected.indexOf(id);
    return index === -1 ? null : index + 1;
  };

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <span className="text-[13px] font-semibold text-muted-foreground">{label}</span>
        <span className="text-[13px] font-semibold text-foreground">{translate("seatPicker.peopleCount", { count: selected.length })}</span>
      </div>

      <div className="rounded-[16px] border border-border bg-slate-50 p-3">
        <div className="grid grid-cols-4 gap-2">
          {/* The driver's place: drawn, never offered. */}
          <div
            className="flex h-[62px] w-full flex-col items-center justify-center gap-1 rounded-[14px] border-2 border-dashed border-slate-300 bg-slate-100"
            aria-hidden="true"
          >
            <span className="block h-5 w-5 rounded-full border-2 border-slate-400" />
            <span className="text-[9px] font-semibold text-slate-400">{translate("seatPicker.driver")}</span>
          </div>
          <div className="col-span-2" />
          <SeatButton
            label={SEATS[0].label}
            index={orderOf(SEATS[0].id)}
            selected={selected.includes(SEATS[0].id)}
            onToggle={() => toggle(SEATS[0].id)}
          />
        </div>

        <div className="mt-2 grid grid-cols-4 gap-2">
          <div />
          {SEATS.filter((seat) => seat.row === 2).map((seat) => (
            <SeatButton
              key={seat.id}
              label={seat.label}
              index={orderOf(seat.id)}
              selected={selected.includes(seat.id)}
              onToggle={() => toggle(seat.id)}
            />
          ))}
        </div>
      </div>

      <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
        {translate("seatPicker.bookedIs")}{" "}
        <span className="font-semibold text-foreground">{translate("seatPicker.seatCount")}</span>
        {translate("seatPicker.seatNotReserved")}
      </p>
    </div>
  );
}
