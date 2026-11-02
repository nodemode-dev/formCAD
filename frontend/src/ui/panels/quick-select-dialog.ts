import { drawingCanvas } from '../../canvas/mount';
import { api } from '../../io/api';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setText } from '../dom';
import { toast } from '../toast';
import { failure } from './engine-run';
import { radioRow } from './pref-rows';
import { setOptions } from './prop-rows';
import { kindTitle } from './props-kinds';
import { matches, propsFor, type Operator, type QuickProp, type Rec } from './quick-select-model';
import { selection } from './selection-bus';

const OPERATORS: ReadonlyArray<readonly [Operator, string]> = [['=', '= Equals'], ['<>', '<> Not Equal'], ['>', '> Greater than'], ['<', '< Less than'], ['*', '* Wildcard Match']];
const BASIC_COLORS = ['ByLayer', 'ByBlock', 'Red', 'Yellow', 'Green', 'Cyan', 'Blue', 'Magenta', 'White'];

export class QuickSelectDialog extends Dialog {
  private readonly scope = el<HTMLSelectElement>('<select class="cv-input" aria-label="Apply to"></select>');
  private readonly type = el<HTMLSelectElement>('<select class="cv-input" aria-label="Object type"></select>');
  private readonly list = el<HTMLElement>('<div class="qs-list" role="listbox" aria-label="Properties"></div>');
  private readonly op = el<HTMLSelectElement>('<select class="cv-input" aria-label="Operator"></select>');
  private readonly value = el<HTMLInputElement>('<input class="cv-input" type="text" list="qs-values" spellcheck="false" autocomplete="off" aria-label="Value">');
  private readonly values = el<HTMLDataListElement>('<datalist id="qs-values"></datalist>');
  private readonly append: HTMLInputElement;
  private readonly count = el<HTMLElement>('<p class="cv-note qs-count" role="status"></p>');
  private records = new Map<number, Rec>();
  private how: 'include' | 'exclude' = 'include';
  private propId = 'color';
  private readonly ok: HTMLButtonElement;

