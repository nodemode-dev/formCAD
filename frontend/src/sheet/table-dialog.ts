import { messageOf } from '../part/store';
import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { sheet, type BendTable, type TableRow, type TableSet } from './api';
import { sheetStore } from './store';
import { choiceRow, heading } from './ui';

interface SetDraft { id: number; thickness: string; radius: string; points: string }

let draftId = 0;

const parsePoints = (text: string): Array<[number, number]> => {
  const out: Array<[number, number]> = [];
  for (const line of text.split(/\r?\n/)) {
    const s = line.trim();
    if (!s) continue;
    const parts = s.split(/[\s,;]+/).filter(Boolean);
    if (parts.length !== 2) throw new Error(`${t('A point is two numbers')}: ${s}`);
    const a = Number(parts[0]);
    const b = Number(parts[1]);
    if (!Number.isFinite(a) || !Number.isFinite(b)) throw new Error(`${t('A point is two numbers')}: ${s}`);
    out.push([a, b]);
  }
  if (!out.length) throw new Error(t('Each set needs at least one point.'));
  return out;
};

export class TableDialog extends Dialog {
  private rows: TableRow[] = [];
  private current = '';
  private origin = 'document';
  private sets: SetDraft[] = [];
  private readonly pick: HTMLSelectElement;
  private readonly id: HTMLInputElement;
  private readonly name: HTMLInputElement;
  private readonly source: HTMLTextAreaElement;
  private readonly mode = choiceRow('Table gives', [['k', 'K-factor'], ['ba', 'Bend allowance (mm)'], ['bd', 'Bend deduction (mm)']], () => this.paintHead());
  private readonly axis = choiceRow('Looked up by', [['angle', 'Bend angle (degrees)'], ['ratio', 'Radius over thickness']], () => this.paintHead());
  private readonly list: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly saveBtn: HTMLButtonElement;
  private readonly delBtn: HTMLButtonElement;
  private readonly addSet: HTMLButtonElement;

  constructor() {
    super('Bend Tables', 680);
    const root = el(
      '<div class="sm-form sm-tables">' +
      '<div class="sm-bar"><select class="cv-input sm-pick" aria-label="Table"></select><button class="cv-btn sm-new" type="button"></button><button class="cv-btn sm-copy" type="button"></button></div>' +
      '<label class="sm-row"><span class="sm-lab"></span><span class="sm-slot"><input class="cv-input sm-in sm-id" type="text" spellcheck="false" autocomplete="off"></span><span class="sm-unit"></span></label>' +
      '<label class="sm-row"><span class="sm-lab"></span><span class="sm-slot"><input class="cv-input sm-in sm-name" type="text" spellcheck="false" autocomplete="off"></span><span class="sm-unit"></span></label>' +
      '<label class="sm-row sm-tall"><span class="sm-lab"></span><span class="sm-slot"><textarea class="cv-input sm-in sm-source" rows="2" spellcheck="false"></textarea></span><span class="sm-unit"></span></label>' +
      '</div>');
    this.pick = q<HTMLSelectElement>(root, '.sm-pick');
    this.id = q<HTMLInputElement>(root, '.sm-id');
    this.name = q<HTMLInputElement>(root, '.sm-name');
    this.source = q<HTMLTextAreaElement>(root, '.sm-source');
    const labs = root.querySelectorAll('.sm-lab');
    setText(labs[0] as HTMLElement, t('Table id'));
    setText(labs[1] as HTMLElement, t('Name'));
    setText(labs[2] as HTMLElement, t('Source of the values'));
    setText(q(root, '.sm-new'), t('New'));
    setText(q(root, '.sm-copy'), t('Copy'));
    root.append(this.mode.root, this.axis.root, heading('Sets'));
    this.list = el('<div class="sm-sets"></div>');
    this.msg = el('<p class="sm-msg" role="alert"></p>');
    this.addSet = el<HTMLButtonElement>('<button class="cv-btn sm-addset" type="button"></button>');
    setText(this.addSet, t('Add set'));
    root.append(this.list, this.addSet, this.msg);
    this.body.appendChild(root);
    this.button('Close', 'ghost', () => this.close());
    this.delBtn = this.button('Delete', 'ghost', () => { void this.remove(); });
    this.saveBtn = this.button('Save', 'primary', () => { void this.save(); });
    this.pick.addEventListener('change', () => { void this.load(this.pick.value); });
    q(root, '.sm-new').addEventListener('click', () => this.fresh(null));
    q(root, '.sm-copy').addEventListener('click', () => this.fresh(this.current));
    this.addSet.addEventListener('click', () => { this.readSets(); this.sets.push({ id: ++draftId, thickness: '', radius: '', points: '' }); this.paintSets(); });
    this.list.addEventListener('click', (e) => {
      const b = (e.target as HTMLElement).closest<HTMLElement>('.sm-rmset');
      if (!b) return;
      this.readSets();
      const id = Number(b.dataset.id);
      this.sets = this.sets.filter((s) => s.id !== id);
      this.paintSets();
    });
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    await this.reload(this.current);
    this.open();
  }

