import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { part, type BodyRow, type MassResult, type MaterialRow } from './api';
import { messageOf } from './store';

const sig = (v: number | null | undefined, digits = 9): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '';
  if (v === 0) return '0';
  const a = Math.abs(v);
  return a >= 1e7 || a < 1e-3 ? v.toExponential(digits - 1) : String(Number(v.toPrecision(digits)));
};

export class MaterialDialog extends Dialog {
  private bodies: BodyRow[] = [];
  private mats: MaterialRow[] = [];
  private current = 0;
  private readonly bodySel: HTMLSelectElement;
  private readonly list: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly assign: HTMLButtonElement;
  private picked = '';

  constructor() {
    super('Materials', 820);
    this.body.appendChild(el(
      '<div class="mt"><div class="mt-bar"><label class="mt-lab"><span></span><select class="cv-input mt-body"></select></label></div>' +
      '<div class="mt-table"><div class="mt-row mt-head"><span>Material</span><span>Density kg/m3</span><span>Young GPa</span><span>Poisson</span><span>Where the numbers come from</span></div><div class="mt-list"></div></div>' +
      '<p class="mt-msg" role="alert"></p></div>'));
    this.bodySel = q<HTMLSelectElement>(this.body, '.mt-body');
    this.list = q(this.body, '.mt-list');
    this.msg = q(this.body, '.mt-msg');
    setText(q(this.body, '.mt-lab span'), t('Body'));
    const heads = this.body.querySelectorAll('.mt-head span');
    ['Material', 'Density kg/m3', 'Young GPa', 'Poisson', 'Where the numbers come from'].forEach((w, i) => setText(heads[i] as HTMLElement, t(w)));
    this.button('Close', 'ghost', () => this.close());
    this.assign = this.button('Assign to Body', 'primary', () => { void this.apply(); });
    this.bodySel.addEventListener('change', () => { this.current = Number(this.bodySel.value); this.picked = this.bodies.find((b) => b.handle === this.current)?.material ?? ''; this.paint(); });
    this.list.addEventListener('click', (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>('.mt-row');
      if (!row) return;
      this.picked = row.dataset.key ?? '';
      this.paint();
    });
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const [bodies, mats] = await Promise.all([part.bodies(id), part.materials(id)]);
    this.bodies = bodies;
    this.mats = mats.materials;
    if (!this.bodies.some((b) => b.handle === this.current)) this.current = this.bodies[0]?.handle ?? 0;
    this.picked = this.bodies.find((b) => b.handle === this.current)?.material ?? '';
    this.paint();
    this.open();
  }

  private paint(): void {
    patchList<BodyRow>(this.bodySel, this.bodies, {
      key: (b) => String(b.handle),
      create: (b) => { const o = document.createElement('option'); o.value = String(b.handle); return o; },
      update: (n, b) => setText(n, `${b.name}${b.material ? ` (${b.material})` : ''}`),
    });
    if (this.bodySel.value !== String(this.current)) this.bodySel.value = String(this.current);
    patchList<MaterialRow>(this.list, this.mats, {
      key: (m) => m.name,
      create: (m) => {
        const n = el<HTMLElement>('<div class="mt-row" role="button" tabindex="0"><span class="mt-n"></span><span></span><span></span><span></span><span class="mt-prov"></span></div>');
        n.title = m.provenance;
        return n;
      },
      update: (n, m) => {
        const cells = n.children;
        const flagged = (m.single_source_fields ?? []).length > 0 || m.single_source;
        setText(cells[0] as HTMLElement, m.name + (m.grade && !m.name.includes(m.grade) ? ` ${m.grade}` : ''));
        setText(cells[1] as HTMLElement, sig(m.density, 6));
        setText(cells[2] as HTMLElement, sig(m.youngs_modulus, 6));
        setText(cells[3] as HTMLElement, sig(m.poissons_ratio, 4));
        const src = `${m.origin === 'shipped' ? '' : `${t('Your row')}. `}${flagged ? `${t('Single source')}${m.single_source ? '' : ` (${(m.single_source_fields ?? []).join(', ')})`}. ` : ''}${m.provenance}`;
        setText(cells[4] as HTMLElement, src);
        n.title = src;
        setClass(n, 'is-picked', m.name === this.picked);
        setClass(n, 'is-flag', !!flagged);
      },
    });
    const body = this.bodies.find((b) => b.handle === this.current);
    setDisabled(this.assign, !body || this.picked === (body.material ?? ''));
  }

