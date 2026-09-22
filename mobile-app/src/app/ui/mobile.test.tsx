/**
 * The design system's behaviour, not its looks.
 *
 * Colour and spacing are judged by eye; these are the parts of the components that can be *wrong* - a button
 * that is not really disabled, a phone field that lets a letter through, a status pill that shows a raw
 * English enum to an Uzbek speaker. Each of those shipped at least once in this app's history.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { Package, Truck } from "./icons";
import { describe, expect, it, vi } from "vitest";

import { ChoiceCard, CodeField, PhoneField, PrimaryButton, SegmentedControl, StatusBadge } from "./mobile";

describe("PrimaryButton", () => {
  it("does not fire while disabled", () => {
    const onClick = vi.fn();
    render(
      <PrimaryButton disabled onClick={onClick}>
        Davom etish
      </PrimaryButton>,
    );
    const button = screen.getByRole("button", { name: "Davom etish" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("ChoiceCard", () => {
  it("reports its selection to assistive technology, not only with colour", () => {
    render(
      <>
        <ChoiceCard icon={Package} label="Men mijozman" description="Posilka yuborish" active onClick={() => {}} />
        <ChoiceCard icon={Truck} label="Men haydovchiman" description="Buyurtmalar" active={false} onClick={() => {}} />
      </>,
    );
    expect(screen.getByRole("button", { name: /Men mijozman/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Men haydovchiman/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("calls back with the choice", () => {
    const onClick = vi.fn();
    render(<ChoiceCard icon={Truck} label="Men haydovchiman" active={false} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: /Men haydovchiman/ }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("SegmentedControl", () => {
  it("switches mode through the callback rather than local state", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        value="parcel"
        options={[["parcel", "Yuk"], ["passenger", "Yo'lovchi"]] as const}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Yo'lovchi" }));
    expect(onChange).toHaveBeenCalledWith("passenger");
  });
});

describe("StatusBadge", () => {
  it("shows the Uzbek sentence, never the raw enum", () => {
    render(<StatusBadge status="in_transit" />);
    expect(screen.getByText("Yo'lda")).toBeInTheDocument();
    expect(screen.queryByText("in_transit")).not.toBeInTheDocument();
  });

  it("colours by meaning, so finished and broken do not look alike", () => {
    const { container: done } = render(<StatusBadge status="delivered" />);
    const { container: broken } = render(<StatusBadge status="cancelled" />);
    expect(done.firstElementChild?.className).not.toBe(broken.firstElementChild?.className);
  });

  it("falls back to the code rather than to a blank pill for an unknown status", () => {
    render(<StatusBadge status="something_new" />);
    expect(screen.getByText("something_new")).toBeInTheDocument();
  });
});

describe("PhoneField", () => {
  it("keeps the digits and drops everything else", () => {
    const onChange = vi.fn();
    render(<PhoneField value="" onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText("__ ___ __ __"), { target: { value: "90 123-45-67" } });
    expect(onChange).toHaveBeenCalledWith("901234567");
  });

  it("stops at nine digits, so a pasted full number cannot overflow the field", () => {
    const onChange = vi.fn();
    render(<PhoneField value="" onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText("__ ___ __ __"), { target: { value: "998901234567" } });
    expect(onChange).toHaveBeenCalledWith("998901234");
  });
});

describe("CodeField", () => {
  it("accepts only digits and only as many as the code has", () => {
    const onChange = vi.fn();
    render(<CodeField label="5 xonali kod" value="" length={5} onChange={onChange} />);
    const input = screen.getByLabelText("5 xonali kod", { selector: "input" });
    fireEvent.change(input, { target: { value: "1a2b3c4d5e6" } });
    expect(onChange).toHaveBeenCalledWith("12345");
  });
});
