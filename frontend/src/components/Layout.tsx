import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  FolderTree,
  Home,
  MessagesSquare,
  Network,
  Search,
  Sparkles,
  Upload,
  type LucideIcon,
} from 'lucide-react'
import { useLayoutEffect, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { MOCK, api } from '../api/client'
import { ResizeHandle } from './Resizable'
import { usePaneSize } from '../lib/usePaneSize'

const ROUTES: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/import', label: 'Import', icon: Upload },
  { to: '/graph', label: 'Graph', icon: Network },
  { to: '/vault', label: 'Vault', icon: FolderTree },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/chat', label: 'Chat', icon: MessagesSquare },
  { to: '/guides', label: 'Guides', icon: BookOpen },
]

/**
 * App shell: floating glass sidebar with the home page, the seven app pages and a backend status card.
 *
 * Behavior:
 *     Polls `GET /health` every 15 s and shows whether the vault and index are
 *     reachable. A "Mock data" note marks `VITE_PAM_MOCK=1` builds. Below the
 *     `lg` breakpoint the sidebar becomes a horizontal top bar; from `lg` up its
 *     width can be dragged between 196 and 320 px. A highlight pill glides to
 *     the active link, and each page change replays the page entrance
 *     (`.page-enter` in index.css).
 */
export function Layout() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const status = health.isError ? 'Backend offline' : !health.data ? 'Checking backend…' : health.data.index_ok ? 'Vault ready' : 'Index stale'
  const sidebar = usePaneSize({ id: 'sidebar', initial: 224, min: 196, max: 320 })
  const dot = health.isError ? 'bg-bad' : health.data?.index_ok ? 'bg-ok' : 'bg-warn'
  const { pathname } = useLocation()
  const links = useRef<HTMLDivElement>(null)
  const pill = useRef<HTMLSpanElement>(null)

  // Move the pill onto the active link, and follow it when the sidebar is resized.
  useLayoutEffect(() => {
    const box = links.current
    const el = pill.current
    if (!box || !el) return
    const place = () => {
      const active = box.querySelector<HTMLElement>('a[aria-current="page"]')
      el.style.opacity = active ? '1' : '0'
      if (!active) return
      el.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`
      el.style.width = `${active.offsetWidth}px`
      el.style.height = `${active.offsetHeight}px`
    }
    place()
    // The first placement snaps; later moves animate.
    requestAnimationFrame(() => (el.dataset.ready = 'true'))
    const observer = new ResizeObserver(place)
    observer.observe(box)
    return () => observer.disconnect()
  }, [pathname])
  return (
    <div className="flex h-full flex-col gap-3 p-3 lg:flex-row lg:gap-0 lg:p-4">
      <nav
        aria-label="Main"
        style={sidebar.style}
        className="panel flex shrink-0 items-center gap-2 overflow-x-auto px-3 py-2 lg:w-[var(--pane-w)] lg:flex-col lg:items-stretch lg:gap-0 lg:overflow-visible lg:px-3 lg:py-5"
      >
        <div className="flex shrink-0 items-center gap-2.5 px-2 lg:mb-8">
          <Sparkles size={22} className="text-accent" aria-hidden />
          <div className="leading-tight">
            <div className="text-[17px] font-semibold tracking-tight">PAM</div>
            <div className="hidden text-xs text-muted lg:block">Portable Agent Memory</div>
          </div>
        </div>
        <div ref={links} className="relative flex-1">
          <span
            ref={pill}
            aria-hidden
            className="pointer-events-none absolute left-0 top-0 rounded-[14px] bg-gradient-to-r from-accent/25 to-accent/10 opacity-0 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] data-[ready=true]:transition-[transform,width,height,opacity] data-[ready=true]:duration-500 data-[ready=true]:ease-[var(--ease-spring)]"
          />
          <ul className="relative flex gap-1 lg:flex-col">
            {ROUTES.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `press group flex min-h-[2.75rem] items-center gap-3 whitespace-nowrap rounded-[14px] px-3 text-sm ${
                      isActive ? 'font-medium text-fg' : 'text-muted hover:bg-fg/[0.06] hover:text-fg'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        size={18}
                        strokeWidth={1.75}
                        aria-hidden
                        className={`transition duration-300 ease-[var(--ease-spring)] group-hover:-translate-y-px group-hover:scale-110 ${isActive ? 'text-accent' : ''}`}
                      />
                      {label}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
        <div className="well hidden space-y-2 p-3.5 text-xs lg:block">
          <div className="flex items-center gap-2 text-fg/90" title={health.data?.vault}>
            <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
            {status}
          </div>
          {health.data?.vault && <div className="truncate font-mono text-[11px] text-muted">{health.data.vault}</div>}
          {MOCK && <div className="text-warn">Mock data: demo responses, no backend</div>}
        </div>
        <div className="flex shrink-0 items-center gap-2 px-2 text-xs text-muted lg:hidden" title={status}>
          <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
          {MOCK && <span className="text-warn">mock</span>}
        </div>
      </nav>
      <ResizeHandle pane={sidebar} side="before" label="Resize sidebar" />
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <div key={pathname} className="page-enter flex min-h-0 min-w-0 flex-1 flex-col">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
