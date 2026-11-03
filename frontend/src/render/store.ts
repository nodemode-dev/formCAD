import { docStore } from '../ui/doc-store';
import * as net from './net';

type Listener = () => void;

export class RenderStore {
  docId: string | null = null;
  settings: net.RenderSettings | null = null;
  limits: net.Limits | null = null;
  library: net.Library | null = null;
  envs: net.EnvListing | null = null;
  rows: net.RenderBodyRow[] = [];
  decals: net.Decal[] = [];
  error = '';
  private readonly listeners = new Set<Listener>();
  private token = 0;

  on(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  async load(): Promise<void> {
    const id = docStore.activeId;
    const mine = ++this.token;
    if (!id) {
      this.docId = null;
      this.rows = [];
      this.decals = [];
      this.emit();
      return;
    }
    try {
      const [lib, envs, set, bodies, dec] = await Promise.all([
        this.library ? Promise.resolve(this.library) : net.library(),
        net.environments(),
        net.getSettings(id),
        net.renderBodies(id),
        net.decals(id),
      ]);
      if (mine !== this.token) return;
      this.docId = id;
      this.library = lib;
      this.envs = envs;
      this.settings = set.settings;
      this.limits = set.limits;
      this.rows = bodies.bodies;
      this.decals = dec.decals;
    } catch (e) {
      if (mine !== this.token) return;
      this.error = e instanceof Error ? e.message : 'The render data could not be read.';
    }
    this.emit();
  }

  async patch(patch: Record<string, unknown>): Promise<boolean> {
    if (!this.docId) return false;
    try {
      const r = await net.putSettings(this.docId, patch);
      this.settings = r.settings;
      this.limits = r.limits;
      this.error = '';
      this.emit();
      return true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The setting was refused.';
      this.emit();
      return false;
    }
  }

  async assign(keys: string[], appearance: string | null): Promise<void> {
    if (!this.docId || !keys.length) return;
    try {
      await net.assign(this.docId, keys, appearance);
      const b = await net.renderBodies(this.docId);
      this.rows = b.bodies;
      this.error = '';
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The appearance could not be assigned.';
    }
    this.emit();
  }

  async addAppearance(row: Partial<net.Appearance> & { name: string }): Promise<boolean> {
    try {
      await net.addAppearance(row);
      this.library = await net.library();
      this.error = '';
      this.emit();
      return true;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The appearance was refused.';
      this.emit();
      return false;
    }
  }

  async addDecal(d: Partial<net.Decal> & { name: string }): Promise<void> {
    if (!this.docId) return;
    try {
      await net.addDecal(this.docId, d);
      this.decals = (await net.decals(this.docId)).decals;
      this.error = '';
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The decal was refused.';
    }
    this.emit();
  }

  async removeDecal(name: string): Promise<void> {
    if (!this.docId) return;
    try {
      await net.removeDecal(this.docId, name);
      this.decals = (await net.decals(this.docId)).decals;
      this.error = '';
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'The decal could not be removed.';
    }
    this.emit();
  }

  appearance(name: string): net.Appearance | undefined {
    return this.library?.appearances.find((a) => a.name === name);
  }
}

export const renderStore = new RenderStore();
