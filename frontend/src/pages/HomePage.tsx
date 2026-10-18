import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  Bot,
  FolderGit2,
  MessagesSquare,
  Network,
  BookOpen,
  Repeat2,
  Upload,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { CliHint } from '../components/CliHint'
import { CountUp } from '../components/home/CountUp'
import { MemoryGem } from '../components/home/MemoryGem'
import { Reveal } from '../components/home/Reveal'
import { cliHints } from '../lib/cliHints'

const FEATURES: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: FolderGit2,
    title: 'It remembers',
    body: 'Import your Claude, ChatGPT and Gemini exports. Every conversation becomes a Markdown file in a git vault that lives on your machine.',
  },
  {
    icon: Network,
    title: 'It organizes itself',
    body: 'PAM pulls out facts about you, groups conversations into projects and links related ideas, with no LLM calls and nothing to tag by hand.',
  },
  {
    icon: Repeat2,
    title: 'It carries over',
    body: 'Any model gets a small, token-budgeted briefing instead of your whole history. Switch models mid-chat and the thread keeps going.',
  },
]

const STEPS: { icon: LucideIcon; title: string; body: string; to: string; action: string; cli: string }[] = [
  {
    icon: Upload,
    title: 'Import your history',
    body: 'Export your chats from Claude, ChatGPT or Gemini and drop the file in. PAM extracts, indexes and clusters it in one pass.',
    to: '/import',
    action: 'Open Import',
    cli: cliHints.importRun(),
  },
  {
    icon: Network,
    title: 'Watch your memory take shape',
    body: 'Projects bloom in the graph. Open any node to read the conversation, fact or project note behind it.',
    to: '/graph',
    action: 'Open Graph',
    cli: cliHints.graphExport(),
  },
  {
    icon: Bot,
    title: 'Decide who sees what',
    body: 'Agents get a read scope, a write level and their own persona. A research agent never has to see your job search.',
    to: '/agents',
    action: 'Open Agents',
    cli: cliHints.agentCreate(),
  },
  {
    icon: MessagesSquare,
    title: 'Chat with any model',
    body: "Ask “where did I leave off?” and see exactly what was injected and how many tokens it saved. Or plug the same vault into Claude Desktop over MCP.",
    to: '/chat',
    action: 'Open Chat',
    cli: cliHints.chat(),
  },
]

function Stat({ value, label, note }: { value: ReactNode; label: string; note?: string }) {
  return (
    <div className="flex flex-col items-center gap-1.5 px-4 py-6 text-center">
      <div className="bg-gradient-to-b from-fg to-accent bg-clip-text text-[40px] font-semibold leading-none tracking-[-0.03em] tabular-nums text-transparent sm:text-[48px]">
        {value}
      </div>
      <div className="text-sm text-fg/90">{label}</div>
      {note && <div className="text-xs text-muted">{note}</div>}
    </div>
  )
}

/**
 * Home page: what PAM is, what it does, and how to use it.
 *
 * Behavior:
 *     A cinematic, centered landing page in the style of a product homepage:
 *     a glowing memory gem as the focal point, the PAM wordmark spelled out as
 *     Portable Agent Memory, a tagline with two calls
 *     to action, a band of numbers (vault counts are live from `GET /graph` and
 *     `GET /models`; the token saving is the demo vault's example), three
 *     feature statements, four steps that link to the matching pages with their
 *     CLI commands, and a closing call to action. Sections fade in as they
 *     scroll into view, the hero recedes as it scrolls away, numbers count up
 *     when they appear, and cards lift under the pointer.
 */
