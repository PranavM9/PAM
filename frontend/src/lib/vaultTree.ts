/** Folder tree built from flat vault paths, for the vault browser. */

/** One folder or file in the vault tree. */
export interface TreeNode {
  name: string
  path: string
  children: TreeNode[]
  file: boolean
}

/**
 * Turn flat vault paths into a sorted folder tree (folders first, then by name).
 *
 * Parameters:
 *     paths: Vault-relative POSIX paths.
 * Returns:
 *     The top-level nodes.
 */
export function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', children: [], file: false }
  for (const path of paths) {
    let node = root
    path.split('/').forEach((part, i, parts) => {
      const childPath = parts.slice(0, i + 1).join('/')
      let child = node.children.find((c) => c.name === part)
      if (!child) {
        child = { name: part, path: childPath, children: [], file: i === parts.length - 1 }
        node.children.push(child)
      }
      node = child
    })
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => Number(a.file) - Number(b.file) || a.name.localeCompare(b.name))
    nodes.forEach((n) => sort(n.children))
  }
  sort(root.children)
  return root.children
}
