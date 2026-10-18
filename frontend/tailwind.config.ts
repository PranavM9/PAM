import typography from '@tailwindcss/typography'
import type { Config } from 'tailwindcss'

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        panel: token('panel'),
        raised: token('raised'),
        line: token('line'),
        edge: token('edge'),
        fg: token('fg'),
        muted: token('muted'),
        accent: token('accent'),
        'accent-strong': token('accent-strong'),
        'accent-fg': token('accent-fg'),
        ok: token('ok'),
        warn: token('warn'),
        bad: token('bad'),
      },
      fontFamily: {
        sans: ['DM Sans', 'Avenir Next', 'Avenir', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', '"SF Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: {
        control: '14px',
        card: '20px',
        panel: '28px',
      },
    },
  },
  plugins: [typography],
} satisfies Config
