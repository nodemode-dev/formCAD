import { Dialog } from '../ui/dialogs';
import { el, q, setClass, setText, setTitle } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { events } from '../io/events';
import { graphBus, graphEditor } from '../graph';
import type { NodeWidget, NodeWidgetContext } from '../graph';
import { itemsOf, lines, scalar, stopAll, firstOf } from './wutil';

const wired = (id: string): boolean => !!graphEditor.record()?.wires.some((w) => w.to.node === id);

export function panelWidget(ctx: NodeWidgetContext): NodeWidget {
  const root = el('<div class="gp-panel"><textarea class="gp-ptext is-scroll" spellcheck="false" aria-label="Panel text"></textarea><pre class="gp-pview is-scroll" hidden></pre></div>');
  ctx.host.appendChild(root);
  stopAll(root);
  const area = q<HTMLTextAreaElement>(root, 'textarea');
  const view = q<HTMLElement>(root, 'pre');
  let typing = false;
  let dirty = false;
  let seq = '';
  let isWired = false;

  const values = (): string[] => (area.value === '' ? [] : area.value.split('\n'));
  area.addEventListener('focus', () => { typing = true; });
  area.addEventListener('input', () => { dirty = true; ctx.edit({ persistent: { port: 'text', tree: lines('text', values()) } }, { live: true }); });
  area.addEventListener('blur', () => {
    typing = false;
    if (!dirty) return;
    dirty = false;
    ctx.edit({ persistent: { port: 'text', tree: lines('text', values()) } });
  });

  const mode = (): void => {
    const now = wired(ctx.nodeId);
    if (now === isWired && root.dataset.ready) return;
    isWired = now;
    root.dataset.ready = '1';
    area.hidden = now;
    view.hidden = !now;
    seq = '';
  };

  const pull = (key: string): void => {
    if (key === seq) return;
    seq = key;
    void ctx.tree('text', 0).then((page) => {
      if (seq !== key) return;
      const rows: string[] = [];
      for (const b of page.branches) {
        rows.push(`${b.path} (${b.count})`);
        b.items.forEach((it, i) => { rows.push(`  [${i}] ${it}`); });
      }
      if (page.total > page.branches.length) rows.push(`... ${page.total - page.branches.length} ${t('more branches')}`);
      setText(view, rows.join('\n'));
    }).catch(() => { setText(view, ''); });
  };

  const off = [graphBus.on('wire-added', () => { mode(); }), graphBus.on('wire-removed', () => { mode(); })];

  return {
    size: { w: 208, h: 104 },
    update(node, state) {
      mode();
      if (isWired) {
        const o = state.outputs.text;
        pull(state.state === 'computed' && o ? `${o.count}|${o.items}|${o.first.join('\u0001')}` : `${state.state}`);
        return;
      }
      if (typing) return;
      const text = itemsOf(node.inputs.find((p) => p.name === 'text')?.persistent).map((v) => String(v)).join('\n');
      if (area.value !== text) area.value = text;
    },
    dispose() { for (const f of off) f(); },
  };
}

export function toggleWidget(ctx: NodeWidgetContext): NodeWidget {
  const root = el('<button class="gp-toggle" type="button" role="switch" aria-checked="false"><span class="gp-tsw"><span class="gp-tknob"></span></span><span class="gp-tlabel"></span></button>');
  ctx.host.appendChild(root);
  stopAll(root);
  const label = q(root, '.gp-tlabel');
  let on = false;
  const paint = (): void => {
    setClass(root, 'is-on', on);
    root.setAttribute('aria-checked', String(on));
    setText(label, on ? t('True') : t('False'));
  };
  root.addEventListener('click', () => {
    on = !on;
    paint();
    ctx.edit({ persistent: { port: 'value', tree: scalar('boolean', on) } });
  });
  return {
    size: { w: 168, h: 26 },
    update(node) {
      on = firstOf(node.inputs.find((p) => p.name === 'value')?.persistent) === true;
      paint();
    },
  };
}

