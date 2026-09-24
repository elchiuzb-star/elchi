import { translate } from "../i18n";

/** What the client does with each proof code. A passenger boarding code is never about a parcel. */
export function proofCodeHint(kind: string): string {
  switch (kind) {
    case "boarding_code":
      return translate("proofHint.boarding");
    case "delivery_code":
      return translate("proofHint.delivery");
    case "return_code":
      return translate("proofHint.return");
    default:
      return translate("proofHint.pickup");
  }
}
