import { Download, FileText, Plug, type LucideIcon } from 'lucide-react'

/** Guide category derived from the slug prefix. */
export interface GuideKind {
  label: string
  icon: LucideIcon
}

/**
 * Classify a guide by its slug prefix.
 *
 * Returns:
 *     `Connect a client` for `connect-*`, `Export your history` for `export-*`,
 *     otherwise `More guides`.
 * Parameters:
 *     slug: Guide slug, e.g. `export-claude`.
 */
export function guideKind(slug: string): GuideKind {
  if (slug.startsWith('connect-')) return { label: 'Connect a client', icon: Plug }
  if (slug.startsWith('export-')) return { label: 'Export your history', icon: Download }
  return { label: 'More guides', icon: FileText }
}
