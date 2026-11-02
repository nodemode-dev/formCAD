import { checkField, numField, selectField, setOptions } from './fields';
import { ARROW_NAMES } from './arrows';
import { StyleManager } from './style-manager';
import type { StyleRecord } from './style-manager';

export class MleaderStyleDialog extends StyleManager {
  private readonly textStyle = selectField('Text style', [['Standard', 'Standard']]);

  constructor() {
    super({ title: 'Multileader Style', table: 'mleaderstyles', command: 'mleaderstyle', currentVar: 'CMLEADERSTYLE', width: 640 });
    const arrow = numField('Arrowhead size', { min: 0 });
    const height = numField('Text height', { min: 0 });
    const gap = numField('Landing gap', { min: 0 });
    const land = numField('Landing length', { min: 0 });
    const head = selectField('Arrowhead', ARROW_NAMES);
    const kind = selectField('Leader type', [['straight', 'Straight'], ['spline', 'Spline'], ['none', 'None']]);
    const landing = checkField('Landing');
    const content = selectField('Content type', [['mtext', 'Multiline text'], ['block', 'Block'], ['none', 'None']]);
    const points = numField('Maximum leader points', { min: 2, max: 100, int: true });
    const anno = checkField('Annotative');
    this.bind(arrow, 'arrow_size', (r) => Number(r.arrow_size ?? 0));
    this.bind(height, 'text_height', (r) => Number(r.text_height ?? 0));
    this.bind(gap, 'landing_gap', (r) => Number(r.landing_gap ?? 0));
    this.bind(land, 'dogleg', (r) => Number(r.dogleg ?? 0));
    this.bind(this.textStyle, 'text_style', (r) => String(r.text_style ?? 'Standard'));
    this.bind(head, 'arrowhead', (r) => String(r.arrowhead ?? 'closed filled'));
    this.bind(kind, 'leader_type', (r) => String(r.leader_type ?? 'straight'));
    this.bind(landing, 'landing', (r) => r.landing !== false);
    this.bind(content, 'content_type', (r) => String(r.content_type ?? 'mtext'));
    this.bind(points, 'max_points', (r) => Number(r.max_points ?? 2));
    this.bind(anno, 'annotative', (r) => !!r.annotative);
    for (const f of [arrow, height, gap, land, this.textStyle, head, kind, landing, content, points, anno]) this.props.appendChild(f.el);
  }

  protected afterFill(): void {
    const names = (this.tables?.textstyles ?? []).map((s) => String(s.name));
    setOptions(this.textStyle, names.map((n) => [n, n] as const));
    const rec = this.currentRecord();
    if (rec) this.textStyle.set(String(rec.text_style ?? 'Standard'));
  }

  protected createArgs(base: StyleRecord | undefined, name: string): Record<string, unknown> {
    const out: Record<string, unknown> = { action: 'create', name, current: false };
    if (!base) return out;
    for (const k of ['arrow_size', 'text_height', 'landing_gap', 'dogleg', 'text_style', 'annotative', 'arrowhead', 'leader_type', 'landing', 'content_type', 'max_points']) if (base[k] !== undefined) out[k] = base[k];
    return out;
  }
}
