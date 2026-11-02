import { token, type DocSummary, type KernelStatus } from './api';

export interface DocEvent { type: 'doc'; id: string; rev: number; [key: string]: unknown }
export interface DocsEvent { type: 'docs'; docs?: DocSummary[]; [key: string]: unknown }
export interface SysvarEvent { type: 'sysvar'; name: string; value: unknown; doc?: string; [key: string]: unknown }
export interface KernelEvent extends Partial<KernelStatus> { type: 'kernel'; [key: string]: unknown }
export interface JobEvent { type: 'job'; id: string; label?: string; state?: string; progress?: number; message?: string; [key: string]: unknown }

export type EngineEvent = DocEvent | DocsEvent | SysvarEvent | KernelEvent | JobEvent;
export type EventType = EngineEvent['type'];
export type EventOf<T extends EventType> = Extract<EngineEvent, { type: T }>;
export type LinkState = 'idle' | 'connecting' | 'open' | 'closed';

const EVENT_TYPES: ReadonlySet<string> = new Set(['doc', 'docs', 'sysvar', 'kernel', 'job']);
const BACKOFF_MIN = 500;
const BACKOFF_MAX = 10000;

export class EventsClient {
  private socket: WebSocket | null = null;
  private timer: number | undefined;
  private delay = BACKOFF_MIN;
  private wanted = false;
  private link: LinkState = 'idle';
  private readonly listeners = new Map<string, Set<(e: EngineEvent) => void>>();
  private readonly watchers = new Set<(s: LinkState) => void>();

  get state(): LinkState { return this.link; }

  connect(): void {
    this.wanted = true;
    if (this.socket || this.timer !== undefined) return;
    this.open();
  }

  close(): void {
    this.wanted = false;
    window.clearTimeout(this.timer);
    this.timer = undefined;
    const s = this.socket;
    this.socket = null;
    s?.close();
    this.setState('idle');
  }

  on<T extends EventType>(type: T, fn: (e: EventOf<T>) => void): () => void {
    let set = this.listeners.get(type);
    if (!set) { set = new Set(); this.listeners.set(type, set); }
    const wrapped = fn as (e: EngineEvent) => void;
    set.add(wrapped);
    return () => { set.delete(wrapped); };
  }

  onState(fn: (s: LinkState) => void): () => void {
    this.watchers.add(fn);
    return () => { this.watchers.delete(fn); };
  }

  inject(e: EngineEvent): void {
    for (const fn of this.listeners.get(e.type) ?? []) fn(e);
  }

  private setState(s: LinkState): void {
    if (this.link === s) return;
    this.link = s;
    for (const w of this.watchers) w(s);
  }

  private url(): string {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const tok = token();
    return `${scheme}://${location.host}/api/events${tok ? `?token=${encodeURIComponent(tok)}` : ''}`;
  }

  private open(): void {
    this.timer = undefined;
    this.setState('connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url());
    } catch {
      this.retry();
      return;
    }
    this.socket = ws;
    ws.addEventListener('open', () => { this.delay = BACKOFF_MIN; this.setState('open'); });
    ws.addEventListener('message', (m) => this.receive(m.data));
    ws.addEventListener('close', () => {
      if (this.socket === ws) this.socket = null;
      this.setState('closed');
      this.retry();
    });
    ws.addEventListener('error', () => ws.close());
  }

  private retry(): void {
    if (!this.wanted || this.timer !== undefined) return;
    const wait = this.delay + Math.round(Math.random() * this.delay * 0.25);
    this.delay = Math.min(BACKOFF_MAX, this.delay * 2);
    this.timer = window.setTimeout(() => { if (this.wanted) this.open(); else this.timer = undefined; }, wait);
  }

  private receive(data: unknown): void {
    if (typeof data !== 'string') return;
    let msg: unknown;
    try { msg = JSON.parse(data); } catch { return; }
    if (!msg || typeof msg !== 'object') return;
    const type = (msg as { type?: unknown }).type;
    if (typeof type !== 'string' || !EVENT_TYPES.has(type)) return;
    for (const fn of this.listeners.get(type) ?? []) fn(msg as EngineEvent);
  }
}

export const events = new EventsClient();