export function buttonWidget(ctx: NodeWidgetContext): NodeWidget {
  const root = el<HTMLButtonElement>(`<button class="gp-pulse" type="button">${icon('gcButton', 14)}<span></span></button>`);
  ctx.host.appendChild(root);
  stopAll(root);
  setText(q(root, 'span:not(.icon)'), t('Press'));
  let busy = false;
  const release = (): void => {
    ctx.edit({ persistent: { port: 'pressed', tree: scalar('boolean', false) } });
    busy = false;
    setClass(root, 'is-down', false);
  };
  root.addEventListener('click', () => {
    if (busy) return;
    busy = true;
    setClass(root, 'is-down', true);
    let done = false;
    const finish = (): void => { if (done) return; done = true; off(); window.clearTimeout(timer); release(); };
    const off = events.on('graph', (e) => { if (e.graph === graphEditor.gid() && e.reason === 'solved') finish(); });
    const timer = window.setTimeout(finish, 4000);
    ctx.edit({ persistent: { port: 'pressed', tree: scalar('boolean', true) } });
  });
  return { size: { w: 168, h: 26 }, update() { return; } };
}

interface Entry { name: string; value: string | number | boolean }

const parseValue = (raw: string): string | number | boolean => {
  const s = raw.trim();
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s !== '' && Number.isFinite(Number(s))) return Number(s);
  return s;
};

class EntryEditor extends Dialog {
  private readonly area: HTMLTextAreaElement;
  private owner: NodeWidgetContext | null = null;

  constructor() {
    super('Value List Entries', 420);
    this.area = el<HTMLTextAreaElement>('<textarea class="cv-input gp-entries" spellcheck="false" aria-label="Entries"></textarea>');
    this.body.appendChild(el('<p class="cv-note">One entry per line as name = value. A value that reads as a number or true or false is stored as that type.</p>'));
    this.body.appendChild(this.area);
    this.button('Cancel', 'ghost', () => this.close());
    this.button('Apply', 'primary', () => this.apply());
  }

  open2(ctx: NodeWidgetContext): void {
    this.owner = ctx;
    const items = (ctx.settings().items as Entry[] | undefined) ?? [];
    this.area.value = items.map((e) => `${e.name} = ${String(e.value)}`).join('\n');
    this.open(this.area);
  }

  private apply(): void {
    const ctx = this.owner;
    if (!ctx) return;
    const items: Entry[] = [];
    for (const row of this.area.value.split('\n')) {
      if (!row.trim()) continue;
      const at = row.indexOf('=');
      const name = (at < 0 ? row : row.slice(0, at)).trim();
      const value = at < 0 ? name : row.slice(at + 1);
      items.push({ name, value: parseValue(value) });
    }
    const cur = ctx.settings().selected;
    const keep = Array.isArray(cur) ? cur.filter((i) => typeof i === 'number' && i < items.length) : typeof cur === 'number' && cur < items.length ? cur : 0;
    ctx.edit({ settings: { items, selected: keep } });
    this.close();
  }
}

let entries: EntryEditor | null = null;

export function valueListWidget(ctx: NodeWidgetContext): NodeWidget {
  const root = el(`<div class="gp-vlist"><select class="gp-vsel" aria-label="Selected entry"></select><button class="gp-sbtn" type="button" aria-label="Edit entries">${icon('gcValueList', 14)}</button></div>`);
  ctx.host.appendChild(root);
  stopAll(root);
  const sel = q<HTMLSelectElement>(root, 'select');
  setTitle(q(root, 'button'), t('Edit entries'));
  let key = '';
  sel.addEventListener('change', () => { ctx.edit({ settings: { selected: Number(sel.value) } }); });
  q(root, 'button').addEventListener('click', () => { entries ??= new EntryEditor(); entries.open2(ctx); });
  return {
    size: { w: 168, h: 26 },
    update(node) {
      const items = (node.settings.items as Entry[] | undefined) ?? [];
      const names = items.map((e) => `${e.name}`);
      const k = names.join('\u0001');
      if (k !== key) {
        key = k;
        sel.replaceChildren(...names.map((n, i) => { const o = document.createElement('option'); o.value = String(i); o.textContent = n; return o; }));
      }
      const s = node.settings.selected;
      const at = Array.isArray(s) ? Number(s[0] ?? 0) : typeof s === 'number' ? s : 0;
      if (sel.value !== String(at)) sel.value = String(at);
    },
  };
}
