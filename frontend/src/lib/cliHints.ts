/**
 * Equivalent `pam …` CLI commands (SETUP §6) for each UI action.
 *
 * Behavior:
 *     Each entry builds the command a user would run in the backend container to
 *     do the same thing the UI does. Free text is double-quoted for a POSIX shell.
 */

const q = (text: string) => `"${text.replace(/(["\\$`])/g, '\\$1')}"`
const agentFlag = (agent?: string) => (agent && agent !== 'default' ? ` --agent ${agent}` : '')
const ids = (list: string[]) => (list.length ? list.join(',') : '<id>')

export const cliHints = {
  importRun: (file = '<file>') => `pam import run ${file} --all`,
  graphExport: (agent?: string, facts?: boolean) =>
    `pam graph export${agentFlag(agent)}${facts ? ' --facts' : ''} --out g.json`,
  projectShow: (id = '<id>') => `pam project show ${id}`,
  factShow: (id = '<id>') => `pam fact show ${id}`,
  episodeShow: (id = '<id>') => `pam episode show ${id}`,
  chat: (message = '<msg>', model = '<id>', session = '<id>') =>
    `pam chat ${q(message)} --model ${model} --session ${session}`,
  sessionEnd: (id = '<id>') => `pam session end ${id}`,
  modelsList: () => 'pam models list',
  search: (query = '<q>', agent = 'default', k?: number) =>
    `pam search ${q(query)} --agent ${agent}${k && k !== 8 ? ` -k ${k}` : ''}`,
  context: (query = '<q>', budget: number | string = '<n>', agent?: string) =>
    `pam context ${q(query)} --budget ${budget}${agentFlag(agent)}`,
  agentCreate: (name = '<name>', projects: string[] = []) =>
    `pam agent create ${name} --projects ${ids(projects)}`,
  agentSetScope: (name = '<name>', projects: string[] = []) =>
    `pam agent set-scope ${name} --projects ${ids(projects)}`,
  agentShow: (name = '<name>') => `pam agent show ${name}`,
  sessionShow: (id = '<id>') => `pam session show ${id}`,
  configShow: () => 'pam config show',
  mcpServe: (agent = 'default') => `pam mcp serve --transport stdio --agent ${agent}`,
}

/**
 * CLI command that prints the vault file at `path`.
 *
 * Behavior:
 *     Maps the §6 vault layout to the matching `show` command; unknown paths
 *     fall back to `pam episode show <id>`.
 * Parameters:
 *     path: Vault-relative POSIX path, or nothing for the placeholder.
 */
export function cliForPath(path?: string | null): string {
  if (!path) return cliHints.episodeShow()
  const id = path.split('/').at(-1)?.replace(/\.(md|yaml)$/, '')
  if (/^memory\/[^/]+\/episodes\//.test(path)) return cliHints.episodeShow(id)
  if (/^memory\/[^/]+\/projects\//.test(path)) return cliHints.projectShow(id)
  if (/^memory\/[^/]+\/facts\//.test(path)) return cliHints.factShow(id)
  if (path.startsWith('agent/')) return cliHints.agentShow(path.split('/')[1])
  if (path.startsWith('working/')) return cliHints.sessionShow(id)
  if (path === 'pam.toml') return cliHints.configShow()
  return cliHints.episodeShow()
}
