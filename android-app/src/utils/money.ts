export function formatUzs(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "Narx haydovchi bilan kelishiladi";
  }
  const numeric = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(numeric)) {
    return "Narx haydovchi bilan kelishiladi";
  }
  return `${Math.trunc(numeric).toLocaleString("ru-RU").replace(/\u00a0/g, " ")} so'm`;
}

export function formatAdminMoney(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(numeric)) return "-";
  return `${Math.trunc(numeric).toLocaleString("ru-RU").replace(/\u00a0/g, " ")} so'm`;
}

export const formatUZS = formatAdminMoney;
