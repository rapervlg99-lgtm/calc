/** Тип конструкции (несущая / самонесущая). */
export const BEARING_TYPES = ["Несущая", "Самонесущая"] as const;

export type BearingType = (typeof BEARING_TYPES)[number];

/** Список для select; если текущее значение не из канона — добавляем его первым. */
export function bearingTypeChoices(current?: string): string[] {
  const c = (current ?? "").trim();
  if (c && !(BEARING_TYPES as readonly string[]).includes(c)) {
    return [c, ...BEARING_TYPES];
  }
  return [...BEARING_TYPES];
}
