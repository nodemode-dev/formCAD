import { api, ApiError, type DocSummary, type FileItem } from '../io/api';
import { events } from '../io/events';
import { askSaveChanges } from './dialogs';
import { stored, store } from './dom';
import { pickOpenPath, pickSavePath } from './file-dialogs';
import { tellNotes } from './output/notes';
import { out as outputApi } from './output/output-api';
import { trackWork } from './output/job-feed';
import { toast } from './toast';

const HOME_KEY = 'formCAD.home';

export function readHome(): Record<string, unknown> {
  try {
    const v: unknown = JSON.parse(stored(HOME_KEY) ?? '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

export function writeHome(patch: Record<string, unknown>): void {
  store(HOME_KEY, JSON.stringify({ ...readHome(), ...patch }));
}

export function toMillis(v: number | string | undefined): number {
  if (typeof v === 'number') return v < 1e12 ? v * 1000 : v;
  if (typeof v === 'string') {
    const n = Date.parse(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

export function filterRecent(items: FileItem[]): FileItem[] {
  const cleared = Number(readHome().recentClearedAt) || 0;
  return cleared ? items.filter((i) => toMillis(i.modified) > cleared) : items;
}

export const openHooks: { ask?: (path: string) => Promise<object | null | false> } = {};

const failure = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

export class DocStore {
  docs: DocSummary[] = [];
  activeId: string | null = null;
  recent: FileItem[] = [];
  private loaded = false;
  private timer = 0;
  private readonly listeners = new Set<() => void>();

  constructor() {
    events.on('docs', (e) => { if (e.docs) this.setDocs(e.docs); else this.queue(); });
    events.on('doc', () => this.queue());
    events.onState((s) => { if (s === 'open') { void this.refresh(); void this.refreshRecent(); } });
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  current(): DocSummary | null {
    return this.docs.find((d) => d.id === this.activeId) ?? null;
  }

  private queue(): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, 120);
  }

  async refresh(): Promise<void> {
    try {
      this.setDocs((await api.docs()).docs);
    } catch {
      return;
    }
  }

  async refreshRecent(): Promise<void> {
    try {
      this.recent = filterRecent((await api.recent()).items);
      this.emit();
    } catch {
      return;
    }
  }

  private setDocs(list: DocSummary[]): void {
    const known = new Set(this.docs.map((d) => d.id));
    const fresh = this.loaded ? list.filter((d) => !known.has(d.id)) : [];
    this.docs = list;
    this.loaded = true;
    if (fresh.length) this.activeId = fresh[fresh.length - 1].id;
    else if (!list.some((d) => d.id === this.activeId)) this.activeId = list.length ? list[list.length - 1].id : null;
    this.emit();
  }

  private upsert(doc: DocSummary, activate = true): void {
    const at = this.docs.findIndex((d) => d.id === doc.id);
    this.docs = at < 0 ? [...this.docs, doc] : this.docs.map((d, i) => (i === at ? doc : d));
    if (activate) this.activeId = doc.id;
    this.emit();
  }

  switchTo(id: string): void {
    if (this.activeId === id || !this.docs.some((d) => d.id === id)) return;
    this.activeId = id;
    this.emit();
  }

  async create(template?: string, name?: string): Promise<DocSummary | null> {
    try {
      const doc = await api.createDoc({ ...(template ? { template } : {}), ...(name ? { name } : {}) });
      this.upsert(doc);
      return doc;
    } catch (e) {
      toast(failure(e), 'error');
      return null;
    }
  }

  async openPath(path: string): Promise<DocSummary | null> {
    try {
      const foreign = !/\.fcad$/i.test(path.trim());
      let options: object | undefined;
      if (foreign && openHooks.ask) {
        const asked = await openHooks.ask(path);
        if (asked === null) return null;
        if (asked) options = asked;
      }
      const doc = foreign ? await trackWork(`Open ${path.split(/[\\/]/).pop() ?? path}`, () => outputApi.openForeign(path, false, options)) : await api.openDoc(path);
      this.upsert(doc);
      void this.refreshRecent();
      if (foreign) tellNotes(`Opened ${doc.name}.`, (doc as { notes?: Parameters<typeof tellNotes>[1] }).notes);
      return doc;
    } catch (e) {
      toast(failure(e), 'error');
      return null;
    }
  }

  async openByPrompt(): Promise<DocSummary | null> {
    const path = await pickOpenPath();
    return path ? this.openPath(path) : null;
  }

  async save(id: string | null = this.activeId): Promise<boolean> {
    const doc = this.docs.find((d) => d.id === id);
    if (!doc) return false;
    if (!doc.path) return this.saveAs(doc.id);
    try {
      this.upsert(await api.saveDoc(doc.id), false);
      void this.refreshRecent();
      return true;
    } catch (e) {
      toast(failure(e), 'error');
      return false;
    }
  }

  async saveAs(id: string | null = this.activeId): Promise<boolean> {
    const doc = this.docs.find((d) => d.id === id);
    if (!doc) return false;
    const path = await pickSavePath(doc.path ?? `${doc.name.replace(/\.fcad$/i, '')}.fcad`);
    if (!path) return false;
    try {
      const foreign = /\.(dxf|dwg|dwt|3dm)$/i.test(path.trim());
      const saved = foreign ? await trackWork(`Save ${path.split(/[\\/]/).pop() ?? path}`, () => outputApi.saveAs(doc.id, path)) : await api.saveDoc(doc.id, path);
      this.upsert(saved, false);
      void this.refreshRecent();
      if (foreign) tellNotes(`Saved ${path.split(/[\\/]/).pop() ?? path}.`, (saved as { notes?: Parameters<typeof tellNotes>[1] }).notes);
      return true;
    } catch (e) {
      toast(failure(e), 'error');
      return false;
    }
  }

  async close(id: string | null = this.activeId): Promise<boolean> {
    const doc = this.docs.find((d) => d.id === id);
    if (!doc) return false;
    if (doc.dirty) {
      const choice = await askSaveChanges(doc.name);
      if (choice === 'cancel') return false;
      if (choice === 'save' && !(await this.save(doc.id))) return false;
    }
    try {
      await api.closeDoc(doc.id, true);
    } catch (e) {
      toast(failure(e), 'error');
      return false;
    }
    this.docs = this.docs.filter((d) => d.id !== doc.id);
    if (this.activeId === doc.id) this.activeId = this.docs.length ? this.docs[this.docs.length - 1].id : null;
    this.emit();
    return true;
  }

  async closeAll(except?: string): Promise<boolean> {
    for (const d of [...this.docs]) {
      if (d.id === except) continue;
      this.switchTo(d.id);
      if (!(await this.close(d.id))) return false;
    }
    return true;
  }

  clearRecent(): void {
    writeHome({ recentClearedAt: Date.now() });
    this.recent = [];
    this.emit();
  }
}

export const docStore = new DocStore();
