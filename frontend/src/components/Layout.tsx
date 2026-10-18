import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  FolderTree,
  MessagesSquare,
  Network,
  Search,
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
 * App shell: sidebar navigation with the seven pages and a backend status line.
 *
 * Behavior:
 *     Polls `GET /health` every 15 s and shows whether the vault and index are
 *     reachable. A "mock" badge marks `VITE_PAM_MOCK=1` builds.
 */
export function Layout() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const status = health.isError ? 'offline' : !health.data ? 'checking…' : health.data.index_ok ? 'ready' : 'index stale'
  const dot = health.isError ? 'bg-bad' : health.data?.index_ok ? 'bg-ok' : 'bg-warn'
  return (
    <div className="flex h-full">
      <nav aria-label="Main" className="flex w-52 shrink-0 flex-col border-r border-line bg-panel">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-accent font-bold text-accent-fg">P</div>
          <div className="leading-tight">
            <div className="font-semibold">PAM</div>
            <div className="text-[11px] text-muted">Portable Agent Memory</div>
          </div>
        </div>
        <ul className="flex-1 space-y-0.5 px-2">
          {ROUTES.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                    isActive ? 'bg-accent/15 font-medium text-fg' : 'text-muted hover:bg-raised hover:text-fg'
                  }`
                }
              >
                <Icon size={16} aria-hidden />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="space-y-1 border-t border-line px-4 py-3 text-xs text-muted">
          <div className="flex items-center gap-2" title={health.data?.vault}>
            <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
            backend {status}
          </div>
          {MOCK && <span className="badge border-warn/50 text-warn">mock data</span>}
        </div>
      </nav>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
