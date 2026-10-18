import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  FolderTree,
  MessagesSquare,
  Network,
  Search,
  Sparkles,
  Upload,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { MOCK, api } from '../api/client'

const ROUTES: { to: string; label: string; icon: LucideIcon }[] = [
  { to: '/import', label: 'Import', icon: Upload },
  { to: '/graph', label: 'Graph', icon: Network },
  { to: '/vault', label: 'Vault', icon: FolderTree },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/chat', label: 'Chat', icon: MessagesSquare },
  { to: '/guides', label: 'Guides', icon: BookOpen },
]

/**
 * App shell: floating glass sidebar with the seven pages and a backend status card.
 *
 * Behavior:
 *     Polls `GET /health` every 15 s and shows whether the vault and index are
 *     reachable. A "Mock data" note marks `VITE_PAM_MOCK=1` builds. Below the
 *     `lg` breakpoint the sidebar becomes a horizontal top bar.
 */
export function Layout() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const status = health.isError ? 'Backend offline' : !health.data ? 'Checking backend…' : health.data.index_ok ? 'Vault ready' : 'Index stale'
  const dot = health.isError ? 'bg-bad' : health.data?.index_ok ? 'bg-ok' : 'bg-warn'
  return (
    <div className="flex h-full flex-col gap-3 p-3 lg:flex-row lg:gap-4 lg:p-4">
      <nav
        aria-label="Main"
        className="panel flex shrink-0 items-center gap-2 overflow-x-auto px-3 py-2 lg:w-56 lg:flex-col lg:items-stretch lg:gap-0 lg:overflow-visible lg:px-3 lg:py-5"
      >
        <div className="flex shrink-0 items-center gap-2.5 px-2 lg:mb-8">
          <Sparkles size={22} className="text-accent" aria-hidden />
          <div className="leading-tight">
            <div className="text-[17px] font-semibold tracking-tight">PAM</div>
            <div className="hidden text-xs text-muted lg:block">Portable Agent Memory</div>
          </div>
        </div>
        <ul className="flex flex-1 gap-1 lg:flex-col">
          {ROUTES.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  `flex min-h-[2.75rem] items-center gap-3 whitespace-nowrap rounded-[14px] px-3 text-sm transition duration-200 ease-out ${
                    isActive
                      ? 'bg-gradient-to-r from-accent/25 to-accent/10 font-medium text-fg shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]'
                      : 'text-muted hover:bg-fg/[0.06] hover:text-fg'
                  }`
                }
              >
                <Icon size={18} strokeWidth={1.75} aria-hidden />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
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
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
