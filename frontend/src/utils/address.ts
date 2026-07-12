import { hasCoordinates } from "./maps";

function addressParts(address: string): string[] {
  return address.trim().split(",").map((part) => part.trim()).filter(Boolean);
}

export function formatShortAddress(address: string): string {
  const trimmed = address.trim();
  if (!trimmed) return "";
  const parts = addressParts(trimmed);
  return parts.slice(0, 2).join(", ") || trimmed;
}

export function formatAddressTitle(address: string): string {
  const trimmed = address.trim();
  if (!trimmed) return "";
  const parts = addressParts(trimmed);
  return parts[0] ?? trimmed;
}

export function formatAddressRegion(address: string): string {
  const parts = addressParts(address);
  return parts.slice(1).join(", ");
}

export function formatMapSelectionStatus(lat?: number | string | null, lng?: number | string | null): string {
  return hasCoordinates(lat, lng) ? "Xaritada belgilangan" : "Xaritada belgilanmagan";
}
