/**
 * In-app Markdown guides loaded from `src/guides/*.md` at build time.
 *
 * Behavior:
 *     Adding a guide means adding a `.md` file; its slug is the file name and
 *     its title is the first `# ` heading.
 */

const files = import.meta.glob<string>('./guides/*.md', { query: '?raw', import: 'default', eager: true })

/** One guide page. */
export interface Guide {
  slug: string
  title: string
  body: string
}

export const guides: Guide[] = Object.entries(files)
  .map(([path, body]) => ({
    slug: path.replace(/^.*\/(.+)\.md$/, '$1'),
    title: /^#\s+(.+)$/m.exec(body)?.[1] ?? path,
    body,
  }))
  .sort((a, b) => a.slug.localeCompare(b.slug))

/** Look up a guide by slug, e.g. `export-claude`. */
export function guide(slug: string): Guide | undefined {
  return guides.find((g) => g.slug === slug)
}