  private async apply(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.current) return;
    setText(this.msg, '');
    try {
      await part.assignMaterial(id, this.current, this.picked);
      this.bodies = await part.bodies(id);
      this.paint();
      toast(t('The material was assigned.'));
    } catch (e) {
      setText(this.msg, messageOf(e));
    }
  }
}

const AXES = ['X', 'Y', 'Z'];

export class MassDialog extends Dialog {
  private bodies: BodyRow[] = [];
  private chosen = new Set<number>();
  private seq = 0;
  private readonly bodyList: HTMLElement;
  private readonly cs: HTMLSelectElement;
  private readonly density: HTMLInputElement;
  private readonly out: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly per: HTMLElement;
  private timer = 0;

  constructor() {
    super('Mass Properties', 780);
    this.body.appendChild(el(
      '<div class="mp"><div class="mp-side"><div class="mp-title"></div><div class="mp-bodies"></div>' +
      '<label class="mp-lab"><span class="mp-cs-t"></span><select class="cv-input mp-cs"></select></label>' +
      '<label class="mp-lab"><span class="mp-d-t"></span><input class="cv-input mp-density" type="text" inputmode="decimal" spellcheck="false"></label></div>' +
      '<div class="mp-main"><div class="mp-grid"></div><div class="mp-inertia"></div><div class="mp-per"></div><ul class="mp-notes"></ul><p class="mp-msg" role="status"></p></div></div>'));
    this.bodyList = q(this.body, '.mp-bodies');
    this.cs = q<HTMLSelectElement>(this.body, '.mp-cs');
    this.density = q<HTMLInputElement>(this.body, '.mp-density');
    this.out = q(this.body, '.mp-grid');
    this.per = q(this.body, '.mp-per');
    this.msg = q(this.body, '.mp-msg');
    setText(q(this.body, '.mp-title'), t('Bodies'));
    setText(q(this.body, '.mp-cs-t'), t('Coordinate system'));
    setText(q(this.body, '.mp-d-t'), t('Density kg/m3 (optional)'));
    this.density.placeholder = t('From materials');
    this.button('Close', 'ghost', () => this.close());
    this.bodyList.addEventListener('change', (e) => {
      const b = e.target as HTMLInputElement;
      const h = Number(b.dataset.h);
      if (b.checked) this.chosen.add(h); else this.chosen.delete(h);
      this.later();
    });
    this.cs.addEventListener('change', () => this.later());
    this.density.addEventListener('input', () => this.later());
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.bodies = await part.bodies(id);
    const ref = await part.refgeo(id).catch(() => ({ items: [] }));
    const opts: Array<[string, string]> = [['world', t('World')], ...ref.items.filter((i) => (i.kind === 'cs' || i.kind === 'plane') && i.status !== 'error').map((i) => [i.name, `${i.kind === 'cs' ? t('Coordinate system') : t('Plane')}: ${i.name}`] as [string, string])];
    patchList<[string, string]>(this.cs, opts, {
      key: (o) => o[0],
      create: (o) => { const n = document.createElement('option'); n.value = o[0]; return n; },
      update: (n, o) => setText(n, o[1]),
    });
    if (this.chosen.size === 0) for (const b of this.bodies) this.chosen.add(b.handle);
    for (const h of [...this.chosen]) if (!this.bodies.some((b) => b.handle === h)) this.chosen.delete(h);
    patchList<BodyRow>(this.bodyList, this.bodies, {
      key: (b) => String(b.handle),
      create: (b) => el<HTMLElement>(`<label class="mp-check"><input type="checkbox" data-h="${b.handle}"><span></span></label>`),
      update: (n, b) => { setText(q(n, 'span'), b.name); const c = q<HTMLInputElement>(n, 'input'); const on = this.chosen.has(b.handle); if (c.checked !== on) c.checked = on; },
    });
    this.open();
    this.later(0);
  }

