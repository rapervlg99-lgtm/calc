import { handbookKey, type ProfileCategory } from './ocrImport'

/**
 * Наименование группы профиля и ГОСТ сортамента для вида профиля — когда
 * пользователь вручную меняет марку на профиль другого вида (двутавр →
 * швеллер), строка ОГЗ должна называться по-новому: «Наименование профиля»
 * и «ГОСТ профиля» считаются от `name`/`gostProfile`, а не от марки.
 */
const GROUPS: Record<string, { name: string; gost: string }> = {
  balka: { name: 'Двутавры стальные горячекатаные с параллельными гранями полок', gost: 'ГОСТ Р 57837-2017' },
  shveller: { name: 'Швеллеры стальные горячекатаные', gost: 'ГОСТ 8240-97' },
  shveller_gnyt: { name: 'Швеллеры стальные гнутые равнополочные', gost: 'ГОСТ 8278-83' },
  ygolok: { name: 'Уголки стальные горячекатаные равнополочные', gost: 'ГОСТ 8509-93' },
  ygolok_gnyt: { name: 'Уголки стальные гнутые равнополочные', gost: 'ГОСТ 19771-93' },
  tryba_es_kvadr: { name: 'Трубы стальные квадратные', gost: 'ГОСТ 8639-82' },
  tryba_es_pr: { name: 'Трубы стальные прямоугольные', gost: 'ГОСТ 8645-68' },
  tryba_es_krug: { name: 'Трубы стальные электросварные прямошовные', gost: 'ГОСТ 10704-91' },
  tryba_vgp: { name: 'Трубы стальные водогазопроводные', gost: 'ГОСТ 3262-75' },
  tavr: { name: 'Тавры стальные', gost: 'СТО АСЧМ 20-93' }
}

const UNEQUAL_ANGLE = {
  ygolok: { name: 'Уголки стальные горячекатаные неравнополочные', gost: 'ГОСТ 8510-86' },
  ygolok_gnyt: { name: 'Уголки стальные гнутые неравнополочные', gost: 'ГОСТ 19772-93' }
}

/** Уголок с разными полками: в справочнике «150/100Х10», в спецификации «150х100х10». */
function isUnequalAngle(mark: string): boolean {
  const key = handbookKey(mark)
  if (key.includes('/')) return true
  const m = /^(\d+(?:\.\d+)?)Х(\d+(?:\.\d+)?)Х(\d+(?:\.\d+)?)$/.exec(key)
  return !!m && m[1] !== m[2]
}

/** Наименование группы и ГОСТ для вида профиля; null — вид неизвестен. */
export function groupForCategory(category: ProfileCategory | string, mark = ''): { name: string; gost: string } | null {
  if ((category === 'ygolok' || category === 'ygolok_gnyt') && isUnequalAngle(mark)) {
    return UNEQUAL_ANGLE[category]
  }
  return GROUPS[category] || null
}
