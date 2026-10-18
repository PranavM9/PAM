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
  mcpServe: (agent = 'default') => `pam mcp serve --transport stdio --agent ${agent}`,
}
