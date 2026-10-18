import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Render Markdown (GFM) inside the typography `prose` styles.
 *
 * Parameters:
 *     children: Markdown source.
 *     className: Extra classes for the wrapper.
 */
export function Markdown({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`prose prose-sm ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
