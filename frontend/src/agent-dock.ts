import { onShellMounted } from './app';
import type { DockAdapter, DockAgentStatus, DockChannel, DockErrorKind, DockTerminal } from './dock/adapter';
import { Dock } from './dock/dock';
import { ApiError } from './io/api';
import { terminalApi, termSocket } from './io/terminal-api';
import { commands } from './ui/commands';
import { isMac } from './ui/dom';

type Extra = 'antigravity';

const LEAD = "Ask Claude Code about your drawing. It works through FormCAD's commands, and every change shows in the window.";

function socketChannel(socket: WebSocket): DockChannel {
  let data = (_chunk: string | Uint8Array): void => undefined;
  let exit = (): void => undefined;
  let closed = (): void => undefined;
  socket.binaryType = 'arraybuffer';
  socket.addEventListener('message', (msg) => {
    if (typeof msg.data === 'string') { data(msg.data); return; }
    try { if ((JSON.parse(new TextDecoder().decode(msg.data as ArrayBuffer)) as { type?: string }).type === 'exit') exit(); } catch { return; }
  });
  socket.addEventListener('close', () => closed());
  const send = (text: string): void => {
    if (socket.readyState === WebSocket.OPEN) socket.send(text);
    else if (socket.readyState === WebSocket.CONNECTING) socket.addEventListener('open', () => socket.send(text), { once: true });
  };
  return {
    send: (chunk) => send(JSON.stringify({ type: 'input', data: chunk })),
    resize: (cols, rows) => send(JSON.stringify({ type: 'resize', cols, rows })),
    onData: (handler) => { data = handler; },
    onExit: (handler) => { exit = handler; },
    onClose: (handler) => { closed = handler; },
    close: () => socket.close(),
  };
}

function errorKind(err: unknown): DockErrorKind | null {
  if (!(err instanceof ApiError)) return err instanceof TypeError ? 'unreachable' : null;
  if (err.status === 0 || err.status === 502 || err.status === 503 || err.status === 504) return 'unreachable';
  if (err.status === 401 || err.status === 403) return 'refused';
  if (err.status === 424) return 'notInstalled';
  if (err.status === 409) return 'busy';
  if ((err.status === 404 || err.status === 405) && /^(Not Found|Method Not Allowed)$/i.test(err.message)) return 'oldEngine';
  return null;
}

export function formcadAgentDock(): DockAdapter<Extra> {
  return {
    words: { app: 'FormCAD', noun: 'drawing', lead: LEAD, example: 'draw a 40 by 20 rectangle at the origin', start: './formCAD' },
    placement: {
      mode: 'own',
      storage: { key: 'formCAD.agentDock' },
      sizes: { minHeight: 120, maxHeightShare: 0.7, defaultHeight: 280, minWidth: 320, maxWidthShare: 0.6, defaultWidth: 440 },
    },
    chordLabel: () => `${isMac ? 'Cmd' : 'Ctrl'}+J`,
    tabs: () => ({ builtin: ['shell', 'claude', 'codex', 'cursor', 'antigravity'] }),
    classes: { iconButton: 'cv-tt-btn', button: 'cv-btn', primaryButton: 'cv-btn cv-btn-primary', input: 'cv-input', select: 'cv-input', note: 'cv-note' },
    t: (_key, english) => english,
    onTheme: (handler) => { document.addEventListener('nm:ui-settings-changed', handler); },
    errors: {
      message: (err) => (err instanceof ApiError ? err.message : null),
      kind: errorKind,
    },
    terminal: {
      list: async () => (await terminalApi.list()) as DockTerminal<Extra>[],
      open: async (kind, o) => {
        if (kind === 'shell') return (await terminalApi.openShell(o.cols, o.rows)) as DockTerminal<Extra>;
        return (await terminalApi.openAgent(kind, { cols: o.cols, rows: o.rows, ...(o.prompt ? { prompt: o.prompt } : {}), ...(o.resume ? { resume: o.resume } : {}) })) as DockTerminal<Extra>;
      },
      restart: (id) => terminalApi.restart(id),
      close: (id) => terminalApi.close(id),
      channel: (id) => socketChannel(termSocket(id)),
    },
    agentStatus: async () => {
      try {
        const { contract: _contract, ...programs } = await terminalApi.status();
        return programs as DockAgentStatus<Extra>;
      } catch {
        return null;
      }
    },
  };
}

let agentDock: Dock<Extra> | null = null;

export const theAgentDock = (): Dock<Extra> | null => agentDock;

onShellMounted(({ hosts }) => {
  const dock = new Dock(formcadAgentDock());
  agentDock = dock;
  dock.mount(hosts.root, hosts.status);
  commands.add(
    {
      id: 'agent-dock',
      label: 'Agent Dock',
      icon: 'terminal',
      group: 'Window',
      description: 'Show or hide the agent dock: a terminal, Claude Code, Codex, Cursor and Antigravity with FormCAD connected. Tabs keep running while it is hidden.',
      checked: () => dock.isOpen(),
      run: () => { dock.toggle(); },
    },
    {
      id: 'agent-dock-terminal',
      label: 'New Terminal Tab',
      icon: 'terminal',
      group: 'Window',
      description: 'Open a new shell tab in the agent dock.',
      run: () => { void dock.newTerminal(); },
    },
    {
      id: 'agent-dock-claude',
      label: 'Claude Code Tab',
      icon: 'agent',
      group: 'Window',
      description: "Open Claude Code in the agent dock with FormCAD's MCP server connected.",
      checked: () => dock.isShowing('claude'),
      run: () => { void dock.toggleKind('claude'); },
    },
  );
});
