import { api, type QSelectInfo } from '../../io/api';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setText } from '../dom';
import { toast } from '../toast';
import { failure } from './engine-run';
import { radioRow } from './pref-rows';
import { setOptions } from './prop-rows';
import { kindTitle } from './props-kinds';
import { selection } from './selection-bus';

type QuickProp = QSelectInfo['props'][number];

const OPERATORS: ReadonlyArray<readonly [string, string]> = [['=', '= Equals'], ['<>', '<> Not Equal'], ['>', '> Greater than'], ['<', '< Less than'], ['*', '* Wildcard Match']];

export class QuickSelectDialog extends Dialog {
  private readonly scope = el<HTMLSelectElement>('<select class="cv-input" aria-label="Apply to"></select>');
  private readonly type = el<HTMLSelectElement>('<select class="cv-input" aria-label="Object type"></select>');
  private readonly list = el<HTMLElement>('<div class="qs-list" role="listbox" aria-label="Properties"></div>');
  private readonly op = el<HTMLSelectElement>('<select class="cv-input" aria-label="Operator"></select>');
  private readonly value = el<HTMLInputElement>('<input class="cv-input" type="text" list="qs-values" spellcheck="false" autocomplete="off" aria-label="Value">');
  private readonly values = el<HTMLDataListElement>('<datalist id="qs-values"></datalist>');
  private readonly append: HTMLInputElement;
  private readonly count = el<HTMLElement>('<p class="cv-note qs-count" role="status"></p>');
  private info: QSelectInfo | null = null;
  private seq = 0;
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
    this.ok = this.button('OK', 'primary', () => { void this.apply(); });
    this.scope.addEventListener('change', () => { void this.load(true); });
    this.type.addEventListener('change', () => { void this.load(false); });
    this.op.addEventListener('change', () => this.fillValues());
    this.list.addEventListener('click', (e) => {
      const id = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (id) { this.propId = id; this.paintProps(); this.fillValues(); }
    });
    this.value.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.apply(); } });
  }

  async show(): Promise<void> {
    const doc = docStore.activeId;
    if (!doc) { toast('Open a drawing first.', 'info'); return; }
    this.open(this.value);
    this.ok.disabled = true;
    setText(this.count, 'Reading the drawing');
    const has = selection.handles.length > 0;
    this.scope.options[1].disabled = !has;
    if (!has && this.scope.value === 'sel') this.scope.value = 'all';
    await this.load(true);
  }

  private async load(types: boolean): Promise<void> {
    const doc = docStore.activeId;
    if (!doc) return;
    const mine = ++this.seq;
    try {
      const info = await api.qselectInfo(doc, this.scope.value, this.type.value);
      if (mine !== this.seq) return;
      this.info = info;
    } catch (e) {
      setText(this.count, failure(e));
      return;
    }
    this.ok.disabled = false;
    setText(this.count, '');
    if (!types) { this.fillProps(); return; }
    const keep = this.type.value;
    const kinds = this.info.kinds.slice().sort((a, b) => kindTitle(a.kind).localeCompare(kindTitle(b.kind)));
    setOptions(this.type, [['', 'Multiple'], ...kinds.map((k) => [k.kind, `${kindTitle(k.kind)} (${k.count})`] as const)]);
    this.type.value = kinds.some((k) => k.kind === keep) ? keep : '';
    if (this.type.value !== keep) void this.load(false);
    else this.fillProps();
  }

  private props(): QuickProp[] {
    return this.info?.props ?? [];
  }

  private paintProps(): void {
    const list = this.props();
    if (!list.length) return;
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
    const choices = prop?.choices ?? [];
    while (this.values.options.length > choices.length) this.values.removeChild(this.values.lastChild as Node);
    choices.forEach((c, i) => {
      let o = this.values.options[i];
      if (!o) { o = document.createElement('option'); this.values.appendChild(o); }
      if (o.value !== c) o.value = c;
    });
  }

  private async apply(): Promise<void> {
    const doc = docStore.activeId;
    if (!doc || this.ok.disabled) return;
    try {
      const out = await api.qselect(doc, {
        scope: this.scope.value === 'sel' ? 'sel' : 'all',
        kind: this.type.value,
        property: this.propId,
        operator: this.op.value,
        value: this.value.value.trim(),
        how: this.how,
        append: this.append.checked,
      });
      if (!out.count) { setText(this.count, 'No objects match the criteria.'); return; }
      selection.select(out.handles);
      this.close();
      toast(`${out.count} ${out.count === 1 ? 'object' : 'objects'} selected.`, 'info');
    } catch (e) {
      setText(this.count, failure(e));
    }
  }
}
