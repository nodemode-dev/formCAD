import { Dialog } from '../ui/dialogs';
import { el, patchList, q, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { graphEditor } from '../graph';
import type { NodeRecord } from '../graph';
import { bake, layers } from './net';

const GEOMETRY = new Set(['point', 'curve', 'surface', 'brep', 'mesh', 'geometry']);

interface Row { id: string; title: string; count: number; kinds: string }

function rowsOf(): Row[] {
  const rec = graphEditor.record();
  if (!rec) return [];
  const out: Row[] = [];
  for (const n of rec.nodes) {
    const entry = graphEditor.store.entries.get(n.type);
    const ports = (entry?.outputs ?? []).filter((p) => GEOMETRY.has(p.kind));
    if (!ports.length) continue;
    const st = graphEditor.store.states.get(n.id);
    let count = 0;
    for (const p of ports) count += st?.outputs[p.name]?.items ?? 0;
    out.push({ id: n.id, title: titleOf(n, entry?.name ?? n.type), count, kinds: [...new Set(ports.map((p) => p.kind))].join(', ') });
  }
  return out;
}

const titleOf = (n: NodeRecord, fallback: string): string => (n.nickname ? `${n.nickname} (${fallback})` : fallback);

export class BakeDialog extends Dialog {
  private readonly list: HTMLElement;
  private readonly layer: HTMLInputElement;
  private readonly layerList: HTMLDataListElement;
  private readonly colour: HTMLInputElement;
  private readonly byLayer: HTMLInputElement;
  private readonly name: HTMLInputElement;
  private readonly count: HTMLElement;
  private readonly go: HTMLButtonElement;
  private readonly picked = new Set<string>();
  private busy = false;

  constructor() {
    super('Bake to Geometry', 480);
    this.body.appendChild(el('<p class="cv-note gp-bnote"></p>'));
    this.list = el('<div class="gp-blist is-scroll" role="group" aria-label="Outputs to bake"></div>');
    this.body.appendChild(this.list);
    this.layer = el<HTMLInputElement>('<input class="cv-input" type="text" list="gp-layers" spellcheck="false" autocomplete="off">');
    this.layerList = el<HTMLDataListElement>('<datalist id="gp-layers"></datalist>');
    this.field('Layer', this.layer).appendChild(this.layerList);
    const colourRow = el('<div class="cv-row-actions"></div>');
    this.colour = el<HTMLInputElement>('<input class="gp-colour" type="color" value="#f97316" aria-label="Colour">');
    this.byLayer = el<HTMLInputElement>('<input type="checkbox" checked aria-label="Use the layer colour">');
    const byLabel = el('<label class="cv-note gp-bylayer"><span></span></label>');
    byLabel.prepend(this.byLayer);
    setText(q(byLabel, 'span'), t('By layer'));
    colourRow.append(this.colour, byLabel);
    this.field('Colour', colourRow);
    this.name = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false" autocomplete="off">');
    this.field('Name', this.name);
    this.count = el('<p class="gp-bcount" role="status"></p>');
    this.body.appendChild(this.count);
    this.button('Cancel', 'ghost', () => this.close());
    this.go = this.button('Bake', 'primary', () => { void this.run(); });
    setText(q(this.body, '.gp-bnote'), t('Choose the outputs to turn into document objects. Baking again replaces the earlier objects of the same node in one undo step.'));
    this.byLayer.addEventListener('change', () => { this.colour.disabled = this.byLayer.checked; });
    this.colour.disabled = true;
    this.list.addEventListener('change', (e) => {
      const box = e.target as HTMLInputElement;
      const id = (box.closest('.gp-brow') as HTMLElement | null)?.dataset.key;
      if (!id) return;
      if (box.checked) this.picked.add(id); else this.picked.delete(id);
      this.total();
    });
  }

  async show(): Promise<void> {
    if (!graphEditor.gid()) { toast(t('Open a graph first.')); return; }
    const rows = rowsOf();
    this.picked.clear();
    const sel = new Set(graphEditor.selected());
    const withSel = rows.filter((r) => sel.has(r.id));
    for (const r of withSel.length ? withSel : rows) this.picked.add(r.id);
    this.paint(rows);
    if (!this.name.value) this.name.value = t('Graph object');
    this.open(this.go);
    try {
      const res = await layers();
      if (!this.layer.value) this.layer.value = res.current;
      patchList(this.layerList, res.layers, {
        key: (l) => l.name,
        create: () => document.createElement('option'),
        update: (o, l) => { (o as HTMLOptionElement).value = l.name; },
      });
    } catch { return; }
  }

  private paint(rows: Row[]): void {
    patchList(this.list, rows, {
      key: (r) => r.id,
      create: () => el('<label class="gp-brow"><input type="checkbox"><span class="gp-btitle"></span><span class="gp-bkind"></span><span class="gp-bn"></span></label>'),
      update: (node, r) => {
        const box = q<HTMLInputElement>(node, 'input');
        if (box.checked !== this.picked.has(r.id)) box.checked = this.picked.has(r.id);
        setText(q(node, '.gp-btitle'), r.title);
        setText(q(node, '.gp-bkind'), r.kinds);
        setText(q(node, '.gp-bn'), String(r.count));
        (node as HTMLElement & { _count?: number })._count = r.count;
      },
    });
    this.total();
  }

  private total(): void {
    let n = 0;
    for (const r of rowsOf()) if (this.picked.has(r.id)) n += r.count;
    setText(this.count, `${n} ${t('objects from')} ${this.picked.size} ${t('nodes')}`);
    setDisabled(this.go, this.busy || this.picked.size === 0);
  }

  private async run(): Promise<void> {
    if (this.busy || !this.picked.size) return;
    this.busy = true;
    setDisabled(this.go, true);
    try {
      await graphEditor.store.flush();
      const res = await bake(graphEditor.gid(), [...this.picked], { layer: this.layer.value.trim(), colour: this.colour.value, byLayer: this.byLayer.checked, name: this.name.value.trim() });
      const made = typeof res.baked === 'number' ? res.baked : 0;
      toast(`${t('Baked')} ${made} ${t('objects.')}${res.skipped?.length ? ` ${res.skipped.length} ${t('skipped.')}` : ''}`);
      this.close();
    } catch (e) {
      toast(e instanceof Error ? e.message : t('The bake failed.'), 'error');
    } finally {
      this.busy = false;
      this.total();
    }
  }
}
