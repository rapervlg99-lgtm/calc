import { describe, expect, it } from 'vitest'
import type { RollMark } from '../types/api'
import { assortmentLabel, LEGACY_STANDARD, rollsForShape, rollsForStandard, sourceRollsForGost, standardOptions } from './rollCatalog'
import { mapPrefillPayload } from './prefillMapper'
import { resolveMassPerMeter } from './ocrImport'

const legacy: RollMark = { id:'old',shape:'I-beam_sm',label:'10Б1',dims:{h:100,b:55,s:4.1,t:5.7} }
const current: RollMark = { ...legacy,id:'new',standard:'ГОСТ 35087-2024',standardLabel:'ГОСТ 35087-2024 — действующий',massPerMeter:8.1012,familyLabel:'Балочные нормальные (Б)' }
const archived: RollMark = { ...current,id:'archive',standard:'ГОСТ 26020-83',standardLabel:'ГОСТ 26020-83 — недействующий' }
const bent: RollMark = {id:'bend',shape:'channel_bent',label:'25×26×2',dims:{h:25,b:26,s:2,t:2,R:3},standard:'ГОСТ 8278-83',massPerMeter:1.09115}
const unequal: RollMark = {...bent,id:'unequal',shape:'channel_unequal',standard:'ГОСТ 8281-80',label:'32×22×12×3',dims:{h:32,b:22,b1:12,s:3,t:3,R:5},massPerMeter:1.27955}
const all = [legacy,current,archived,bent,unequal]

describe('standard-qualified assortment', () => {
  it('keeps current/archived standards and legacy distinct', () => {
    expect(standardOptions(rollsForShape(all,'I-beam_sm')).map(o=>o.value)).toEqual(['ГОСТ 35087-2024','ГОСТ 26020-83',LEGACY_STANDARD])
    expect(rollsForStandard(all,'ГОСТ 26020-83')).toEqual([archived])
    expect(assortmentLabel(current)).toContain('Балочные нормальные')
  })
  it('does not substitute rolled or equal channels for unequal ones', () => {
    expect(rollsForShape(all,'channel_unequal')).toEqual([unequal])
    expect(rollsForShape(all,'channel_bent')).toEqual([bent])
  })
  it('recognizes ГОСТ text without spaces and different dash characters', () => {
    expect(sourceRollsForGost(all,'ГОСТ35087–2024')).toEqual([current])
  })
  it('prefill follows the specification standard instead of first same-name mark', () => {
    const payload = {version:'1',jobId:'test',sheet:{areaM2:0},items:[{profileMark:'10Б1',gostProfile:'ГОСТ 26020-83',lengthM:6,heatingSides:'4',fireLimit:'R60',bearingType:'несущая',coatingType:'ТЕХНО ОЗМ'}]}
    expect(mapPrefillPayload(payload,all).elements[0].element.rollId).toBe('archive')
  })
  it('uses the table mass for a new standard and avoids guessing a bending table', () => {
    expect(resolveMassPerMeter('32х22х12х3','shveller_gnyt','Швеллер',undefined,all,undefined,'ГОСТ 8281-80').mpm).toBe(1.27955)
    const otherTable={...bent,id:'bend2',dims:{...bent.dims,R:5},massPerMeter:1.0676}
    expect(resolveMassPerMeter('25х26х2','shveller_gnyt','Швеллер',undefined,[bent,otherTable],undefined,'ГОСТ 8278-83').mpm).toBeNull()
    expect(resolveMassPerMeter('32х22х12х3','shveller_gnyt','Швеллер',undefined,all,undefined,'ГОСТ 8278-83').mpm).toBeNull()
  })
})