  private later(ms = 160): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => { void this.compute(); }, ms);
  }

  private async compute(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const n = ++this.seq;
    const dens = Number(this.density.value);
    try {
      const r = await part.mass(id, { handles: [...this.chosen], cs: this.cs.value || 'world', ...(this.density.value.trim() && Number.isFinite(dens) && dens > 0 ? { density: dens } : {}) });
      if (n !== this.seq) return;
      this.show(r);
      setText(this.msg, '');
    } catch (e) {
      if (n === this.seq) setText(this.msg, messageOf(e));
    }
  }

  private show(r: MassResult): void {
    const u = r.units;
    const rows: Array<[string, string]> = [
      [t('Volume'), r.volume === undefined ? t('Not a closed solid') : `${sig(r.volume)} ${u.volume}`],
      [t('Surface area'), `${sig(r.area)} ${u.area}`],
      [t('Mass'), r.mass === undefined || r.mass === null ? t('Needs a material or a density') : `${sig(r.mass)} ${u.mass}`],
      [t('Centre of mass, world'), r.centroid ? r.centroid.map((v, i) => `${AXES[i]} ${sig(v)}`).join('   ') : ''],
      [`${t('Centre of mass in')} ${r.cs}`, r.centroid_cs ? r.centroid_cs.map((v, i) => `${AXES[i]} ${sig(v)}`).join('   ') : ''],
      [t('Principal moments'), r.principal ? r.principal.map((v) => sig(v)).join('   ') : ''],
    ];
    patchList<[string, string]>(this.out, rows, {
      key: (x) => x[0],
      create: () => el<HTMLElement>('<div class="mp-r"><span></span><span class="mp-v"></span></div>'),
      update: (n, x) => { setText(n.children[0] as HTMLElement, x[0]); setText(n.children[1] as HTMLElement, x[1]); },
    });
    const inertia = q(this.body, '.mp-inertia');
    const mat = (m: number[][] | undefined, title: string): string => (m ? `${title}\n${m.map((row) => row.map((v) => sig(v, 7).padStart(15)).join('')).join('\n')}` : '');
    const text = [mat(r.inertia, `${t('Inertia about the centre of mass, world axes')} (${u.inertia})`), mat(r.inertia_cs, `${t('Inertia about the origin of')} ${r.cs} (${u.inertia})`)].filter(Boolean).join('\n\n');
    setText(inertia, text);
    setHidden(inertia, !text);
    patchList<MassResult['bodies'][number]>(this.per, r.bodies, {
      key: (b) => String(b.handle),
      create: () => el<HTMLElement>('<div class="mp-pb"><span></span><span></span><span></span></div>'),
      update: (n, b) => {
        setText(n.children[0] as HTMLElement, b.name);
        setText(n.children[1] as HTMLElement, `${b.material ?? t('no material')}${b.density ? ` · ${sig(b.density, 6)} ${u.density}` : ''}`);
        setText(n.children[2] as HTMLElement, `${b.volume === null ? t('open') : sig(b.volume, 7)} ${u.volume}${b.mass !== null ? ` · ${sig(b.mass, 7)} ${u.mass}` : ''}`);
      },
    });
    const notes = q(this.body, '.mp-notes');
    patchList<string>(notes, [...r.notes, ...(r.mass_basis && r.mass_basis !== 'density' ? [`${t('Mass basis')}: ${r.mass_basis}`] : [])], {
      key: (s) => s,
      create: () => el<HTMLElement>('<li></li>'),
      update: (n, s) => setText(n, s),
    });
  }
}