  constructor() {
    super('Quick Select', 380);
    this.field('Apply to', this.scope);
    this.field('Object type', this.type);
    const listRow = el<HTMLElement>('<div class="cv-field qs-listrow"><span>Properties</span></div>');
    listRow.appendChild(this.list);
    this.body.appendChild(listRow);
    this.field('Operator', this.op);
    const valueRow = this.field('Value', this.value);
    valueRow.appendChild(this.values);
    const how = radioRow('How to apply', [['include', 'Include in new selection set'], ['exclude', 'Exclude from new selection set']], (v) => { this.how = v === 'exclude' ? 'exclude' : 'include'; });
    how.set('include');
    this.body.appendChild(how.el);
    const app = el<HTMLLabelElement>('<label class="cv-field cv-check"><span>Append to current selection set</span><input type="checkbox"></label>');
    this.append = q<HTMLInputElement>(app, 'input');
    this.body.append(app, this.count);
    setOptions(this.scope, [['all', 'Entire drawing'], ['sel', 'Current selection']]);
    setOptions(this.op, OPERATORS.map(([k, label]) => [k, label] as const));
    this.button('Cancel', 'ghost', () => this.close());
    this.ok = this.button('OK', 'primary', () => this.apply());
    this.scope.addEventListener('change', () => this.fillTypes());
    this.type.addEventListener('change', () => this.fillProps());
    this.op.addEventListener('change', () => this.fillValues());
    this.list.addEventListener('click', (e) => {
      const id = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (id) { this.propId = id; this.paintProps(); this.fillValues(); }
    });
    this.value.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.apply(); } });
  }

  async show(): Promise<void> {
    const doc = docStore.activeId;
    if (!doc) { toast('Open a drawing first.', 'info'); return; }
    this.open(this.value);
    this.ok.disabled = true;
    setText(this.count, 'Reading the drawing');
    try {
      const snap = await api.snapshot(doc);
      const cv = drawingCanvas();
      this.records = new Map();
      for (const raw of snap.entities as unknown as Rec[]) {
        const h = Number(raw.handle);
        if (Number.isFinite(h) && (!cv || cv.item(h))) this.records.set(h, raw);
      }
    } catch (e) {
      setText(this.count, failure(e));
      return;
    }
    const has = selection.handles.length > 0;
    this.scope.options[1].disabled = !has;
    if (!has && this.scope.value === 'sel') this.scope.value = 'all';
    this.ok.disabled = false;
    setText(this.count, '');
    this.fillTypes();
  }

  private scoped(): Rec[] {
    if (this.scope.value === 'sel') {
      const keep = new Set(selection.handles);
      return Array.from(this.records.entries()).filter(([h]) => keep.has(h)).map(([, r]) => r);
    }
    return Array.from(this.records.values());
  }

  private fillTypes(): void {
    const counts = new Map<string, number>();
    for (const r of this.scoped()) counts.set(String(r.kind), (counts.get(String(r.kind)) ?? 0) + 1);
    const kinds = Array.from(counts.keys()).sort((a, b) => kindTitle(a).localeCompare(kindTitle(b)));
    const keep = this.type.value;
    setOptions(this.type, [['', 'Multiple'], ...kinds.map((k) => [k, `${kindTitle(k)} (${counts.get(k)})`] as const)]);
    this.type.value = kinds.includes(keep) ? keep : '';
    this.fillProps();
  }

  private props(): QuickProp[] {
    return propsFor(this.type.value || null);
  }

  private paintProps(): void {
    const list = this.props();
    if (!list.some((p) => p.id === this.propId)) this.propId = list[0].id;
    patchList(this.list, list, {
      key: (p) => p.id,
      create: (p) => {
        const node = el<HTMLElement>('<button class="qs-prop" type="button" role="option"></button>');
        setText(node, p.label);
        setClass(node, 'is-chosen', p.id === this.propId);
        return node;
      },
      update: (node, p) => {
        setText(node, p.label);
        setClass(node, 'is-chosen', p.id === this.propId);
        node.setAttribute('aria-selected', String(p.id === this.propId));
      },
    });
  }

  private fillProps(): void {
    this.propId = this.props().some((p) => p.id === this.propId) ? this.propId : 'color';
    this.paintProps();
    this.fillValues();
  }

  private fillValues(): void {
    const prop = this.props().find((p) => p.id === this.propId);
    const wild = this.op.value === '*';
    this.value.placeholder = wild ? 'Pattern, for example *wall*' : '';
    let choices: string[] = [];
    if (prop?.choices === 'color') choices = BASIC_COLORS;
    else if (prop?.choices) {
      const seen = new Set<string>();
      for (const r of this.scoped()) {
        const v = prop.get(r);
        if (v !== null) seen.add(String(v));
      }
      choices = Array.from(seen).sort();
    }
    while (this.values.options.length > choices.length) this.values.removeChild(this.values.lastChild as Node);
    choices.forEach((c, i) => {
      let o = this.values.options[i];
      if (!o) { o = document.createElement('option'); this.values.appendChild(o); }
      if (o.value !== c) o.value = c;
    });
  }

  private apply(): void {
    const prop = this.props().find((p) => p.id === this.propId);
    const kind = this.type.value;
    const typed = this.value.value.trim();
    const wild = this.op.value === '*';
    const scope = this.scoped();
    const ofType = scope.filter((r) => !kind || r.kind === kind);
    const useCriterion = !!prop && (typed !== '' || wild);
    const hit = new Set<number>();
    for (const r of ofType) if (!useCriterion || (prop && matches(prop.get(r), this.op.value as Operator, typed))) hit.add(Number(r.handle));
    let result: number[];
    if (this.how === 'include') result = Array.from(hit);
    else result = scope.map((r) => Number(r.handle)).filter((h) => !hit.has(h));
    if (this.append.checked) result = Array.from(new Set([...selection.handles, ...result]));
    if (!result.length) { setText(this.count, 'No objects match the criteria.'); return; }
    selection.select(result);
    this.close();
    toast(`${result.length} ${result.length === 1 ? 'object' : 'objects'} selected.`, 'info');
  }
}
