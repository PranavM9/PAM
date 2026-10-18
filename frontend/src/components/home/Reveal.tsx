import { useEffect, useRef, useState, type ReactNode } from 'react'

/**
 * Fade a block up into view the first time it scrolls on screen.
 *
 * Behavior:
 *     Uses an `IntersectionObserver` on the nearest scroll container; once
 *     shown, the block stays shown. Without observer support, or with reduced
 *     motion, the content is visible immediately (see `.reveal` in index.css).
 * Parameters:
 *     children: Content to reveal.
 *     delay: Animation delay in milliseconds, for staggering siblings.
 *     className: Classes for the wrapper.
 *     as: Wrapper element.
 */
export function Reveal({
  children,
  delay = 0,
  className = '',
  as: Tag = 'div',
}: {
  children: ReactNode
  delay?: number
  className?: string
  as?: 'div' | 'section' | 'li'
}) {
  const ref = useRef<HTMLElement>(null)
  const [shown, setShown] = useState(() => typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    const el = ref.current
    if (!el || shown) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true)
          observer.disconnect()
        }
      },
      { threshold: 0.15 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [shown])

  return (
    <Tag
      ref={ref as never}
      data-shown={shown}
      className={`reveal ${className}`}
      style={{ animationDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  )
}
