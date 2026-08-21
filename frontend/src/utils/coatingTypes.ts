/**
 * Типы защитного покрытия (fr_coat из ozm-calc).
 * Доступность TAIKOR зависит от предела огнестойкости R (таблицы x500).
 * δпр на этапе формы ещё нет — окончательная достижимость ОЗМ проверяется в калькуляторе.
 */

export const COATING_TYPES = [
  "ТЕХНО ОЗМ",
  "TAIKOR FP Epoxy",
  "TAIKOR FP Graphite",
  "TAIKOR FP Extra + TAIKOR FP Graphite",
  "АКЗ"
] as const;

export type CoatingType = (typeof COATING_TYPES)[number];

const TAIKOR_EPOXY_GRAPHITE_R = new Set([15, 30, 45, 60, 90, 120]);
const TAIKOR_EXTRA_R = new Set([90, 120]);

/** Минуты из строки вида R90 / «90» / «R 120». */
export function parseFireLimitMinutes(fireLimit?: string): number | null {
  const m = (fireLimit ?? "").trim().match(/(\d+)/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

/** Доступен ли тип покрытия при заданном пределе ОС (по данным x500). */
export function isCoatingAvailableForFireLimit(
  coating: string,
  fireLimit?: string
): boolean {
  const c = coating.trim();
  if (!c) return true;
  if (!(COATING_TYPES as readonly string[]).includes(c)) return true;

  const r = parseFireLimitMinutes(fireLimit);
  // R ещё не выбран — все канонические типы доступны.
  if (r == null) return true;

  switch (c as CoatingType) {
    case "ТЕХНО ОЗМ":
    case "АКЗ":
      return true;
    case "TAIKOR FP Epoxy":
    case "TAIKOR FP Graphite":
      return TAIKOR_EPOXY_GRAPHITE_R.has(r);
    case "TAIKOR FP Extra + TAIKOR FP Graphite":
      return TAIKOR_EXTRA_R.has(r);
    default:
      return true;
  }
}

/** Канонические типы, допустимые при текущем R. */
export function availableCoatingTypes(fireLimit?: string): CoatingType[] {
  return COATING_TYPES.filter((c) =>
    isCoatingAvailableForFireLimit(c, fireLimit)
  );
}

/**
 * Список для select.
 * Текущее значение (OCR / устаревшее) добавляем первым, даже если недоступно при R.
 */
export function coatingTypeChoices(
  current?: string,
  fireLimit?: string
): string[] {
  const available = availableCoatingTypes(fireLimit);
  const c = (current ?? "").trim();
  if (c && !available.includes(c as CoatingType)) {
    return [c, ...available];
  }
  return [...available];
}
