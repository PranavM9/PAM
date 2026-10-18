/**
 * Luminous lavender orb, the home page's single focal point.
 *
 * Behavior:
 *     Built from CSS only: a soft outer bloom, an iridescent conic body that
 *     rotates very slowly, an inner glass sphere with a specular highlight, and
 *     a faint orbit ring. The whole gem floats a few pixels. Decorative only,
 *     hidden from assistive technology; motion stops with reduced motion.
 * Parameters:
 *     size: Diameter in pixels.
 */
export function MemoryGem({ size = 280 }: { size?: number }) {
  return (
    <div
      aria-hidden
      className="group relative mx-auto motion-safe:animate-[gem-float_9s_ease-in-out_infinite]"
      style={{ width: size, height: size }}
    >
      <div className="absolute -inset-[45%] rounded-full bg-[radial-gradient(circle,rgb(var(--accent)/0.35),rgb(var(--accent-strong)/0.12)_40%,transparent_68%)] blur-2xl" />
      <div className="absolute inset-0 overflow-hidden rounded-full shadow-[0_30px_90px_rgb(var(--accent-strong)/0.45)] transition duration-700 ease-[var(--ease-spring)] group-hover:scale-105 group-hover:shadow-[0_30px_110px_rgb(var(--accent-strong)/0.65)]">
        <div className="absolute -inset-1/4 bg-[conic-gradient(from_210deg,#5b3fd0,#b8a9ff,#f0abfc,#7dd3fc,#8b6cff,#4c2d79,#5b3fd0)] opacity-90 blur-xl motion-safe:animate-[gem-spin_28s_linear_infinite]" />
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_32%_28%,rgba(255,255,255,0.75),rgba(255,255,255,0.12)_22%,transparent_46%)]" />
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_70%_78%,rgba(9,7,17,0.55),transparent_55%)]" />
        <div className="absolute inset-[9%] rounded-full border border-white/25 bg-[radial-gradient(circle_at_40%_35%,rgba(255,255,255,0.18),rgba(255,255,255,0.02)_60%)] backdrop-blur-[2px]" />
      </div>
      <div className="absolute -inset-[14%] rounded-full border border-edge/[0.12] [transform:rotateX(68deg)]" />
    </div>
  )
}
