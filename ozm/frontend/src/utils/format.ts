const nf2 = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2
});

export function num(value: number): string {
  return nf2.format(value);
}

export function massWithUnit(value: number, unit: "kg" | "t"): string {
  return `${num(value)} ${unit === "t" ? "т" : "кг"}`;
}
