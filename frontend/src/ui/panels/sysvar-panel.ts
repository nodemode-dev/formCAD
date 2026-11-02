import { api, ApiError, type SysVar } from '../../io/api';
import { events } from '../../io/events';
import type { DockPanel } from '../dock';
import { el, patchList, q, setHidden, setText } from '../dom';
import { icon } from '../icons';
import { toast } from '../toast';

export interface SysvarPanelDeps {
  activeDoc: () => string | null;
  onDoc: (fn: () => void) => () => void;
}

const show = (v: unknown): string => {
  if (Array.isArray(v)) return v.join(', ');
  if (v === null || v === undefined) return '';
  return String(v);
};

export function sysvarPanel(deps: SysvarPanelDeps): DockPanel {
  return {
    id: 'sysvars',
    label: 'System Variables',
    icon: 'sliders',
    order: 20,
    grow: true,
    build(body) {
      body.classList.add('cv-sv');
      const bar = el(`<div class="cv-sv-bar"><input class="cv-input cv-sv-search" type="search" placeholder="Search variables" aria-label="Search variables" spellcheck="false" autocomplete="off"><button class="cv-icon-btn" type="button" title="Reload" aria-label="Reload">${icon('refresh', 14)}</button></div>`);
      const list = el('<div class="cv-sv-list" role="list"></div>');
      const note = el('<p class="cv-note cv-sv-note"></p>');
      body.append(bar, list, note);
      const search = q<HTMLInputElement>(bar, 'input');
      const vars = new Map<string, SysVar>();
      let filter = '';
      let loading = false;
      let docId: string | null = null;

      const matches = (v: SysVar): boolean => !filter || v.name.toLowerCase().includes(filter) || v.description.toLowerCase().includes(filter);

      const paintNote = (): void => {
        let shown = 0;
        for (const child of Array.from(list.children) as HTMLElement[]) if (!child.hidden) shown++;
        setText(note, vars.size === 0 ? 'The engine is not connected.' : shown === 0 ? 'No variable matches.' : `${shown} of ${vars.size} variables`);
      };

      const fill = (node: HTMLElement, v: SysVar): void => {
        const name = q(node, '.cv-sv-name');
        setText(name, v.name);
        name.title = v.description;
        const input = q<HTMLInputElement>(node, 'input');
        const text = show(v.value);
        if (document.activeElement !== input && input.value !== text) input.value = text;
        if (input.readOnly !== v.readonly) input.readOnly = v.readonly;
        node.classList.toggle('is-readonly', v.readonly);
        input.title = v.range ? `${v.description} (${v.range})` : v.description;
        setHidden(node, !matches(v));
      };

      const create = (v: SysVar): HTMLElement => {
        const node = el('<div class="cv-sv-row" role="listitem"><span class="cv-sv-name"></span><input class="cv-input cv-sv-value" type="text" spellcheck="false" autocomplete="off"></div>');
        const input = q<HTMLInputElement>(node, 'input');
        input.setAttribute('aria-label', v.name);
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
          else if (e.key === 'Escape') { e.preventDefault(); input.value = show(vars.get(v.name)?.value); input.blur(); }
        });
        input.addEventListener('change', () => { void commit(v.name, input); });
        fill(node, v);
        return node;
      };

      const commit = async (name: string, input: HTMLInputElement): Promise<void> => {
        const current = vars.get(name);
        if (!current || current.readonly) return;
        try {
          const r = await api.setSysvar(name, input.value.trim(), current.scope === 'drawing' ? deps.activeDoc() ?? undefined : undefined);
          vars.set(name, { ...current, value: r.value });
          input.value = show(r.value);
        } catch (e) {
          toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer', 'error');
          input.value = show(current.value);
        }
      };

      const paint = (): void => {
        patchList(list, Array.from(vars.values()), { key: (v) => v.name, create, update: fill });
        paintNote();
      };

      const reload = async (): Promise<void> => {
        if (loading) return;
        loading = true;
        try {
          const r = await api.sysvars();
          vars.clear();
          for (const v of r.vars) vars.set(v.name, v);
        } catch {
          return;
        } finally {
          loading = false;
        }
        paint();
      };

      search.addEventListener('input', () => {
        filter = search.value.trim().toLowerCase();
        for (const [name, v] of vars) {
          const node = list.querySelector<HTMLElement>(`[data-key="${name}"]`);
          if (node) setHidden(node, !matches(v));
        }
        paintNote();
      });
      q(bar, 'button').addEventListener('click', () => { void reload(); });
      events.on('sysvar', (e) => {
        if (typeof e.name !== 'string') return;
        const key = e.name.toUpperCase();
        const cur = vars.get(key);
        if (!cur) return;
        const next = { ...cur, value: e.value };
        vars.set(key, next);
        const node = list.querySelector<HTMLElement>(`[data-key="${key}"]`);
        if (node) fill(node, next);
      });
      events.onState((s) => { if (s === 'open') void reload(); });
      deps.onDoc(() => {
        const id = deps.activeDoc();
        if (id !== docId) { docId = id; void reload(); }
      });
      paintNote();
      void reload();
    },
  };
}