export default function HomePage() {
  const graph = useQuery({ queryKey: ['graph', 'default', false], queryFn: () => api.graph('default') })
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const count = (type: 'project' | 'episode') => graph.data?.nodes.filter((n) => n.type === type).length
  const live = (n: number | undefined) => (n === undefined ? '–' : <CountUp value={n} />)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col px-4 sm:px-8">
        <section className="hero-recede flex flex-col items-center pb-16 pt-12 text-center sm:pb-24 sm:pt-20" aria-labelledby="home-title">
          <Reveal>
            <MemoryGem size={220} />
          </Reveal>
          <Reveal delay={120} className="mt-12">
            <h1 id="home-title" className="flex flex-col items-center">
              <span className="display-type text-[108px] leading-[0.85] text-fg sm:text-[144px] lg:text-[168px]">
                PAM
              </span>
              <span className="mt-3 text-[15px] font-medium uppercase tracking-[0.32em] text-accent sm:text-[17px]">
                Portable Agent Memory
              </span>
            </h1>
            <p className="display-type mt-8 text-[42px] leading-[1.02] text-fg sm:text-[56px] lg:text-[68px]">
              Pick up where you left off.{' '}
              <span className="text-accent">With any AI.</span>
            </p>
          </Reveal>
          <Reveal delay={360} className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link to="/import" className="btn btn-primary min-h-[3rem] rounded-full px-6 text-[15px]">
              Import your history <ArrowRight size={17} strokeWidth={2} aria-hidden className="nudge" />
            </Link>
            <Link to="/chat" className="btn min-h-[3rem] rounded-full px-6 text-[15px]">
              See it remember
            </Link>
          </Reveal>
        </section>

        <Reveal as="section" className="panel grid grid-cols-1 divide-edge/[0.08] sm:grid-cols-3 sm:divide-x">
          <h2 className="sr-only">PAM in numbers</h2>
          <Stat value={live(count('episode'))} label="conversations remembered" />
          <Stat value={live(count('project'))} label="projects found for you" />
          <Stat value={live(models.data?.length)} label="models ready to chat" />
        </Reveal>

        <section className="py-24 text-center sm:py-32" aria-labelledby="home-problem">
          <Reveal>
            <h2 id="home-problem" className="mx-auto max-w-3xl text-[34px] font-semibold leading-[1.12] tracking-[-0.03em] sm:text-[48px]">
              Every AI starts from zero.
              <span className="text-muted"> You shouldn't have to.</span>
            </h2>
          </Reveal>
          <Reveal delay={120}>
            <p className="mx-auto mt-6 max-w-2xl text-[17px] leading-relaxed text-muted">
              You run out of messages, switch tools, or open a new chat, and the context is gone. PAM keeps it: your
              decisions, your projects, how you like to work. It hands each model exactly what it needs.
            </p>
          </Reveal>
          <ul className="mt-16 grid gap-4 text-left md:grid-cols-3">
            {FEATURES.map((f, i) => (
              <Reveal as="li" key={f.title} delay={i * 120} className="group card lift flex flex-col gap-4 p-6 sm:p-7">
                <span className="flex h-11 w-11 items-center justify-center rounded-[14px] transition-transform duration-500 ease-[var(--ease-spring)] group-hover:-rotate-6 group-hover:scale-110 bg-gradient-to-b from-accent/30 to-accent-strong/10 text-accent shadow-[inset_0_1px_0_rgb(var(--edge)/0.15)]">
                  <f.icon size={20} strokeWidth={1.75} aria-hidden />
                </span>
                <h3 className="text-[19px] font-semibold tracking-[-0.015em]">{f.title}</h3>
                <p className="text-[15px] leading-relaxed text-muted">{f.body}</p>
              </Reveal>
            ))}
          </ul>
        </section>

        <section className="pb-24 sm:pb-32" aria-labelledby="home-how">
          <Reveal className="text-center">
            <p className="eyebrow text-[13px]">How to use it</p>
            <h2 id="home-how" className="mt-3 text-[34px] font-semibold tracking-[-0.03em] sm:text-[44px]">
              Four steps. About two minutes.
            </h2>
          </Reveal>
          <ol className="mt-14 space-y-4">
            {STEPS.map((s, i) => (
              <Reveal as="li" key={s.title} delay={i * 80} className="group panel lift grid gap-5 p-6 sm:p-8 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center md:gap-8">
                <span className="flex h-14 w-14 items-center justify-center rounded-full transition-transform duration-500 ease-[var(--ease-spring)] group-hover:scale-110 bg-gradient-to-b from-accent to-accent-strong text-xl font-semibold text-accent-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.35),0_10px_30px_rgb(var(--accent-strong)/0.35)]">
                  {i + 1}
                </span>
                <div className="min-w-0 space-y-2">
                  <h3 className="flex items-center gap-2 text-[20px] font-semibold tracking-[-0.015em]">
                    <s.icon size={18} strokeWidth={1.75} className="text-accent" aria-hidden />
                    {s.title}
                  </h3>
                  <p className="max-w-2xl text-[15px] leading-relaxed text-muted">{s.body}</p>
                  <div className="max-w-xl pt-1">
                    <CliHint command={s.cli} />
                  </div>
                </div>
                <Link to={s.to} className="btn justify-self-start rounded-full px-5 md:justify-self-end">
                  {s.action} <ArrowRight size={16} strokeWidth={1.75} aria-hidden className="nudge" />
                </Link>
              </Reveal>
            ))}
          </ol>
        </section>

        <section className="flex flex-col items-center pb-20 text-center" aria-labelledby="home-cta">
          <Reveal>
            <MemoryGem size={120} />
          </Reveal>
          <Reveal delay={120} className="mt-12">
            <h2 id="home-cta" className="text-[40px] font-semibold leading-[1.05] tracking-[-0.035em] sm:text-[56px]">
              Stop starting over.
            </h2>
            <p className="mt-3 text-[15px] font-medium text-accent">Start with PAM.</p>
            <p className="mx-auto mt-4 max-w-md text-[17px] leading-relaxed text-muted">
              Bring your history in once. Every model you use after that already knows you.
            </p>
          </Reveal>
          <Reveal delay={240} className="mt-8 flex flex-wrap justify-center gap-3">
            <Link to="/import" className="btn btn-primary min-h-[3rem] rounded-full px-6 text-[15px]">
              Get started <ArrowRight size={17} strokeWidth={2} aria-hidden className="nudge" />
            </Link>
            <Link to="/guides" className="btn min-h-[3rem] rounded-full px-6 text-[15px]">
              <BookOpen size={16} strokeWidth={1.75} aria-hidden /> Read the guides
            </Link>
          </Reveal>
          <p className="mt-20 text-xs text-muted">PAM · Portable Agent Memory · your vault stays in ./vault</p>
        </section>
      </div>
    </div>
  )
}
