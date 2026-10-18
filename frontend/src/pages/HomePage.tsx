import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MemoryGem } from '../components/home/MemoryGem'
import { Reveal } from '../components/home/Reveal'

/**
 * Landing page: the gem, the PAM wordmark and two buttons.
 *
 * Behavior:
 *     Shows nothing else, so the way into the app is one click. "Import" opens
 *     the import wizard and "Chat" opens the chat page.
 */
export default function HomePage() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex min-h-full max-w-5xl flex-col justify-center px-4 sm:px-8">
        <section className="hero-recede flex flex-col items-center py-12 text-center" aria-labelledby="home-title">
          <Reveal>
            <MemoryGem size={220} />
          </Reveal>
          <Reveal delay={120} className="mt-12">
            <h1 id="home-title" className="display-type text-[108px] leading-[0.85] text-fg sm:text-[144px] lg:text-[168px]">
              PAM
            </h1>
          </Reveal>
          <Reveal delay={240} className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link to="/import" className="btn btn-primary min-h-[3rem] rounded-full px-6 text-[15px]">
              Import <ArrowRight size={17} strokeWidth={2} aria-hidden className="nudge" />
            </Link>
            <Link to="/chat" className="btn min-h-[3rem] rounded-full px-6 text-[15px]">
              Chat
            </Link>
          </Reveal>
        </section>
      </div>
    </div>
  )
}