  private async reload(select: string): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const raw = await sheet.tables(id);
    this.rows = Array.isArray(raw) ? raw : raw.tables;
    patchList<TableRow>(this.pick, this.rows, {
      key: (r) => r.id,
      create: (r) => { const o = document.createElement('option'); o.value = r.id; return o; },
      update: (n, r) => setText(n, `${r.name || r.id}  (${t(r.origin === 'document' ? 'document' : r.origin === 'builtin' ? 'built in' : 'library')})`),
    });
    const want = this.rows.some((r) => r.id === select) ? select : (this.rows[0]?.id ?? '');
    if (want) await this.load(want);
    else this.fresh(null);
  }

  private async load(tid: string): Promise<void> {
    const id = docStore.activeId;
    if (!id || !tid) return;
    setText(this.msg, '');
    try {
      const tb = await sheet.table(id, tid);
      this.current = tid;
      this.origin = tb.origin ?? this.rows.find((r) => r.id === tid)?.origin ?? 'document';
      this.pick.value = tid;
      this.fill(tid, tb);
    } catch (e) {
      setText(this.msg, messageOf(e));
    }
  }

  private fill(tid: string, tb: BendTable): void {
    this.id.value = tid;
    this.name.value = tb.name ?? '';
    this.source.value = tb.source ?? '';
    this.mode.set(tb.mode);
    this.axis.set(tb.axis);
    this.sets = tb.sets.map((s: TableSet) => ({
      id: ++draftId,
      thickness: s.thickness === undefined ? '' : String(s.thickness),
      radius: s.radius === undefined ? '' : String(s.radius),
      points: s.points.map((p) => `${p[0]} ${p[1]}`).join('\n'),
    }));
    this.paintSets();
    this.paintHead();
  }

  private fresh(from: string | null): void {
    if (from === null) {
      this.current = '';
      this.id.value = '';
      this.name.value = '';
      this.source.value = '';
      this.mode.set('k');
      this.axis.set('angle');
      this.sets = [{ id: ++draftId, thickness: '', radius: '', points: '' }];
    } else {
      this.readSets();
      this.id.value = `${from}-copy`;
      this.current = '';
    }
    this.origin = 'document';
    this.paintSets();
    this.paintHead();
    setText(this.msg, '');
  }

  private readonly_(): boolean { return this.origin !== 'document'; }

  private paintHead(): void {
    const ro = this.readonly_();
    for (const n of [this.id, this.name, this.source]) if (n.disabled !== ro) n.disabled = ro;
    this.mode.use(!ro);
    this.axis.use(!ro);
    setDisabled(this.saveBtn, ro && this.id.value === this.current);
    setDisabled(this.delBtn, ro || !this.current);
    setDisabled(this.addSet, ro);
    const ratio = this.axis.get() === 'ratio';
    const valueWord = this.mode.get() === 'k' ? t('K') : this.mode.get() === 'ba' ? t('BA mm') : t('BD mm');
    for (const ta of Array.from(this.list.querySelectorAll<HTMLTextAreaElement>('.sm-points'))) ta.placeholder = `${ratio ? t('R/T') : t('angle deg')}  ${valueWord}`;
    if (ro) setText(this.msg, t('This table is read only. Use Copy to make an editable one.'));
  }

  private paintSets(): void {
    const ro = this.readonly_();
    patchList<SetDraft>(this.list, this.sets, {
      key: (s) => String(s.id),
      create: (s) => {
        const n = el<HTMLElement>(
          `<div class="sm-set"><div class="sm-set-top"><label>${t('Thickness')}<input class="cv-input sm-th" type="text" inputmode="decimal" placeholder="${t('any')}"></label>` +
          `<label>${t('Radius')}<input class="cv-input sm-ra" type="text" inputmode="decimal" placeholder="${t('any')}"></label>` +
          `<button class="cv-btn sm-rmset" type="button" data-id="${s.id}">${t('Remove')}</button></div>` +
          '<textarea class="cv-input sm-points" rows="4" spellcheck="false"></textarea></div>');
        n.dataset.id = String(s.id);
        return n;
      },
      update: (n, s) => {
        const th = q<HTMLInputElement>(n, '.sm-th');
        const ra = q<HTMLInputElement>(n, '.sm-ra');
        const pt = q<HTMLTextAreaElement>(n, '.sm-points');
        if (th.value !== s.thickness) th.value = s.thickness;
        if (ra.value !== s.radius) ra.value = s.radius;
        if (pt.value !== s.points) pt.value = s.points;
        for (const c of [th, ra, pt, q<HTMLButtonElement>(n, '.sm-rmset')]) if (c.disabled !== ro) c.disabled = ro;
      },
    });
    this.paintHead();
  }

  private readSets(): void {
    for (const n of Array.from(this.list.querySelectorAll<HTMLElement>('.sm-set'))) {
      const s = this.sets.find((x) => x.id === Number(n.dataset.id));
      if (!s) continue;
      s.thickness = q<HTMLInputElement>(n, '.sm-th').value;
      s.radius = q<HTMLInputElement>(n, '.sm-ra').value;
      s.points = q<HTMLTextAreaElement>(n, '.sm-points').value;
    }
  }

  private collect(): BendTable {
    this.readSets();
    if (!this.source.value.trim()) throw new Error(t('Name where the values come from. A table without a source is not saved.'));
    const sets: TableSet[] = this.sets.map((s) => {
      const out: TableSet = { points: parsePoints(s.points) };
      if (s.thickness.trim()) out.thickness = Number(s.thickness);
      if (s.radius.trim()) out.radius = Number(s.radius);
      if ((out.thickness !== undefined && !Number.isFinite(out.thickness)) || (out.radius !== undefined && !Number.isFinite(out.radius))) throw new Error(t('Thickness and radius are numbers.'));
      return out;
    });
    if (!sets.length) throw new Error(t('Add at least one set.'));
    return { name: this.name.value.trim(), mode: this.mode.get() as BendTable['mode'], axis: this.axis.get() as BendTable['axis'], source: this.source.value.trim(), sets };
  }

  private async save(): Promise<void> {
    const doc = docStore.activeId;
    const tid = this.id.value.trim();
    if (!doc) return;
    setText(this.msg, '');
    try {
      if (!tid) throw new Error(t('Give the table an id.'));
      const body = this.collect();
      await sheet.putTable(doc, tid, body);
      this.current = tid;
      this.origin = 'document';
      await this.reload(tid);
      sheetStore.refresh(0);
      toast(t('The bend table was saved.'));
    } catch (e) {
      setText(this.msg, messageOf(e));
    }
  }

  private async remove(): Promise<void> {
    const doc = docStore.activeId;
    if (!doc || !this.current) return;
    try {
      await sheet.removeTable(doc, this.current);
      this.current = '';
      await this.reload('');
      sheetStore.refresh(0);
    } catch (e) {
      setText(this.msg, messageOf(e));
    }
  }
}
