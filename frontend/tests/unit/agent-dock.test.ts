import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { agentKinds } from '../../src/dock/agents';
import { moveLegacy, readState, type DockStore } from '../../src/dock/state';
import { engine, jsonResponse, type Sent } from './support';

type Holder = { __FORMCAD_TOKEN?: unknown };

class FakeSocket extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static urls: string[] = [];
  readyState = 1;
  binaryType = 'blob';
  constructor(readonly url: string) { super(); FakeSocket.urls.push(url); queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', { data: '' }))); }
  send(): void { return undefined; }
  close(): void { this.readyState = 3; }
}

let opened = 0;
function terminalEngine(): Sent[] {
  return engine((method, url, body) => {
    if (method === 'GET' && url === '/api/terminal') return jsonResponse(200, { terminals: [] });
    if (method === 'GET' && url === '/api/agents/status') return jsonResponse(200, { contract: '2.2.1', claude: { installed: true, version: '1', install: '', signedIn: true }, codex: { installed: true, version: '1', install: '', signedIn: null } });
    if (method === 'POST' && url === '/api/terminal') return jsonResponse(200, { id: `t${++opened}`, title: 'shell', alive: true, kind: 'shell' });
    if (method === 'POST' && url === '/api/terminal/agent') { const kind = (body as { kind: string }).kind; return jsonResponse(200, { id: `t${++opened}`, title: kind, alive: true, kind }); }
    if (method === 'DELETE') return new Response(null, { status: 204 });
    return jsonResponse(404, { detail: 'Not Found' }, 'Not Found');
  });
}

async function adapter() {
  vi.resetModules();
  const mod = await import('../../src/agent-dock');
  return mod.formcadAgentDock();
}

beforeEach(() => {
  opened = 0;
  FakeSocket.urls = [];
  localStorage.clear();
  (window as unknown as Holder).__FORMCAD_TOKEN = 'window-key';
});
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ''; });

describe('the agent dock adapter', () => {
  it.each(['claude', 'codex', 'cursor', 'antigravity'] as const)('opening a %s tab asks the engine to launch that agent with the window key in the header only', async (kind) => {
    const a = await adapter();
    const sent = terminalEngine();
    const rec = await a.terminal.open(kind, { cols: 120, rows: 30, prompt: 'draw a 40 by 20 rectangle' });
    expect(rec.kind).toBe(kind);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ method: 'POST', url: '/api/terminal/agent', body: { kind, cols: 120, rows: 30, prompt: 'draw a 40 by 20 rectangle' } });
    expect(sent[0].headers['X-FormCAD-Token']).toBe('window-key');
    expect(JSON.stringify(sent[0].body)).not.toContain('window-key');
  });

  it('opening a shell tab uses the shell route with no agent kind', async () => {
    const a = await adapter();
    const sent = terminalEngine();
    await a.terminal.open('shell', { cols: 80, rows: 24 });
    expect(sent[0]).toMatchObject({ method: 'POST', url: '/api/terminal', body: { cols: 80, rows: 24 } });
    expect(sent[0].body).not.toHaveProperty('kind');
  });

  it('resuming a Claude Code session sends the session id and no prompt', async () => {
    const a = await adapter();
    const sent = terminalEngine();
    await a.terminal.open('claude', { cols: 100, rows: 20, resume: 'sess-42' });
    expect(sent[0].body).toEqual({ kind: 'claude', cols: 100, rows: 20, resume: 'sess-42' });
  });

  it('reports the agent programs without the contract number and null when the engine cannot be reached', async () => {
    const a = await adapter();
    terminalEngine();
    const st = await a.agentStatus();
    expect(Object.keys(st ?? {}).sort()).toEqual(['claude', 'codex']);
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    expect(await a.agentStatus()).toBeNull();
  });

  it.each([
    [401, 'Session key missing', 'refused'], [403, 'Agents are blocked', 'refused'], [502, 'Bad Gateway', 'unreachable'], [503, 'x', 'unreachable'],
    [424, 'Claude Code is not installed', 'notInstalled'], [409, 'Tab is starting', 'busy'], [404, 'Not Found', 'oldEngine'], [404, 'No terminal t9', null],
  ])('an engine answer of %d with "%s" is classed as %s', async (status, message, kind) => {
    const a = await adapter();
    const { ApiError } = await import('../../src/io/api');
    expect(a.errors.kind?.(new ApiError(status, message))).toBe(kind);
    expect(a.errors.message(new ApiError(status, message))).toBe(message);
  });

  it('lists the four agent programs and not the plain shell among the launchable agents', async () => {
    const a = await adapter();
    expect(agentKinds(a.tabs().builtin).map((k) => k.id)).toEqual(['claude', 'codex', 'cursor', 'antigravity']);
  });
});

