import { docStore } from '../ui/doc-store';
import { el, q, setClass, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { layoutState } from '../ui/layout-state';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import { part, type RefGeoItem } from './api';
import { messageOf, partStore } from './store';

const WORLD: Array<[string, string]> = [['XZ', 'Front plane'], ['XY', 'Top plane'], ['YZ', 'Right plane']];

export class SketchEntry {
  private readonly bar: HTMLElement;
  private readonly menu: HTMLElement;
  private busy = false;

  constructor(stage: HTMLElement) {
    this.bar = el<HTMLElement>(
      `<div class="pt-sketchbar" aria-hidden="true"><span class="pt-sk-ico">${icon('sketch', 16)}</span><span class="pt-sk-name"></span><span class="pt-sk-plane"></span>` +
      '<button class="cv-btn cv-btn-primary pt-sk-done" type="button"></button></div>');
    stage.appendChild(this.bar);
    setText(q(this.bar, '.pt-sk-done'), t('Finish Sketch'));
    q(this.bar, '.pt-sk-done').addEventListener('click', () => { void this.finish(); });
    this.menu = el<HTMLElement>('<div class="pt-menu pt-planes" role="menu" hidden></div>');
    (document.getElementById('overlay-root') ?? document.body).appendChild(this.menu);
    document.addEventListener('pointerdown', (e) => { if (!this.menu.hidden && !this.menu.contains(e.target as Node)) this.menu.hidden = true; }, true);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.menu.hidden) { this.menu.hidden = true; e.stopPropagation(); } }, true);
    docStore.onChange(() => this.paint());
    document.addEventListener('formcad:part-sketch-edit', (e) => { void this.edit((e as CustomEvent<string>).detail); });
    this.paint();
  }

  get name(): string {
    const space = docStore.current()?.space ?? docStore.current()?.tab ?? '';
    return space.startsWith('sketch:') ? space.slice(7) : '';
  }

  private paint(): void {
    const name = this.name;
    const on = name !== '';
    setClass(this.bar, 'is-on', on);
    this.bar.setAttribute('aria-hidden', String(!on));
    if (!on) return;
    setText(q(this.bar, '.pt-sk-name'), `${t('Sketch')}: ${name}`);
    const f = partStore.features.find((x) => x.type === 'sketch' && x.params.sketch === name);
    const plane = f ? (f.params.plane === 'face' ? t('on a face') : f.params.plane === 'source' ? t('on a reference plane') : `${t('on plane')} ${String(f.params.plane)}`) : '';
    setText(q(this.bar, '.pt-sk-plane'), plane);
  }

  async start(anchor?: HTMLElement): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const c = view3d();
    if (c && !c.on) await c.enter();
    const face = c?.vp?.sel.faces[0];
    if (face) {
      await this.create({ face: { pid: face.face } });
      return;
    }
    await this.choosePlane(anchor);
  }

  private async choosePlane(anchor?: HTMLElement): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    let refs: RefGeoItem[] = [];
    try { refs = (await part.refgeo(id)).items.filter((i) => i.kind === 'plane' && i.status !== 'error'); } catch { refs = []; }
    this.menu.replaceChildren();
    const title = el<HTMLElement>('<div class="pt-menu-title"></div>');
    setText(title, t('Sketch on which plane? You can also pick a flat face first.'));
    this.menu.appendChild(title);
    const add = (label: string, body: Record<string, unknown>): void => {
      const b = el<HTMLButtonElement>('<button type="button" role="menuitem"></button>');
      setText(b, label);
      b.addEventListener('click', () => { this.menu.hidden = true; void this.create(body); });
      this.menu.appendChild(b);
    };
    for (const [plane, label] of WORLD) add(t(label), { plane });
    for (const r of refs) add(`${t('Reference')}: ${r.name}`, { source: { kind: 'refgeo', name: r.name } });
    this.menu.style.visibility = 'hidden';
    this.menu.hidden = false;
    const w = this.menu.offsetWidth, h = this.menu.offsetHeight;
    const r = (anchor ?? document.querySelector('.cv-view3d'))?.getBoundingClientRect() ?? { left: 80, top: 80, bottom: 120 };
    this.menu.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - w - 4))}px`;
    this.menu.style.top = `${Math.max(4, Math.min('bottom' in r ? r.bottom + 4 : 80, window.innerHeight - h - 4))}px`;
    this.menu.style.visibility = '';
  }

  private async create(body: Record<string, unknown>): Promise<void> {
    const id = docStore.activeId;
    if (!id || this.busy) return;
    this.busy = true;
    try {
      const f = await part.sketch(id, body as Parameters<typeof part.sketch>[1]);
      await this.edit(f.id);
    } catch (e) {
      toast(messageOf(e), 'error');
    } finally {
      this.busy = false;
    }
  }

  async edit(fid: string): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      await part.enter(id, fid);
      await view3d()?.leave();
      await docStore.refresh();
      layoutState.schedule();
      partStore.refresh(0);
    } catch (e) {
      toast(messageOf(e), 'error');
    }
  }

  async finish(): Promise<void> {
    const id = docStore.activeId;
    if (!id || this.busy) return;
    this.busy = true;
    try {
      await part.exit(id);
      await part.rebuild(id, false);
      await docStore.refresh();
      layoutState.schedule();
      partStore.refresh(0);
      await view3d()?.enter();
      await view3d()?.refresh();
    } catch (e) {
      toast(messageOf(e), 'error');
    } finally {
      this.busy = false;
    }
  }
}
