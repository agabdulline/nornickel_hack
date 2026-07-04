import { useEffect } from 'react'

/** Мост «ассистент → экран»: клик по ссылке в чате просит экран подсветить
 *  цель (правило/ячейку/гипотезу). Экран помечает элементы атрибутом
 *  data-hl="type:id" и вызывает useChatHighlight(ready) после загрузки данных. */
export interface HighlightTarget {
  type: 'rule' | 'cell' | 'hypothesis'
  id: string
}

const EVT = 'fh-highlight'
const FLASH_MS = 5000

let pending: HighlightTarget | null = null

export function requestHighlight(t: HighlightTarget) {
  pending = t
  window.dispatchEvent(new CustomEvent(EVT))
}

/** Посмотреть цель, не забирая её (экран может, например, переключить Ni/Cu). */
export function peekPending(): HighlightTarget | null {
  return pending
}

function flash(el: Element) {
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.remove('flash-highlight')
  void (el as HTMLElement).offsetWidth   // рестарт CSS-анимации
  el.classList.add('flash-highlight')
  window.setTimeout(() => el.classList.remove('flash-highlight'), FLASH_MS)
}

function consumePending(): boolean {
  const t = pending
  if (!t) return true   // нечего подсвечивать — считаем выполненным
  const val = `${t.type}:${t.id}`.replace(/"/g, '\\"')
  const el = document.querySelector(`[data-hl="${val}"]`)
  if (!el) return false
  pending = null
  flash(el)
  return true
}

/** Подсветить цель из чата, когда данные экрана готовы. Ретраи покрывают
 *  дорендеривание после навигации/переключения Ni-Cu. `deps` — что ещё
 *  должно триггерить новую попытку (например, выбранный элемент). */
export function useChatHighlight(ready: boolean, deps: unknown[] = []) {
  useEffect(() => {
    if (!ready) return
    let cancelled = false
    const tryConsume = (attempt = 0) => {
      if (cancelled || consumePending() || attempt >= 6) return
      window.setTimeout(() => tryConsume(attempt + 1), 250)
    }
    const raf = requestAnimationFrame(() => tryConsume())
    const onEvt = () => tryConsume()
    window.addEventListener(EVT, onEvt)
    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
      window.removeEventListener(EVT, onEvt)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, ...deps])
}

export const HIGHLIGHT_EVENT = EVT

/** Ассистент выполнил действие (принял гипотезу, переранжировал, построил
 *  роадмап) — открытые экраны перезагружают данные по этому событию. */
export const DATA_CHANGED_EVENT = 'fh-data-changed'

export function notifyDataChanged() {
  window.dispatchEvent(new CustomEvent(DATA_CHANGED_EVENT))
}
