import { describe, expect, it } from 'vitest'
import { shareTokenFromUrl, urlWithShareToken, urlWithoutShareToken } from './share'

const TOKEN = 'n1792668187385'

describe('ссылки обмена', () => {
  it('достаёт токен из адреса вида ?n1792668187385', () => {
    expect(shareTokenFromUrl(`https://calc.tn.ru/ozm/?${TOKEN}`)).toBe(TOKEN)
  })

  it('поддерживает запасной вид ?n=…', () => {
    expect(shareTokenFromUrl(`https://calc.tn.ru/ozm/?n=${TOKEN}`)).toBe(TOKEN)
  })

  it('возвращает null, если токена нет или он чужой', () => {
    expect(shareTokenFromUrl('https://calc.tn.ru/ozm/')).toBeNull()
    expect(shareTokenFromUrl('https://calc.tn.ru/ozm/?utm=1')).toBeNull()
    expect(shareTokenFromUrl('https://calc.tn.ru/ozm/?n123')).toBeNull()
    expect(shareTokenFromUrl('https://calc.tn.ru/ozm/?nabcdefghijklm')).toBeNull()
  })

  it('собирает адрес с токеном, сохраняя путь и якорь', () => {
    expect(urlWithShareToken(`https://calc.tn.ru/ozm/?old=1`, TOKEN)).toBe(`https://calc.tn.ru/ozm/?${TOKEN}`)
    expect(urlWithShareToken(`https://calc.tn.ru/ozm/?${TOKEN}#res`, TOKEN)).toBe(`https://calc.tn.ru/ozm/?${TOKEN}#res`)
  })

  it('не подставляет мусор вместо токена', () => {
    expect(urlWithShareToken(`https://calc.tn.ru/ozm/?${TOKEN}`, 'nope')).toBe('https://calc.tn.ru/ozm/')
  })

  it('умеет убрать токен из адреса', () => {
    expect(urlWithoutShareToken(`https://calc.tn.ru/ozm/?${TOKEN}`)).toBe('https://calc.tn.ru/ozm/')
  })
})
