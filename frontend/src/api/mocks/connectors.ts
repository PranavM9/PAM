/**
 * Mock-mode connectors (T18): the `/connectors` routes and synthetic tool results.
 *
 * Behavior:
 *     An in-memory store seeded with a synthetic carrier connector `tmobile`
 *     (the 7 tools of `mock/tmobile/connector.yaml`, ticked for `default`) and one
 *     archived example. Routes validate like the backend: 400 when the path id
 *     differs from the body, 404 for an unknown connector or tool, and an
 *     `ok: false` result for missing or undeclared arguments. Card images are
 *     inline SVG data URIs, because no mock service runs in mock mode. Every
 *     brand, plan and person is fictional.
 */
import type { CardChart, Connector, ConnectorCard, ConnectorResult, ToolCallEvent } from '../../types/generated'
import { ApiError } from '../client'

const SYNTHETIC = 'Synthetic demo data'
const SUMMARY_CHARS = 200

const svg = (body: string, w: number, h: number) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}">${body}</svg>`)}`

/** A phone front view in two gradient colours, 240×480 like the real mock's images. */
function phone(from: string, to: string): string {
  return svg(
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/></linearGradient></defs>` +
      '<rect x="24" y="16" width="192" height="448" rx="34" fill="url(#g)"/>' +
      '<rect x="36" y="30" width="168" height="420" rx="24" fill="#0f0b1f"/>' +
      '<rect x="36" y="30" width="168" height="420" rx="24" fill="url(#g)" opacity="0.35"/>' +
      '<text x="120" y="120" font-family="system-ui" font-size="34" fill="#fff" text-anchor="middle">9:41</text>' +
      '<circle cx="120" cy="44" r="6" fill="#000"/>',
    240,
    480,
  )
}

function planTile(color: string, label: string): string {
  return svg(
    `<rect width="400" height="240" rx="24" fill="${color}"/><rect y="170" width="400" height="70" fill="#000" opacity="0.15"/>` +
      `<text x="28" y="120" font-family="system-ui" font-size="40" font-weight="700" fill="#fff">${label}</text>`,
    400,
    240,
  )
}

const P = (name: string, type: 'string' | 'number' | 'boolean' = 'string', required = false, description = '') => ({ name, type, required, description })

function seed(): Connector[] {
  return [
    {
      id: 'tmobile',
      name: 'T-Mobile (synthetic)',
      description: 'Synthetic carrier data: phones, plans, add-ons, trade-in values and household accounts.',
      base_url: 'http://tmobile-mock:8100',
      public_base_url: '/connectors/tmobile',
      auth: { type: 'none', header: null, env_var: null },
      tools: [
        { name: 'get_household', description: 'Look up a household account.', method: 'GET', path: '/customers/{customer_id}', params: [P('customer_id', 'string', true, 'Customer id, for example cust-chen.')] },
        { name: 'search_devices', description: 'Search the phones on sale.', method: 'GET', path: '/catalog/devices', params: [P('query', 'string', false, 'Free text such as camera or battery.'), P('max_monthly', 'number'), P('form_factor'), P('limit', 'number')] },
        { name: 'list_plans', description: 'List the plans priced for a line count.', method: 'GET', path: '/catalog/plans', params: [P('lines', 'number')] },
        { name: 'tradein_value', description: 'Trade-in value now and over time.', method: 'GET', path: '/tradein/{device_id}', params: [P('device_id', 'string', true), P('months_ahead', 'number')] },
        { name: 'recommend_upgrade', description: 'Should this line upgrade, wait, or replace the battery.', method: 'POST', path: '/recommend/upgrade', params: [P('customer_id', 'string', true), P('line_id', 'string', true), P('monthly_budget', 'number'), P('needs')] },
        { name: 'optimize_household', description: 'Cheapest plan mix that covers the household.', method: 'POST', path: '/recommend/household', params: [P('customer_id', 'string', true), P('include_home_internet', 'boolean')] },
        { name: 'suggest_addons', description: 'Add-ons worth buying with a device, or nothing.', method: 'POST', path: '/recommend/addons', params: [P('customer_id', 'string', true), P('line_id', 'string', true), P('device_id', 'string', true)] },
      ],
      enabled: true,
      archived: false,
      agents: ['default'],
    },
    {
      id: 'weather-demo',
      name: 'Weather (old example)',
      description: 'An archived example connector.',
      base_url: 'https://api.example.com/weather',
      public_base_url: null,
      auth: { type: 'api_key', header: 'x-api-key', env_var: 'WEATHER_API_KEY' },
      tools: [{ name: 'forecast', description: 'Three-day forecast.', method: 'GET', path: '/forecast', params: [P('city', 'string', true)] }],
      enabled: false,
      archived: true,
      agents: [],
    },
  ]
}

let connectors: Connector[] = seed()

const card = (c: Omit<ConnectorCard, 'connector_id'>): ConnectorCard => ({
  ...c,
  badges: [SYNTHETIC, ...(c.badges ?? [])],
  connector_id: 'tmobile',
})

const product = (title: string, subtitle: string, amount: number, was: number, colors: [string, string], fields: [string, string][]) =>
  card({
    kind: 'product', title, subtitle, image_url: phone(...colors), image_alt: `${title} front view`,
    price: { amount, period: 'month', was, note: 'over 24 months after trade-in' },
    fields: fields.map(([label, value]) => ({ label, value })),
  })

const TRADEIN: CardChart = {
  kind: 'line', x_label: 'Months from today', y_label: 'Trade-in value (USD)', marker_x: 0,
  series: [{
    label: 'Kestrel 5',
    points: [-6, -4, -2, 0, 2, 4, 6, 8, 10, 12].map((m): [number, number] => [m, Math.round(63 - m * 1.7 + (m < 0 ? -m * 0.6 : 0))]),
  }],
}

const RESULTS: Record<string, () => { data: Record<string, unknown>; cards: ConnectorCard[] }> = {
  get_household: () => ({
    data: { customer_id: 'cust-chen', lines: 4 },
    cards: [card({ kind: 'comparison', title: 'Chen household', subtitle: '4 lines, bill $236/mo', columns: ['Line', 'Phone', 'Plan', 'Data'], rows: [['Mei', 'Aurora One', 'Max', '12.1 GB'], ['David', 'Lumen 3', 'Max', '2.4 GB'], ['Maya', 'Kestrel 5', 'Plus', '41.3 GB'], ['Leo', 'Nimbus A', 'Starter', '49.1 GB']] })],
  }),
  search_devices: () => ({
    data: { query: 'camera', results: 3 },
    cards: [
      product('Kestrel 8 Pro', 'Kestrel flagship, 256 GB', 22.5, 33.29, ['#5b6b8c', '#2c3550'], [['Camera', 'Triple 50 MP'], ['Battery', '5000 mAh'], ['Rating', '4.7 of 5']]),
      product('Aurora One Pro', 'Aurora flagship, 256 GB', 24.0, 37.46, ['#6d6875', '#2b2d42'], [['Camera', '200 MP main'], ['Battery', '4900 mAh'], ['Rating', '4.6 of 5']]),
      product('Lumen X', 'Lumen mid, 128 GB', 16.25, 22.88, ['#1b1b2f', '#4a4e69'], [['Camera', 'Dual 64 MP'], ['Battery', '4600 mAh'], ['Rating', '4.3 of 5']]),
    ],
  }),
  list_plans: () => ({
    data: { lines: 4 },
    cards: [
      ['Starter', 20, '15 GB', '3 GB', '#7c6cf0'],
      ['Plus', 30, '50 GB', '15 GB', '#4f9dde'],
      ['Max', 40, 'Unlimited', '50 GB', '#d46aa8'],
      ['Student', 18, '60 GB', '10 GB', '#3fae8c'],
    ].map(([name, price, data, hotspot, color]) =>
      card({
        kind: 'plan', title: String(name), subtitle: 'Fictional plan', image_url: planTile(String(color), String(name)), image_alt: `${name} plan tile`,
        price: { amount: Number(price), period: 'month', note: 'per line with 4 lines and autopay' },
        fields: [{ label: 'Premium data', value: String(data) }, { label: 'Hotspot', value: String(hotspot) }, { label: 'Total', value: `$${Number(price) * 4}/mo` }],
      }),
    ),
  }),
  tradein_value: () => ({
    data: { device_id: 'kestrel-5', today: 63 },
    cards: [card({ kind: 'chart', title: 'Kestrel 5 trade-in value', subtitle: '$63 today, $57 in 3 months', chart: TRADEIN, reasons: ['Waiting 3 months costs you about $6 in trade-in value.'] })],
  }),
  recommend_upgrade: () => ({
    data: { winner: 'replace_battery' },
    cards: [
      card({
        kind: 'verdict', title: 'Replace the battery', subtitle: 'The lowest 24-month cost for what Maya needs', tone: 'positive',
        price: { amount: 89, period: 'once', note: 'battery replacement, about an hour in store' },
        fields: [{ label: 'Battery health', value: '78%' }, { label: 'Phone age', value: '37 months' }, { label: 'Trade-in today', value: '$63' }],
        reasons: [
          'A new battery costs $89 once and brings your battery back to full health.',
          'Keeping your phone as it is scores $300, which is $61 more.',
          'Upgrading to the Kestrel 8 scores $336, which is $97 more.',
        ],
      }),
      RESULTS.tradein_value().cards[0],
      product('Kestrel 8', 'Kestrel mid, 128 GB', 14, 24.96, ['#7d8597', '#33415c'], [['Battery', '4800 mAh'], ['Camera', 'Dual 50 MP'], ['Rating', '4.5 of 5']]),
      product('Kestrel A', 'Kestrel budget, 128 GB', 7.75, 10.38, ['#adb5bd', '#495057'], [['Battery', '4500 mAh'], ['Camera', '48 MP main'], ['Rating', '4.0 of 5']]),
    ],
  }),
  optimize_household: () => ({
    data: { savings_monthly: 74.48 },
    cards: [
      card({
        kind: 'verdict', title: 'Save $74.48/mo on your plans', subtitle: 'Chen household', tone: 'positive',
        price: { amount: 95, period: 'month', was: 169.48, note: 'plans, bundles and services, autopay on' },
        fields: [{ label: 'Saved per year', value: '$893.76' }, { label: 'Options checked', value: '1,024' }],
        reasons: ['Move David from Max to Starter: he peaks at 2.4 GB.', 'Move Maya and Leo to Student.', 'The Sound bundle covers two subscriptions you pay for separately.'],
      }),
      card({
        kind: 'comparison', title: 'Your plans now and suggested', subtitle: '$169.48/mo now, $95/mo suggested',
        columns: ['Line', 'Now', 'Suggested', 'Peak data'],
        rows: [['Mei', 'Max', 'Plus', '12.1 GB'], ['David', 'Max', 'Starter', '2.4 GB'], ['Maya', 'Plus', 'Student', '41.3 GB'], ['Leo', 'Starter', 'Student', '49.1 GB'], ['Total', '$169.48/mo', '$95/mo', '']],
      }),
    ],
  }),
  suggest_addons: () => ({
    data: { addons: [] },
    cards: [card({ kind: 'notice', title: 'Nothing else needed', subtitle: 'This line already has protection, a case and a charger.' })],
  }),
}

function find(id: string): Connector {
  const c = connectors.find((x) => x.id === id)
  if (!c) throw new ApiError(404, 'NOT_FOUND', `connector '${id}' not found`)
  return c
}

/** Run one mocked tool call, refusing bad arguments like the backend's executor. */
function callTool(id: string, tool: string, args: Record<string, unknown>): ConnectorResult {
  const spec = find(id).tools?.find((t) => t.name === tool)
  if (!spec) throw new ApiError(404, 'NOT_FOUND', `connector '${id}' has no tool '${tool}' (not found)`)
  const params = spec.params ?? []
  const undeclared = Object.keys(args).filter((k) => args[k] != null && !params.some((p) => p.name === k))
  const missing = params.filter((p) => p.required && (args[p.name] == null || args[p.name] === '')).map((p) => p.name)
  const latency_ms = 40 + Math.floor(Math.random() * 60)
  if (undeclared.length || missing.length) {
    const message = undeclared.length ? `undeclared argument(s): ${undeclared.join(', ')}` : `missing required argument(s): ${missing.join(', ')}`
    return { ok: false, status: null, latency_ms: 0, data: null, cards: [], error: { code: 'BAD_ARGUMENTS', message } }
  }
  const make = RESULTS[tool]
  if (!make) return { ok: false, status: 404, latency_ms, data: null, cards: [], error: { code: 'HTTP_404', message: `${find(id).name} answered HTTP 404` } }
  const { data, cards } = make()
  return { ok: true, status: 200, latency_ms, data: { synthetic: true, as_of: '2026-10-18', data }, cards, error: null }
}

/**
 * Serve a `/connectors` route in mock mode.
 *
 * Exceptions:
 *     ApiError: 400 for an id mismatch or a missing name/base URL, 404 for an unknown connector or tool.
 * Returns:
 *     The response body, or `undefined` when the route is not a connector route.
 * Parameters:
 *     method: HTTP method.
 *     parts: Decoded path segments after `/api` (the first is `connectors`).
 *     query: Query string parameters.
 *     body: JSON body.
 */
export function mockConnectorRequest(method: string, parts: string[], query: URLSearchParams, body: unknown): unknown {
  const [, id, action, tool, verb] = parts
  if (method === 'GET' && !id) {
    const all = query.get('include_archived') === 'true'
    return connectors.filter((c) => all || !c.archived).sort((a, b) => a.id.localeCompare(b.id))
  }
  if (method === 'GET' && id && !action) return find(id)
  if (method === 'PUT' && id && !action) {
    const c = body as Connector
    if (!c || c.id !== id) throw new ApiError(400, 'VALIDATION_ERROR', 'connector.id must match the URL')
    if (!c.name?.trim() || !/^https?:\/\//.test(c.base_url ?? '')) throw new ApiError(400, 'VALIDATION_ERROR', 'name and base_url are required')
    connectors = [...connectors.filter((x) => x.id !== id), { ...c, schema_version: '1.1.0' }]
    return find(id)
  }
  if (method === 'POST' && id && action === 'archive') {
    const c = find(id)
    connectors = connectors.map((x) => (x.id === id ? { ...c, archived: true, enabled: false } : x))
    return find(id)
  }
  if (method === 'POST' && id && action === 'tools' && tool && verb === 'call') {
    return callTool(id, tool, (body as Record<string, unknown>) ?? {})
  }
  return undefined
}

const PHONE_TOPIC = /\b(phone|upgrade|plan|plans|bill|battery|carrier)\b/i

/**
 * The connector tool calls the mock chat makes for one turn.
 *
 * Behavior:
 *     Only for a message about phones or plans, from an agent ticked on the
 *     enabled `tmobile` connector, with a model that supports tools (the same
 *     rules the backend applies). The four calls together carry every card kind.
 * Returns:
 *     The `tool_call` events in order, or an empty list.
 * Parameters:
 *     agent: The chat's agent.
 *     message: The user's message.
 *     supportsTools: Whether the chosen model supports tools.
 */
export function mockConnectorCalls(agent: string, message: string, supportsTools: boolean): ToolCallEvent[] {
  const c = connectors.find((x) => x.id === 'tmobile')
  if (!supportsTools || !c || !c.enabled || c.archived || !(c.agents ?? []).includes(agent) || !PHONE_TOPIC.test(message)) return []
  const calls: [string, Record<string, unknown>][] = [
    ['recommend_upgrade', { customer_id: 'cust-chen', line_id: 'chen-maya', monthly_budget: 40, needs: 'battery,camera' }],
    ['optimize_household', { customer_id: 'cust-chen' }],
    ['list_plans', { lines: 4 }],
    ['suggest_addons', { customer_id: 'cust-chen', line_id: 'chen-maya', device_id: 'kestrel-5' }],
  ]
  return calls.map(([tool, args]) => {
    const result = callTool('tmobile', tool, args)
    const summary = JSON.stringify({ connector: 'tmobile', tool, data: result.data }).slice(0, SUMMARY_CHARS)
    return { type: 'tool_call', name: `tmobile__${tool}`, arguments: args, result_summary: summary, cards: result.cards ?? [] }
  })
}
