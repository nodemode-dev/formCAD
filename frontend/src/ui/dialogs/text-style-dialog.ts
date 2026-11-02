import { el, q, setStyleVar } from '../dom';
import { checkField, comboField, numField } from './fields';
import { StyleManager } from './style-manager';
import type { StyleRecord } from './style-manager';

const STROKE = ['txt', 'simplex', 'romans', 'isocp', 'italic', 'complex'];
const FAMILIES = ['Arial', 'Times New Roman', 'Courier New', 'Verdana', 'Georgia', 'Calibri', 'DejaVu Sans'];

export class TextStyleDialog extends StyleManager {
  private readonly sample = el('<div class="u2-sample"><span>AaBbCc 123</span></div>');

  constructor() {
    super({ title: 'Text Style', table: 'textstyles', command: 'style', currentVar: 'TEXTSTYLE', width: 640 });
    const font = comboField('Font', [...STROKE, ...FAMILIES]);
    const big = comboField('Big font', STROKE);
    const height = numField('Height', { min: 0 });
    const width = numField('Width factor', { min: 0.01, max: 100 });
    const oblique = numField('Oblique angle', { min: -85, max: 85 });
    const back = checkField('Backwards');
    const down = checkField('Upside down');
    const vert = checkField('Vertical');
    const anno = checkField('Annotative');
    this.bind(font, 'font', (r) => String(r.font ?? 'txt'));
    this.bind(big, 'big_font', (r) => String(r.big_font ?? ''));
    this.bind(height, 'height', (r) => Number(r.height ?? 0));
    this.bind(width, 'width_factor', (r) => Number(r.width_factor ?? 1));
    this.bind(oblique, 'oblique', (r) => (Number(r.oblique ?? 0) * 180) / Math.PI, (f) => f.get());
    this.bind(back, 'backwards', (r) => !!r.backwards);
    this.bind(down, 'upside_down', (r) => !!r.upside_down);
    this.bind(vert, 'vertical', (r) => !!r.vertical);
    this.bind(anno, 'annotative', (r) => !!r.annotative);
    for (const f of [font, big, height, width, oblique, back, down, vert, anno]) this.props.appendChild(f.el);
    this.props.appendChild(this.sample);
    this.props.appendChild(el('<p class="cv-note">A height of 0 asks for the height each time text is placed.</p>'));
  }

  protected afterFill(rec: StyleRecord): void {
    const span = q(this.sample, 'span');
    const w = Number(rec.width_factor ?? 1);
    const ob = (Number(rec.oblique ?? 0) * 180) / Math.PI;
    setStyleVar(this.sample, '--u2-wf', String(w));
    setStyleVar(this.sample, '--u2-ob', `${-ob}deg`);
    setStyleVar(this.sample, '--u2-sx', rec.backwards ? '-1' : '1');
    setStyleVar(this.sample, '--u2-sy', rec.upside_down ? '-1' : '1');
    const family = String(rec.font ?? '');
    span.style.fontFamily = FAMILIES.includes(family) ? `"${family}"` : '';
  }

  protected editArgs(_rec: StyleRecord, key: string, value: unknown): Record<string, unknown> {
    return { [key]: value, current: false };
  }

  protected createArgs(base: StyleRecord | undefined, name: string): Record<string, unknown> {
    const out: Record<string, unknown> = { name, current: false };
    if (!base) return out;
    out.font = base.font;
    out.big_font = base.big_font;
    out.height = base.height;
    out.width_factor = base.width_factor;
    out.oblique = (Number(base.oblique ?? 0) * 180) / Math.PI;
    out.backwards = !!base.backwards;
    out.upside_down = !!base.upside_down;
    out.vertical = !!base.vertical;
    out.annotative = !!base.annotative;
    return out;
  }
}
