/** What the client does with each proof code. A passenger boarding code is never about a parcel. */
export function proofCodeHint(kind: string): string {
  switch (kind) {
    case "boarding_code":
      return "Mashinaga o'tirayotganingizda bu kodni haydovchiga ayting.";
    case "delivery_code":
      return "Bu kodni faqat qabul qiluvchiga bering.";
    case "return_code":
      return "Jo'natma sizga qaytarilganda bu kodni haydovchiga ayting.";
    default:
      return "Bu kodni haydovchiga posilkani topshirayotganda ayting.";
  }
}