describe('the agent dock tabs', () => {
  async function mounted() {
    const a = await adapter();
    vi.stubGlobal('WebSocket', FakeSocket);
    const sent = terminalEngine();
    const { Dock } = await import('../../src/dock/dock');
    const dock = new Dock(a);
    const host = document.createElement('div');
    document.body.append(host);
    dock.mount(host);
    return { dock, sent };
  }
  const settle = async (): Promise<void> => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };
  const titles = (dock: { root: HTMLElement }): string[] => [...dock.root.querySelectorAll('.ft-dock-tab .ft-dock-tab-title')].map((n) => n.textContent ?? '');

  it('opening the dock starts one shell tab, showing an agent adds its tab in front, and switching back selects the shell', async () => {
    const { dock } = await mounted();
    dock.toggle(true);
    await settle();
    expect(dock.isOpen()).toBe(true);
    expect(dock.activeKind()).toBe('shell');
    await dock.show('codex');
    await settle();
    expect(dock.activeKind()).toBe('codex');
    expect(titles(dock)).toEqual(['shell', 'codex']);
    await dock.show('shell');
    expect(dock.activeKind()).toBe('shell');
    const selected = [...dock.root.querySelectorAll('.ft-dock-tab[aria-selected="true"] .ft-dock-tab-title')].map((n) => n.textContent);
    expect(selected).toEqual(['shell']);
  });

  it('closing a tab ends its program on the engine and selects the remaining tab', async () => {
    const { dock, sent } = await mounted();
    dock.toggle(true);
    await settle();
    await dock.show('claude');
    await settle();
    const tab = [...dock.root.querySelectorAll<HTMLElement>('.ft-dock-tab')].find((n) => n.textContent === 'claude');
    tab?.querySelector<HTMLElement>('.ft-dock-tab-x')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await settle();
    expect(titles(dock)).toEqual(['shell']);
    expect(dock.activeKind()).toBe('shell');
    expect(sent.filter((s) => s.method === 'DELETE').map((s) => s.url)).toEqual(['/api/terminal/t2']);
  });

  it('each tab stream is opened on its own terminal route carrying the window key', async () => {
    const { dock } = await mounted();
    dock.toggle(true);
    await settle();
    await dock.show('claude');
    await settle();
    expect(FakeSocket.urls.map((u) => new URL(u).pathname)).toEqual(['/api/terminal/t1/stream', '/api/terminal/t2/stream']);
    expect(FakeSocket.urls.every((u) => new URL(u).searchParams.get('token') === 'window-key')).toBe(true);
  });

  it('closing and reopening the dock is remembered for the next start', async () => {
    const { dock } = await mounted();
    dock.toggle(true);
    await settle();
    dock.toggle(false);
    expect(dock.isOpen()).toBe(false);
    const store = localStorage as unknown as DockStore;
    expect(readState(store, 'formCAD.agentDock', undefined, { h: 280, w: 440 }).open).toBe(false);
    dock.toggle(true);
    await settle();
    expect(readState(store, 'formCAD.agentDock', undefined, { h: 280, w: 440 }).open).toBe(true);
  });
});

describe('the stored dock layout', () => {
  const memory = (seed: Record<string, string>): DockStore & { data: Record<string, string> } => {
    const data = { ...seed };
    return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; }, removeItem: (k) => { delete data[k]; } };
  };

  it('restores a saved layout and falls back to defaults for a damaged one', () => {
    const good = memory({ k: JSON.stringify({ open: true, side: 'right', h: 300, w: 500, tab: 'claude' }) });
    expect(readState(good, 'k', undefined, { h: 280, w: 440 })).toEqual({ open: true, side: 'right', h: 300, w: 500, tab: 'claude' });
    const bad = memory({ k: '{not json' });
    expect(readState(bad, 'k', undefined, { h: 280, w: 440 })).toEqual({ open: false, side: 'bottom', h: 280, w: 440, tab: '' });
  });

  it('moves a layout kept under an old key to the new key and removes the old one', () => {
    const s = memory({ old: JSON.stringify({ open: true, h: 333 }) });
    expect(moveLegacy(s, 'new', ['old'], { h: 280, w: 440 })).toBe(true);
    expect(s.data.old).toBeUndefined();
    expect(JSON.parse(s.data.new)).toMatchObject({ open: true, h: 333, w: 440, side: 'bottom' });
    expect(moveLegacy(s, 'new', ['old'], { h: 280, w: 440 })).toBe(false);
  });
});
