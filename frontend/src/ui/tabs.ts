import type { DocSummary } from '../io/api';
import type { DocStore } from './doc-store';
import { el, patchList, q, setClass, setText, setTitle } from './dom';
import { icon } from './icons';
import { t } from './i18n';

export interface TabsDeps {
  docs: DocStore;
  close: (id: string) => void;
  menu?: (id: string, x: number, y: number) => void;
  docTitle?: HTMLElement;
}

const APP_NAME = 'FormCAD';

export class Tabs {
  private activeId: string | null = null;
  private windowTitle: string | null = null;
  private home = false;
  private frame = 0;

  constructor(private readonly strip: HTMLElement, private readonly d: TabsDeps) {
    d.docs.onChange(() => this.queue());
    const tabOf = (e: Event): HTMLElement | null => (e.target as HTMLElement).closest<HTMLElement>('.cv-tab[data-key]');
    strip.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      const tab = tabOf(e);
      if (!tab || (e.target as HTMLElement).closest('.cv-tab-close')) return;
      d.docs.switchTo(tab.dataset.key as string);
    });
    strip.addEventListener('auxclick', (e) => {
      if (e.button !== 1) return;
      const tab = tabOf(e);
      if (!tab) return;
      e.preventDefault();
      d.close(tab.dataset.key as string);
    });
    strip.addEventListener('contextmenu', (e) => {
      const tab = tabOf(e);
      if (!tab || !d.menu) return;
      e.preventDefault();
      d.docs.switchTo(tab.dataset.key as string);
      d.menu(tab.dataset.key as string, e.clientX, e.clientY);
    });
    strip.addEventListener('click', (e) => {
      if (!(e.target as HTMLElement).closest('.cv-tab-close')) return;
      const tab = tabOf(e);
      if (tab) d.close(tab.dataset.key as string);
    });
    this.render();
  }

  setHome(shown: boolean): void {
    if (this.home === shown) return;
    this.home = shown;
    this.render();
  }

  private queue(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; this.render(); });
  }

  render(): void {
    const current = this.d.docs.current();
    patchList(this.strip, this.d.docs.docs, {
      key: (doc) => doc.id,
      create: (doc) => {
        const n = el(`<div class="cv-tab" role="tab"><span class="cv-tab-dot"></span><span class="cv-tab-name"></span><button class="cv-tab-close" type="button" aria-label="Close tab">${icon('close', 12)}</button></div>`);
        n.dataset.key = doc.id;
        this.update(n, doc, current);
        return n;
      },
      update: (n, doc) => this.update(n, doc, current),
    });
    const shown = current ? `${current.dirty ? '• ' : ''}${current.name}` : '';
    setText(this.d.docTitle ?? null, shown);
    const title = this.home ? `Start - ${APP_NAME}` : current ? `${shown} - ${APP_NAME}` : APP_NAME;
    if (this.windowTitle !== title) {
      this.windowTitle = title;
      document.title = title;
      if ('__TAURI_INTERNALS__' in window) void import('@tauri-apps/api/core').then((m) => m.invoke('set_window_title', { title })).catch(() => undefined);
    }
    if ((current?.id ?? null) !== this.activeId) {
      this.activeId = current?.id ?? null;
      const tab = this.activeId ? this.strip.querySelector<HTMLElement>(`.cv-tab[data-key="${CSS.escape(this.activeId)}"]`) : null;
      tab?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }

  private update(n: HTMLElement, doc: DocSummary, current: DocSummary | null): void {
    setText(q(n, '.cv-tab-name'), doc.name);
    const active = !!current && doc.id === current.id;
    setClass(n, 'is-active', active);
    setClass(n, 'is-dirty', doc.dirty);
    const sel = active ? 'true' : 'false';
    if (n.getAttribute('aria-selected') !== sel) n.setAttribute('aria-selected', sel);
    setTitle(n, doc.path ? `${doc.name} · ${doc.path}` : `${doc.name} · ${t('not saved yet')}`);
    setTitle(q(n, '.cv-tab-close'), `${t('Close')} ${doc.name}`);
  }
}
