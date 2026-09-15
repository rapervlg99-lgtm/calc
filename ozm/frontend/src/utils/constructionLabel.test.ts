import { describe, expect, it } from 'vitest'
import { constructionLabel, elementDisplayName } from './constructionLabel'

describe('constructionLabel', () => {
  it('maps known constructions', () => {
    expect(constructionLabel('Балки')).toBe('балка')
    expect(constructionLabel('Ригели')).toBe('ригели')
    expect(constructionLabel('Колонны/Стойки')).toBe('колонна / стойка')
  })

  it('builds element display name', () => {
    expect(elementDisplayName('Балки', '40Б1')).toBe('балка 40Б1')
    expect(elementDisplayName('Ригели', '23Б1')).toBe('ригели 23Б1')
    expect(elementDisplayName('', '40Б1')).toBe('40Б1')
    expect(elementDisplayName('', '')).toBe('Элемент')
  })
})
