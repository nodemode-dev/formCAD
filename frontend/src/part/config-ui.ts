import { events } from '../io/events';
import { param } from '../io/api-param';
import { Dialog, promptName } from '../ui/dialogs';
import type { DockPanel } from '../ui/dock';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { gate } from '../ui/panel-gate';
import { toast } from '../ui/toast';
import { part, type ConfigList, type DesignTable, type TableColumn, type TableRow } from './api';
import { messageOf, partStore } from './store';

export class DesignTableDialog extends Dialog {
  private cols: TableColumn[] = [];
  private rows: TableRow[] = [];
  private active = '';
  private readonly head: HTMLElement;
  private readonly body_: HTMLElement;
  private readonly adder: HTMLSelectElement;
  private readonly msg: HTMLElement;
  private readonly save: HTMLButtonElement;
  private readonly grid: HTMLElement;

  constructor() {
    super('Design Table', 760);
    this.body.appendChild(el(
      '<div class="dt"><div class="dt-bar"><select class="cv-input dt-add" aria-label="Add column"></select></div>' +
      '<div class="dt-wrap"><div class="dt-grid"><div class="dt-head dt-row"></div><div class="dt-body"></div></div></div>' +
      '<p class="dt-note"></p><p class="dt-msg" role="alert"></p></div>'));
    this.grid = q(this.body, '.dt-grid');
    this.head = q(this.body, '.dt-head');
    this.body_ = q(this.body, '.dt-body');
    this.adder = q<HTMLSelectElement>(this.body, '.dt-add');
    this.msg = q(this.body, '.dt-msg');
    setText(q(this.body, '.dt-note'), t('Each row is a configuration. An empty cell keeps the value the model already has. Material cells name a material from the library.'));
    this.button('Close', 'ghost', () => this.close());
    this.save = this.button('Apply', 'primary', () => { void this.apply(); });
    this.adder.addEventListener('change', () => this.addColumn());
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    await this.load(id);
    this.open();
  }

  private async load(id: string): Promise<void> {
    const grid: DesignTable = await part.table(id);
    this.cols = grid.columns.map((c) => ({ ...c }));
    this.rows = grid.rows.map((r) => ({ name: r.name, description: r.description, cells: { ...r.cells } }));
    this.active = grid.active;
    await this.options(id);
    this.paint();
  }

  private async options(id: string): Promise<void> {
    const have = new Set(this.cols.map((c) => c.id));
    const opts: Array<[string, string]> = [];
    try {
      for (const p of (await param.list(id)).parameters) if (!have.has(`param:${p.name}`)) opts.push([`param:${p.name}`, `${t('Parameter')} ${p.name}`]);
    } catch { /* parameters are optional */ }
    for (const f of partStore.features) if (f.type !== 'sketch' && !have.has(`suppress:${f.id}`) && !have.has(`suppress:${f.label}`)) opts.push([`suppress:${f.label}`, `${t('Suppress')} ${f.label}`]);
    try {
      for (const b of await part.bodies(id)) if (!have.has(`material:${b.handle}`)) opts.push([`material:${b.handle}`, `${t('Material of')} ${b.name}`]);
    } catch { /* bodies are optional */ }
    this.adder.replaceChildren(...[['', t('Add column...')] as [string, string], ...opts].map(([v, l]) => { const o = document.createElement('option'); o.value = v; o.textContent = l; return o; }));
  }

  private addColumn(): void {
    const v = this.adder.value;
    if (!v) return;
    const [kind, key] = [v.slice(0, v.indexOf(':')), v.slice(v.indexOf(':') + 1)];
    const label = this.adder.selectedOptions[0]?.textContent ?? key;
    this.cols.push({ id: v, kind, key, label: kind === 'material' ? label.replace(`${t('Material of')} `, '') : key });
    this.adder.querySelector(`option[value="${CSS.escape(v)}"]`)?.remove();
    this.adder.value = '';
    this.paint();
  }

