/** Канонические пределы огнестойкости (R) — как в калькуляторе 23met. */
export const FIRE_LIMITS = [
  "R15",
  "R30",
  "R45",
  "R60",
  "R90",
  "R120",
  "R150",
  "R180",
  "R210",
  "R240"
] as const;

export type FireLimit = (typeof FIRE_LIMITS)[number];

/** Список для select; если текущее значение не из канона — добавляем его первым. */
export function fireLimitChoices(current?: string): string[] {
  const c = (current ?? "").trim();
  if (c && !(FIRE_LIMITS as readonly string[]).includes(c)) {
    return [c, ...FIRE_LIMITS];
  }
  return [...FIRE_LIMITS];
}
