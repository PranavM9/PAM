import { useEffect, useRef, useState } from 'react'

/**
 * Number that counts up from zero the first time it scrolls into view.
 *
 * Behavior:
 *     Eases out over 1.4 s once at least half of it is visible, then holds the
 *     final value. Shows the final value straight away without
 *     `IntersectionObserver`. Counting changes only text, so it also runs with
 *     reduced motion. Assistive tech always reads the final value. If `value`
 *     changes later, the count restarts from zero.
 * Parameters:
 *     value: Final number.
 *     suffix: Text after the number, e.g. "%".
 */
export function CountUp({ value, suffix = '' }: { value: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [shown, setShown] = useState(0)

  useEffect(() => {
    const el = ref.current
    const still = typeof IntersectionObserver === 'undefined'
    let frame = 0
    const run = () => {
      const start = performance.now()
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / 1400)
        setShown(Math.round(value * (1 - Math.pow(1 - t, 4))))
        if (t < 1) frame = requestAnimationFrame(tick)
      }
      frame = requestAnimationFrame(tick)
    }
    if (!el || still) {
      frame = requestAnimationFrame(() => setShown(value))
      return () => cancelAnimationFrame(frame)
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        observer.disconnect()
        run()
      },
      { threshold: 0.5 },
    )
    observer.observe(el)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
    }
  }, [value])

  return (
    <span ref={ref}>
      <span className="sr-only">
        {value.toLocaleString()}
        {suffix}
      </span>
      <span aria-hidden>
        {shown.toLocaleString()}
        {suffix}
      </span>
    </span>
  )
}
