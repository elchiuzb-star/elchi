export function normalizeUzPhone(value: string): string {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 9) return `+998${digits}`;
  if (digits.length === 12 && digits.startsWith("998")) return `+${digits}`;
  return value.trim();
}

export function isValidUzPhone(value: string): boolean {
  return /^\+998\d{9}$/.test(normalizeUzPhone(value));
}

export function formatUzPhoneInput(value: string): string {
  const normalized = normalizeUzPhone(value);
  if (!/^\+998\d{0,9}$/.test(normalized)) return value;
  const local = normalized.replace("+998", "");
  const parts = [local.slice(0, 2), local.slice(2, 5), local.slice(5, 7), local.slice(7, 9)].filter(Boolean);
  return `+998 ${parts.join(" ")}`.trim();
}
