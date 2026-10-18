const PRESSABLE = '.btn, .btn-ghost, .icon-btn'

/**
 * Add a soft ripple to every button press, starting where the pointer went down.
 *
 * Behavior:
 *     One delegated `pointerdown` listener on the document covers every
 *     `.btn`, `.btn-ghost` and `.icon-btn`, including ones mounted later.
 *     The ripple is a decorative span sized to cover the button; it removes
 *     itself when its animation ends. Disabled buttons get no ripple. It stays
 *     on with reduced motion: it expands in place without moving anything.
 *     Safe to call more than once.
 */
export function installPressFeedback(): void {
  if (typeof document === 'undefined' || document.documentElement.dataset.pressFeedback) return
  document.documentElement.dataset.pressFeedback = 'on'

  document.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return
    const target = (event.target as Element | null)?.closest<HTMLElement>(PRESSABLE)
    if (!target || target.matches(':disabled, [aria-disabled="true"]')) return
    const box = target.getBoundingClientRect()
    const size = Math.hypot(box.width, box.height) * 2
    const ripple = document.createElement('span')
    ripple.className = 'press-ripple'
    ripple.setAttribute('aria-hidden', 'true')
    ripple.style.width = ripple.style.height = `${size}px`
    ripple.style.left = `${event.clientX - box.left}px`
    ripple.style.top = `${event.clientY - box.top}px`
    ripple.addEventListener('animationend', () => ripple.remove(), { once: true })
    target.appendChild(ripple)
  })
}
