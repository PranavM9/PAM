import { useState } from 'react'

/**
 * Luminous lavender orb, the home page's single focal point.
 *
 * Behavior:
 *     Built from CSS only: a soft outer bloom, an iridescent conic body that
 *     rotates very slowly, an inner glass sphere with a specular highlight, and
 *     a faint orbit ring, a gentle hover response, and a click-activated glow.
 *     The whole gem floats a few pixels; motion stops with reduced motion.
 * Parameters:
 *     size: Diameter in pixels.
 */
export function MemoryGem({ size = 280 }: { size?: number }) {
  const [awake, setAwake] = useState(false)
  return (
    <button
      type="button"
      aria-label={awake ? 'PAM memory orb is glowing. Click to settle it.' : 'Wake the PAM memory orb'}
      aria-pressed={awake}
      onClick={() => setAwake((value) => !value)}
      className={`group relative mx-auto block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-4 focus-visible:ring-offset-bg motion-safe:animate-[gem-float_9s_ease-in-out_infinite] ${awake ? 'gem-awake' : ''}`}
      style={{ width: size, height: size }}
    >
      <span className="sr-only">Click to wake the memory orb.</span>
      <div aria-hidden className="absolute -inset-[45%] rounded-full bg-[radial-gradient(circle,rgb(var(--accent)/0.28),rgb(var(--accent-strong)/0.08)_40%,transparent_68%)] blur-2xl transition duration-700 group-hover:opacity-100" />
      <div aria-hidden className="absolute inset-0 overflow-hidden rounded-full shadow-[0_30px_90px_rgb(var(--accent-strong)/0.32)] transition duration-700 ease-[var(--ease-spring)] group-hover:scale-105 group-hover:shadow-[0_30px_110px_rgb(var(--accent-strong)/0.48)]">
        <div className="absolute -inset-1/4 bg-[conic-gradient(from_210deg,#5b3fd0,#b8a9ff,#f0abfc,#7dd3fc,#8b6cff,#4c2d79,#5b3fd0)] opacity-90 blur-xl motion-safe:animate-[gem-spin_28s_linear_infinite]" />
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_32%_28%,rgba(255,255,255,0.75),rgba(255,255,255,0.12)_22%,transparent_46%)]" />
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_70%_78%,rgba(9,7,17,0.55),transparent_55%)]" />
        <div className="absolute inset-[9%] rounded-full border border-white/25 bg-[radial-gradient(circle_at_40%_35%,rgba(255,255,255,0.18),rgba(255,255,255,0.02)_60%)] backdrop-blur-[2px]" />
      </div>
      <div aria-hidden className="absolute -inset-[14%] rounded-full border border-edge/[0.12] transition duration-700 group-hover:rotate-12 group-hover:border-accent/30 [transform:rotateX(68deg)]" />
      <span aria-hidden className="absolute inset-0 grid place-items-center text-[34px] text-white/90 opacity-0 transition duration-500 group-hover:opacity-100 display-type">PAM</span>
      <span aria-hidden className="gem-pulse pointer-events-none absolute inset-[-3%] rounded-full border border-white/0" />
    </button>
  )
}
