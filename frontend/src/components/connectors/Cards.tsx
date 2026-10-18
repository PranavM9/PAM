import { ExternalLink, Info } from 'lucide-react'
import type { ReactNode } from 'react'
import type { CardPrice, ConnectorCard } from '../../types/generated'
import { ConnectorChart } from './ConnectorChart'

/** Badge every synthetic card carries; it is styled apart from the other badges. */
const SYNTHETIC_BADGE = 'Synthetic demo data'
const PRODUCT_FIELDS = 3
const PLAN_FIELDS = 4
const ROW_FROM = 3

/** Format dollars like `$29.17` or `$350` (`$1,024` with thousands). */
function money(amount: number): string {
  const digits = Number.isInteger(amount) ? 0 : 2
  return `$${amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

/**
 * Render a connector result's display cards, in order.
 *
 * Behavior:
 *     Consecutive `product` cards (and consecutive `plan` cards) form one group:
 *     a two-column grid, or a horizontal scroll row with snap points once there
 *     are 3 or more. Every other kind renders on its own line.
 * Parameters:
 *     cards: The cards from a `ConnectorResult` or a `ToolCallEvent`.
 */
export function ConnectorCards({ cards }: { cards: ConnectorCard[] }) {
  const groups: ConnectorCard[][] = []
  for (const card of cards) {
    const last = groups.at(-1)
    const groupable = card.kind === 'product' || card.kind === 'plan'
    if (groupable && last && last[0].kind === card.kind) last.push(card)
    else groups.push([card])
  }
  return (
    <div className="min-w-0 space-y-3" data-testid="connector-cards">
      {groups.map((group, i) =>
        group.length === 1 && group[0].kind !== 'product' && group[0].kind !== 'plan' ? (
          <CardView key={i} card={group[0]} />
        ) : (
          <div
            key={i}
            className={
              group.length >= ROW_FROM
                ? '-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-2 [scrollbar-width:thin]'
                : 'grid gap-3 sm:grid-cols-2'
            }
            data-card-row={group.length >= ROW_FROM ? 'scroll' : 'grid'}
          >
            {group.map((card, k) => (
              <div key={k} className={group.length >= ROW_FROM ? 'w-[13.5rem] shrink-0 snap-start' : 'min-w-0'}>
                <CardView card={card} />
              </div>
            ))}
          </div>
        ),
      )}
    </div>
  )
}

function CardView({ card }: { card: ConnectorCard }) {
  switch (card.kind) {
    case 'product':
      return <ProductCard card={card} />
    case 'plan':
      return <PlanCard card={card} />
    case 'verdict':
      return <VerdictCard card={card} />
    case 'comparison':
      return <ComparisonCard card={card} />
    case 'chart':
      return <ChartCard card={card} />
    case 'notice':
      return <NoticeCard card={card} />
  }
}

function Shell({ card, className = '', children }: { card: ConnectorCard; className?: string; children: ReactNode }) {
  return (
    <article
      className={`flex h-full min-w-0 flex-col gap-2.5 rounded-card border border-edge/10 bg-edge/[0.04] p-4 shadow-[inset_0_1px_0_rgb(var(--edge)/0.05)] ${className}`}
      data-card-kind={card.kind}
      aria-label={card.title}
    >
      {children}
    </article>
  )
}

function Badges({ badges }: { badges?: string[] }) {
  if (!badges?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {badges.map((b) => (
        <span
          key={b}
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] leading-4 ${
            b === SYNTHETIC_BADGE ? 'border-accent/30 bg-accent/10 text-accent' : 'border-edge/10 bg-edge/[0.05] text-muted'
          }`}
          data-badge={b === SYNTHETIC_BADGE ? 'synthetic' : undefined}
        >
          {b}
        </span>
      ))}
    </div>
  )
}

function Heading({ card, size = 'base' }: { card: ConnectorCard; size?: 'base' | 'lg' }) {
  return (
    <div className="min-w-0">
      <h4 className={`${size === 'lg' ? 'text-lg' : 'text-[15px]'} font-semibold leading-snug tracking-[-0.01em] text-fg`}>{card.title}</h4>
      {card.subtitle && <p className="mt-0.5 text-xs leading-snug text-muted">{card.subtitle}</p>}
    </div>
  )
}

function Price({ price }: { price?: CardPrice | null }) {
  if (!price) return null
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-2xl font-semibold tabular-nums tracking-[-0.02em] text-fg">
          {money(price.amount)}
          {(price.period ?? 'month') === 'month' && <span className="text-sm font-medium text-muted">/mo</span>}
        </span>
        {price.was != null && (
          <s className="text-sm tabular-nums text-muted" aria-label={`was ${money(price.was)}`}>
            {money(price.was)}
          </s>
        )}
      </div>
      {price.note && <p className="mt-0.5 text-xs leading-snug text-muted">{price.note}</p>}
    </div>
  )
}

