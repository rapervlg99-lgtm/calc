import type { Job, OgzRow, PrefillPayload } from "../types/ogz";
import { profileCategory, SHAPES_BY_CATEGORY } from "../utils/ocrImport";

/** Формы сечения, допустимые для строки, — по наименованию группы, ГОСТ и марке. */
export function shapesForRow(r: OgzRow): string[] | undefined {
  const cat = profileCategory(r.name, r.gostProfile, r.profileRaw || r.profileMark);
  return cat ? SHAPES_BY_CATEGORY[cat] : undefined;
}

export const DEMO_JOB_ID = "demo";

function row(over: Partial<OgzRow>): OgzRow {
  return {
    id: 1,
    name: "Балка",
    profileMark: "35Б2",
    profileRaw: "35Б2",
    gostProfile: "ГОСТ 26020-83",
    steelGrade: "С255",
    ppNumber: "1",
    construction: "Балки",
    mass: 100,
    massUnit: "kg",
    massPerMeter: 49.6,
    massSource: "23met",
    sourceUrl: "",
    isSheet: false,
    lengthM: 20,
    areaM2: 0,
    classification: "учитывается",
    status: "Посчитано",
    heatingSides: "4",
    fireLimit: "",
    bearingType: "",
    coatingType: "",
    ...over
  };
}

/** Свежая копия демо-задания (мутабельная для patch/confirm в памяти). */
export function createDemoJob(): Job {
  const now = new Date().toISOString();
  return {
    id: DEMO_JOB_ID,
    status: "ready",
    confirmed: false,
    createdAt: now,
    updatedAt: now,
    profileRows: [
      // Полностью готовая строка → уходит в калькулятор.
      row({
        id: 1,
        name: "Балка Б-1",
        profileMark: "40Б1",
        profileRaw: "I40Б1",
        construction: "Балки",
        ppNumber: "1",
        lengthM: 14.8,
        massPerMeter: 56.6,
        mass: 837.68,
        status: "Посчитано",
        heatingSides: "4",
        fireLimit: "R90",
        bearingType: "Несущая",
        coatingType: "TAIKOR FP Graphite"
      }),
      // Другой R и 3-сторонний обогрев.
      row({
        id: 2,
        name: "Балка Б-2",
        profileMark: "26Б1",
        profileRaw: "I26Б1",
        construction: "Балки",
        ppNumber: "2",
        lengthM: 11.2,
        massPerMeter: 28.0,
        mass: 313.6,
        status: "Посчитано",
        heatingSides: "снизу, слева, справа",
        fireLimit: "R60",
        bearingType: "Несущая",
        coatingType: "ТЕХНО ОЗМ"
      }),
      // Высокий R → Extra + Graphite.
      row({
        id: 3,
        name: "Ригель Р-1",
        profileMark: "23Б1",
        profileRaw: "I23Б1",
        construction: "Ригели",
        ppNumber: "3",
        lengthM: 8.4,
        massPerMeter: 25.8,
        mass: 216.72,
        status: "Посчитано",
        heatingSides: "4",
        fireLimit: "R120",
        bearingType: "Несущая",
        coatingType: "TAIKOR FP Extra + TAIKOR FP Graphite"
      }),
      // Посчитано, но без R — в калькулятор не уйдёт.
      row({
        id: 4,
        name: "Колонна К-1",
        profileMark: "30Б1",
        profileRaw: "I30Б1",
        construction: "Колонны/Стойки",
        ppNumber: "4",
        lengthM: 6.5,
        massPerMeter: 32.0,
        mass: 208.0,
        status: "Посчитано",
        heatingSides: "4"
      })
    ],
    sheetRows: []
  };
}

export function demoPrefill(job: Job): PrefillPayload {
  return {
    version: "1",
    jobId: job.id,
    items: job.profileRows
      .filter(
        (r) =>
          (r.status === "Посчитано" || r.status === "Требует проверки") &&
          r.lengthM > 0 &&
          r.fireLimit.trim() !== ""
      )
      .map((r) => ({
        profileMark: r.profileMark,
        construction: r.construction,
        lengthM: r.lengthM,
        heatingSides: r.heatingSides,
        fireLimit: r.fireLimit,
        bearingType: r.bearingType,
        coatingType: r.coatingType,
        shapes: shapesForRow(r)
      })),
    sheet: {
      areaM2: job.sheetRows.reduce((sum, r) => sum + r.areaM2, 0)
    }
  };
}
