/**
 * Ссылки обмена расчётами.
 *
 * Формат как на calc.tn.ru: `?n1792668187385` — токен идёт прямо в строке
 * запроса, без имени параметра. Разбираем и этот вид, и запасной `?n=…`,
 * чтобы ссылками можно было делиться в любом виде.
 */

/** Токен: «n» + 13–17 цифр (миллисекунды, при коллизии — с хвостом). */
export const SHARE_TOKEN_RE = /^n\d{13,17}$/

/** Достаёт токен из адреса страницы; null — ссылка без токена. */
export function shareTokenFromUrl(href: string): string | null {
  let url: URL
  try {
    url = new URL(href, 'http://localhost')
  } catch {
    return null
  }
  const search = url.search.replace(/^\?/, '')
  if (SHARE_TOKEN_RE.test(search)) return search
  const named = url.searchParams.get('n') || ''
  return SHARE_TOKEN_RE.test(named) ? named : null
}

/** Собирает адрес с токеном, сохраняя путь и якорь (без «?n=» — как в эталоне). */
export function urlWithShareToken(href: string, token: string): string {
  const url = new URL(href, 'http://localhost')
  url.search = SHARE_TOKEN_RE.test(token) ? token : ''
  return url.toString()
}

/** Возвращает адрес без токена (для чистого старта, если ссылка битая). */
export function urlWithoutShareToken(href: string): string {
  const url = new URL(href, 'http://localhost')
  url.search = ''
  return url.toString()
}