function Fields({ card, limit }: { card: ConnectorCard; limit?: number }) {
  const fields = (card.fields ?? []).slice(0, limit)
  if (!fields.length) return null
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {fields.map((f) => (
        <div key={f.label} className="contents">
          <dt className="text-muted">{f.label}</dt>
          <dd className="truncate text-right text-fg/90" title={f.value}>{f.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function LinkButton({ card }: { card: ConnectorCard }) {
  if (!card.link) return null
  return (
    <a className="btn mt-auto self-start" href={card.link.url} target="_blank" rel="noreferrer">
      {card.link.label} <ExternalLink size={14} strokeWidth={1.75} aria-hidden />
    </a>
  )
}

function ProductCard({ card }: { card: ConnectorCard }) {
  return (
    <Shell card={card}>
      <div className="aspect-[3/4] w-full overflow-hidden rounded-control bg-edge/[0.05]">
        {card.image_url && (
          <img
            src={card.image_url}
            alt={card.image_alt ?? card.title}
            loading="lazy"
            decoding="async"
            width={240}
            height={320}
            className="h-full w-full object-contain p-2"
          />
        )}
      </div>
      <Heading card={card} />
      <Price price={card.price} />
      <Badges badges={card.badges} />
      <Fields card={card} limit={PRODUCT_FIELDS} />
      <LinkButton card={card} />
    </Shell>
  )
}

function PlanCard({ card }: { card: ConnectorCard }) {
  return (
    <Shell card={card}>
      {card.image_url && (
        <div className="aspect-[5/3] w-full overflow-hidden rounded-control bg-edge/[0.05]">
          <img src={card.image_url} alt={card.image_alt ?? card.title} loading="lazy" decoding="async" width={400} height={240} className="h-full w-full object-cover" />
        </div>
      )}
      <Heading card={card} />
      <Price price={card.price} />
      <Fields card={card} limit={PLAN_FIELDS} />
      <Badges badges={card.badges} />
      <LinkButton card={card} />
    </Shell>
  )
}

const TONES = {
  positive: { ring: 'border-ok/35', bar: 'bg-ok', text: 'text-ok', chip: 'border-ok/25 bg-ok/10' },
  caution: { ring: 'border-warn/40', bar: 'bg-warn', text: 'text-warn', chip: 'border-warn/30 bg-warn/10' },
  neutral: { ring: 'border-accent/30', bar: 'bg-accent', text: 'text-accent', chip: 'border-accent/25 bg-accent/10' },
}

function VerdictCard({ card }: { card: ConnectorCard }) {
  const tone = TONES[card.tone ?? 'neutral']
  return (
    <Shell card={card} className={`relative overflow-hidden ${tone.ring}`}>
      <span className={`absolute inset-y-0 left-0 w-1 ${tone.bar}`} aria-hidden />
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 pl-1">
        <div className="min-w-0">
          <p className={`text-[11px] font-semibold uppercase tracking-[0.08em] ${tone.text}`}>Verdict</p>
          <Heading card={card} size="lg" />
        </div>
        <Price price={card.price} />
      </div>
      {card.fields && card.fields.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 pl-1" aria-label="Signals">
          {card.fields.map((f) => (
            <li key={f.label} className={`rounded-full border px-2 py-0.5 text-[11px] text-fg/90 ${tone.chip}`} data-signal>
              <span className="text-muted">{f.label}</span> <span className="font-medium tabular-nums">{f.value}</span>
            </li>
          ))}
        </ul>
      )}
      {card.reasons && card.reasons.length > 0 && (
        <ol className="list-decimal space-y-1 pl-6 text-[13px] leading-relaxed text-fg/90 marker:text-muted">
          {card.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ol>
      )}
      <div className="pl-1">
        <Badges badges={card.badges} />
      </div>
      <LinkButton card={card} />
    </Shell>
  )
}

/** Rows to highlight: a changed Now/Suggested pair, or a total or savings row. */
function highlighted(columns: string[], row: string[]): boolean {
  const now = columns.findIndex((c) => /^(now|current)$/i.test(c))
  const next = columns.findIndex((c) => /^(suggested|after|new)$/i.test(c))
  if (now >= 0 && next >= 0 && row[now] !== row[next]) return true
  return /^(total|saving|savings)\b/i.test(row[0] ?? '')
}

function ComparisonCard({ card }: { card: ConnectorCard }) {
  const columns = card.columns ?? []
  const rows = card.rows ?? []
  return (
    <Shell card={card}>
      <Heading card={card} />
      <div className="-mx-1 overflow-x-auto px-1">
        <table className="w-full min-w-max border-separate border-spacing-0 text-left text-xs">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} scope="col" className="border-b border-edge/10 px-2 py-1.5 font-medium text-muted">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const hot = highlighted(columns, row)
              return (
                <tr key={i} className={hot ? 'bg-ok/10' : ''} data-highlight={hot ? 'true' : undefined}>
                  {row.map((cell, k) => (
                    <td key={k} className={`border-b border-edge/[0.06] px-2 py-1.5 tabular-nums ${k === 0 ? 'font-medium text-fg' : 'text-fg/85'}`}>{cell}</td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Fields card={card} />
      <Badges badges={card.badges} />
      <LinkButton card={card} />
    </Shell>
  )
}

function ChartCard({ card }: { card: ConnectorCard }) {
  return (
    <Shell card={card}>
      <Heading card={card} />
      {card.chart && <ConnectorChart chart={card.chart} title={card.title} />}
      {card.reasons?.[0] && <p className="text-xs leading-relaxed text-muted">{card.reasons[0]}</p>}
      <Badges badges={card.badges} />
    </Shell>
  )
}

function NoticeCard({ card }: { card: ConnectorCard }) {
  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-control border border-edge/10 bg-edge/[0.03] px-3.5 py-2.5 text-sm"
      data-card-kind="notice"
      role="note"
      aria-label={card.title}
    >
      <Info size={15} strokeWidth={1.75} className="shrink-0 text-accent" aria-hidden />
      <span className="font-medium text-fg">{card.title}</span>
      {card.subtitle && <span className="min-w-0 text-muted">{card.subtitle}</span>}
      <span className="ml-auto">
        <Badges badges={card.badges} />
      </span>
    </div>
  )
}