  private paint(): void {
    this.grid.style.setProperty('--dt-cols', String(this.cols.length));
    const heads = [{ id: '__name', label: 'Configuration' }, { id: '__desc', label: 'Description' }, ...this.cols.map((c) => ({ id: c.id, label: c.kind === 'suppress' ? `${t('Suppress')} ${c.label}` : c.kind === 'material' ? `${t('Material')} ${c.label}` : c.label }))];
    patchList(this.head, heads, {
      key: (h) => h.id,
      create: (h) => el<HTMLElement>(`<span class="dt-h">${h.label}</span>`),
      update: (n, h) => setText(n, h.id.startsWith('__') ? t(h.label) : h.label),
    });
    patchList(this.body_, this.rows, {
      key: (r) => r.name,
      create: (r) => {
        const n = el<HTMLElement>('<div class="dt-row"></div>');
        n.dataset.name = r.name;
        return n;
      },
      update: (n, r) => {
        const cells = [{ id: '__name', v: r.name }, { id: '__desc', v: r.description }, ...this.cols.map((c) => ({ id: c.id, v: r.cells[c.id] ?? '' }))];
        patchList(n, cells, {
          key: (c) => c.id,
          create: (c) => {
            const input = el<HTMLInputElement>('<input class="cv-input dt-c" type="text" spellcheck="false" autocomplete="off">');
            input.addEventListener('input', () => {
              if (c.id === '__name') return;
              if (c.id === '__desc') { r.description = input.value; return; }
              if (input.value.trim()) r.cells[c.id] = input.value.trim(); else delete r.cells[c.id];
            });
            return input;
          },
          update: (i, c) => {
            const input = i as HTMLInputElement;
            if (c.id === '__name') input.readOnly = true;
            if (document.activeElement !== input && input.value !== c.v) input.value = c.v;
          },
        });
        n.classList.toggle('is-active', r.name === this.active);
      },
    });
  }

  private async apply(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    setDisabled(this.save, true);
    setText(this.msg, '');
    try {
      await part.tableSave(id, this.rows);
      partStore.refresh(0);
      await this.load(id);
      toast(t('The design table was applied.'));
    } catch (e) {
      setText(this.msg, messageOf(e));
    } finally {
      setDisabled(this.save, false);
    }
  }
}

export function configPanel(table: () => DesignTableDialog): DockPanel {
  return {
    id: 'configurations',
    label: 'Configurations',
    icon: 'ftConfig',
    order: -0.5,
    build: (body) => {
      body.appendChild(el(
        '<div class="cf"><div class="cf-row"><select class="cv-input cf-sel" aria-label="Active configuration"></select>' +
        `<button class="pt-tool cf-new" type="button">${icon('plus', 16)}</button><button class="pt-tool cf-table" type="button">${icon('ftTable', 16)}</button></div>` +
        '<p class="cf-msg" role="status"></p></div>'));
      const sel = q<HTMLSelectElement>(body, '.cf-sel');
      const msg = q(body, '.cf-msg');
      const bNew = q<HTMLButtonElement>(body, '.cf-new');
      const bTable = q<HTMLButtonElement>(body, '.cf-table');
      bNew.title = t('New configuration from the active one');
      bTable.title = t('Design table');
      let data: ConfigList | null = null;
      let busy = false;
      const paint = (): void => {
        const names = data?.configs.map((c) => c.name) ?? [];
        const have = Array.from(sel.options).map((o) => o.value);
        if (names.join('|') !== have.join('|')) {
          sel.replaceChildren(...names.map((n) => { const o = document.createElement('option'); o.value = n; o.textContent = n; return o; }));
        }
        if (data && sel.value !== data.active) sel.value = data.active;
        const row = data?.configs.find((c) => c.name === sel.value);
        setText(msg, row ? row.description : t('This part has no configurations yet.'));
        setDisabled(sel, !data || busy);
        setDisabled(bNew, !docStore.activeId);
        setDisabled(bTable, !docStore.activeId);
      };
      const load = async (): Promise<void> => {
        const id = docStore.activeId;
        if (!id) { data = null; paint(); return; }
        try { data = await part.configs(id); } catch { data = null; }
        paint();
      };
      sel.addEventListener('change', () => {
        const id = docStore.activeId;
        if (!id) return;
        busy = true;
        paint();
        part.configActivate(id, sel.value)
          .then(() => partStore.refresh(0))
          .catch((e: unknown) => toast(messageOf(e), 'error'))
          .finally(() => { busy = false; void load(); });
      });
      bNew.addEventListener('click', () => {
        const id = docStore.activeId;
        if (!id) return;
        void promptName(t('New Configuration'), '', t('Create')).then((name) => {
          if (!name) return;
          part.configAdd(id, { name, copy_from: data?.active }).catch((e: unknown) => toast(messageOf(e), 'error')).finally(() => { void load(); });
        });
      });
      bTable.addEventListener('click', () => { void table().showFor().catch((e: unknown) => toast(messageOf(e), 'error')); });
      let timer = 0;
      const allow = gate(['configurations'], ['part', 'assembly'], () => later());
      const later = (): void => { window.clearTimeout(timer); timer = window.setTimeout(() => { if (allow()) void load(); }, 160); };
      events.on('doc', (e) => { if (e.id === docStore.activeId) later(); });
      docStore.onChange(later);
      void load();
      return { show: later };
    },
  };
}
