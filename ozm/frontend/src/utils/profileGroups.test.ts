import { describe, expect, it } from 'vitest'
import { profileCategory, profileFamilyLabel } from './ocrImport'
import { groupForCategory } from './profileGroups'

describe('groupForCategory', () => {
  it('даёт наименование группы и ГОСТ по виду профиля', () => {
    expect(groupForCategory('shveller', '16П')).toEqual({ name: 'Швеллеры стальные горячекатаные', gost: 'ГОСТ 8240-97' })
    expect(groupForCategory('balka', '35Б2')?.name).toMatch(/^Двутавры/)
    expect(groupForCategory('tryba_es_krug', '140Х5')?.gost).toBe('ГОСТ 10704-91')
    expect(groupForCategory('', '')).toBeNull()
    expect(groupForCategory('unknown', 'x')).toBeNull()
  })

  it('различает равнополочные и неравнополочные уголки по марке', () => {
    expect(groupForCategory('ygolok', '100Х100Х8')?.gost).toBe('ГОСТ 8509-93')
    expect(groupForCategory('ygolok', '150/100Х10')?.name).toMatch(/неравнополочные/)
    expect(groupForCategory('ygolok', '160х100х9')?.gost).toBe('ГОСТ 8510-86')
    expect(groupForCategory('ygolok_gnyt', '80х40х4')?.gost).toBe('ГОСТ 19772-93')
  })

  it('новое наименование даёт ту же категорию и подпись вида в таблице', () => {
    for (const cat of ['balka', 'shveller', 'ygolok', 'tryba_es_kvadr', 'tryba_es_pr', 'tryba_es_krug', 'tryba_vgp', 'tavr'] as const) {
      const g = groupForCategory(cat, cat === 'tryba_es_pr' ? '100Х50Х4' : '')!
      expect(profileCategory(g.name, g.gost, '')).toBe(cat)
    }
    const g = groupForCategory('shveller', '16П')!
    expect(profileFamilyLabel({ name: g.name, gostProfile: g.gost, profileRaw: 'I40Б1', profileMark: '16П', isSheet: false })).toBe('Швеллер')
  })
})
