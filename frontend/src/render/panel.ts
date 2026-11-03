import * as THREE from 'three';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setChecked, setClass, setDisabled, setHidden, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, checkCtl, numberCtl, readout, selectCtl } from '../u8/ui';
import { reportBox, section } from '../p10/kit';
import type { Viewport3D } from '../view3d/viewport';
import type { LiveRender, LiveStats } from './live';
import { swatch } from './materials';
import type { Appearance, RenderBodyRow } from './net';
import { renderStore } from './store';
import type { RenderDialog } from './dialog';
import type { TurntablePreview } from './turntable';

export interface PanelApi {
  vp: () => Viewport3D | null;
  live: () => LiveRender | null;
  setMode: (on: boolean) => Promise<void>;
  isOn: () => boolean;
  watch: (fn: (s: LiveStats) => void) => void;
  dialog: RenderDialog;
  turntable: TurntablePreview;
  turntableFrames: (n: number, sweep: number) => void;
}

const SIZES: ReadonlyArray<readonly [string, string]> = [['1280x720', '1280 by 720'], ['1920x1080', '1920 by 1080'], ['2560x1440', '2560 by 1440'], ['3840x2160', '3840 by 2160 (4K)'], ['custom', 'Custom']];
const TONES: ReadonlyArray<readonly [string, string]> = [['neutral', 'Neutral'], ['aces', 'Film curve'], ['agx', 'Soft highlights'], ['linear', 'Linear']];
const SCALES: ReadonlyArray<readonly [string, string]> = [['0.25', 'Quarter'], ['0.5', 'Half'], ['1', 'Full']];
const RES: ReadonlyArray<readonly [string, string]> = [['1k', '1k'], ['2k', '2k'], ['4k', '4k']];

const hexOf = (a: Appearance): string => swatch(a);

function colorInput(onChange: () => void): HTMLInputElement {
  const i = el<HTMLInputElement>('<input class="u8-color" type="color" aria-label="Colour">');
  i.addEventListener('change', onChange);
  return i;
}

function labelled(label: string, node: HTMLElement): HTMLElement {
  const root = el('<label class="cv-field"><span></span></label>');
  setText(q(root, 'span'), t(label));
  root.appendChild(node);
  return root;
}

export function renderPanel(api: PanelApi): DockPanel {
  return {
    id: 'render',
    label: 'Render',
    icon: 'rnRender',
    order: 47,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel', 'rn-panel');
      const sel = new Set<string>();
      let lastClick = '';
      let pending = 0;
      let busy = false;

      const sView = section('Render view');
      const toggle = button('Render view', () => void api.setMode(!api.isOn()), 'primary');
      const scale = selectCtl('Preview detail', SCALES, () => { api.live()?.setScale(Number(scale.get())); });
      scale.set('0.5');
      const prog = readout('Samples');
      const state = readout('State');
      sView.body.append(buttons(toggle), scale.el, prog.el, state.el);

      const sEnv = section('Environment');
      const env = selectCtl('Environment', [['', '-']], () => void commit({ environment: { id: env.get() } }));
      const res = selectCtl('Resolution', RES, () => void commit({ environment: { resolution: res.get() } }));
      const rot = numberCtl('Rotation (degrees)', 0, () => void commit({ environment: { rotation: rot.get() ?? 0 } }));
      const inten = numberCtl('Intensity', 1, () => void commit({ environment: { intensity: inten.get() ?? 1 } }));
      const showBg = checkCtl('Show the environment behind', true, () => void commit({ environment: { show_background: showBg.get() } }));
      const bgColor = colorInput(() => void commit({ environment: { background_color: bgColor.value } }));
      const blur = numberCtl('Background blur', 0, () => void commit({ environment: { blur: blur.get() ?? 0 } }));
      const envNote = reportBox(3);
      sEnv.body.append(env.el, res.el, rot.el, inten.el, showBg.el, labelled('Plain background', bgColor), blur.el, envNote.el);

      const sApp = section('Appearance');
      const list = el('<div class="u8-list rn-bodies is-scroll" role="listbox" aria-multiselectable="true" aria-label="Bodies"></div>');
      const picker = selectCtl('Appearance', [['', '-']], () => paintProv());
      const prov = reportBox(5);
      const assign = button('Assign', () => void doAssign(picker.get()), 'primary');
      const clear = button('Use the material', () => void doAssign(null));
      sApp.body.append(list, picker.el, prov.el, buttons(assign, clear));

      const sDec = section('Decals');
      const dList = el('<div class="u8-list rn-decals is-scroll" role="listbox" aria-label="Decals"></div>');
      const dKind = selectCtl('Kind', [['color', 'Colour patch'], ['image', 'Image']], () => syncDecalForm());
      const dColor = colorInput(() => undefined);
      dColor.value = '#e63b2e';
      const dImage = el<HTMLInputElement>('<input type="file" accept="image/png,image/jpeg,image/webp" class="rn-file" aria-label="Decal image">');
      const dW = numberCtl('Width', 20);
      const dH = numberCtl('Height', 10);
      const dOpacity = numberCtl('Opacity (0 to 1)', 1);
      const place = button('Place on a surface', () => void armDecal());
      const del = button('Remove decal', () => void removeDecal(), 'danger');
      const dNote = el('<p class="u8-note rn-decal-note"></p>');
      sDec.body.append(dList, dKind.el, labelled('Colour', dColor), labelled('Image file', dImage), dW.el, dH.el, dOpacity.el, buttons(place, del), dNote);

      const sQ = section('Quality and image');
      const samples = numberCtl('Samples', 256, () => void commit({ quality: { samples: samples.get() ?? 256 } }));
      const bounces = numberCtl('Bounces', 6, () => void commit({ quality: { bounces: bounces.get() ?? 6 } }));
      const tbounces = numberCtl('Glass bounces', 8, () => void commit({ quality: { transmissive_bounces: tbounces.get() ?? 8 } }));
      const tiles = numberCtl('Tiles per side', 4, () => void commit({ quality: { tiles: tiles.get() ?? 4 } }));
      const expo = numberCtl('Exposure', 1, () => void commit({ quality: { exposure: expo.get() ?? 1 } }));
      const tone = selectCtl('Tone mapping', TONES, () => void commit({ quality: { tone_mapping: tone.get() } }));
      const denoise = checkCtl('Smooth the noise', false, () => void commit({ quality: { denoise: denoise.get() } }));
      const ground = checkCtl('Floor under the model', false, () => void commit({ ground: { mode: ground.get() ? 'floor' : 'none' } }));
      const groundColor = colorInput(() => void commit({ ground: { color: groundColor.value } }));
      const size = selectCtl('Image size', SIZES, () => { const v = size.get(); if (v !== 'custom') { const [w, h] = v.split('x').map(Number); void commit({ output: { width: w, height: h } }); } });
      const wIn = numberCtl('Width (pixels)', 3840, () => void commit({ output: { width: wIn.get() ?? 3840 } }));
      const hIn = numberCtl('Height (pixels)', 2160, () => void commit({ output: { height: hIn.get() ?? 2160 } }));
      const transp = checkCtl('Transparent background', false, () => void commit({ output: { transparent: transp.get() } }));
      const dof = numberCtl('Lens opening (0 is sharp)', 0, () => void commit({ camera: { aperture: dof.get() ?? 0 } }));
      const qNote = el('<p class="u8-note rn-note"></p>');
      sQ.body.append(samples.el, bounces.el, tbounces.el, tiles.el, expo.el, tone.el, denoise.el, ground.el, labelled('Floor colour', groundColor), size.el, wIn.el, hIn.el, transp.el, dof.el, qNote);

      const sOut = section('Render to a file');
      const imgBtn = button('Render image...', () => { api.dialog.show('image'); }, 'primary');
      const tFrames = numberCtl('Turntable frames', 36);
      const tSweep = numberCtl('Turntable sweep (degrees)', 360);
      const tPrev = button('Preview turntable', () => { if (api.turntable.on) api.turntable.stop(); else api.turntable.start(8, tSweep.get() ?? 360); syncTurn(); });
      const tRender = button('Render turntable...', () => { api.turntableFrames(Math.round(tFrames.get() ?? 36), tSweep.get() ?? 360); api.dialog.show('turntable'); });
      sOut.body.append(buttons(imgBtn), tFrames.el, tSweep.el, buttons(tPrev, tRender));

      const err = el('<p class="u8-note rn-error" role="alert"></p>');
      body.append(sView.root, sEnv.root, sApp.root, sDec.root, sQ.root, sOut.root, err);

      function syncTurn(): void { setText(tPrev, api.turntable.on ? t('Stop preview') : t('Preview turntable')); }
      function syncDecalForm(): void {
        const image = dKind.get() === 'image';
        setHidden(dColor.parentElement as HTMLElement, image);
        setHidden(dImage.parentElement as HTMLElement, !image);
      }

      async function commit(patch: Record<string, unknown>): Promise<void> {
        window.clearTimeout(pending);
        pending = window.setTimeout(() => { void renderStore.patch(patch); }, 120);
      }

      async function doAssign(name: string | null): Promise<void> {
        const keys = renderStore.rows.filter((r) => sel.has(r.key)).map((r) => r.instance_key || r.key);
        if (!keys.length) { toast(t('Select a body in the list first.'), 'error'); return; }
        await renderStore.assign(keys, name && name !== '' ? name : null);
        api.live()?.invalidateScene();
      }

      function paintProv(): void {
        const a = renderStore.appearance(picker.get());
        if (!a) { prov.set([]); return; }
        const src = renderStore.library?.sources ?? {};
        const f = (k: string, label: string, v: string): string => `${label}: ${v} (${src[a.sources[k]]?.title.split(',')[0].slice(0, 60) ?? a.sources[k] ?? ''})`;
        prov.set([
          `${a.name}, ${a.category}`,
          f('base_color', 'Colour', a.base_color),
          f('metallic', 'Metallic', String(a.metallic)),
          f('roughness', 'Roughness', String(a.roughness)),
          a.provenance,
        ]);
      }

      function paintBodies(): void {
        const rows = renderStore.rows;
        patchList(list, rows, {
          key: (r) => r.key,
          create: (r) => {
            const n = el<HTMLElement>('<div class="u8-row rn-row" role="option"><span class="rn-sw"></span><span class="u8-row-name"></span><span class="rn-app"></span></div>');
            n.dataset.key = r.key;
            return n;
          },
          update: (n, r: RenderBodyRow) => {
            setText(q(n, '.u8-row-name'), r.name);
            setText(q(n, '.rn-app'), r.appearance.name);
            const sw = q<HTMLElement>(n, '.rn-sw');
            if (sw.style.backgroundColor !== hexOf(r.appearance)) sw.style.backgroundColor = hexOf(r.appearance);
            setClass(n, 'is-selected', sel.has(r.key));
            n.setAttribute('aria-selected', String(sel.has(r.key)));
          },
        });
      }

      list.addEventListener('click', (e) => {
        const row = (e.target as HTMLElement).closest<HTMLElement>('[data-key]');
        const key = row?.dataset.key;
        if (!key) return;
        const keys = renderStore.rows.map((r) => r.key);
        if (e.shiftKey && lastClick) {
          const a = keys.indexOf(lastClick), b = keys.indexOf(key);
          for (const k of keys.slice(Math.min(a, b), Math.max(a, b) + 1)) sel.add(k);
        } else if (e.ctrlKey || e.metaKey) {
          if (sel.has(key)) sel.delete(key); else sel.add(key);
        } else {
          sel.clear();
          sel.add(key);
        }
        lastClick = key;
        const first = renderStore.rows.find((r) => r.key === key);
        if (first && !e.ctrlKey && !e.shiftKey) { setValue(picker.input as HTMLSelectElement, first.appearance.name.replace(/ \(body colour\)$/, '')); paintProv(); }
        paintBodies();
      });

      let pickedDecal = '';
      dList.addEventListener('click', (e) => {
        const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
        if (key) { pickedDecal = key; paintDecals(); }
      });

      function paintDecals(): void {
        patchList(dList, renderStore.decals, {
          key: (d) => d.name,
          create: () => el<HTMLElement>('<div class="u8-row rn-row" role="option"><span class="rn-sw"></span><span class="u8-row-name"></span><span class="rn-app"></span></div>'),
          update: (n, d) => {
            setText(q(n, '.u8-row-name'), d.label || d.name.replace(/^decal:/, ''));
            setText(q(n, '.rn-app'), d.kind === 'image' ? t('Image') : t('Colour'));
            const sw = q<HTMLElement>(n, '.rn-sw');
            if (sw.style.backgroundColor !== d.color) sw.style.backgroundColor = d.color;
            setClass(n, 'is-selected', pickedDecal === d.name);
          },
        });
        setDisabled(del, !pickedDecal || !renderStore.decals.some((d) => d.name === pickedDecal));
      }

      async function removeDecal(): Promise<void> {
        if (!pickedDecal) return;
        await renderStore.removeDecal(pickedDecal.replace(/^decal:/, ''));
        pickedDecal = '';
        api.live()?.invalidateScene();
      }

      async function armDecal(): Promise<void> {
        const vp = api.vp();
        if (!vp) { await api.setMode(true); }
        const v = api.vp();
        if (!v) return;
        let image = '';
        if (dKind.get() === 'image') {
          const f = dImage.files?.[0];
          if (!f) { toast(t('Choose an image file first.'), 'error'); return; }
          if (f.size > 280000) { toast(t('The image is larger than 280 KB; use a smaller one.'), 'error'); return; }
          image = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = () => rej(new Error('The image could not be read.')); r.readAsDataURL(f); });
        }
        setText(dNote, t('Click a surface in the view. Escape cancels.'));
        const canvas = v.canvas;
        const done = (): void => { canvas.removeEventListener('pointerup', onUp, true); canvas.removeEventListener('keydown', onKey, true); setText(dNote, ''); };
        const onKey = (ev: KeyboardEvent): void => { if (ev.key === 'Escape') { ev.stopPropagation(); done(); } };
        const onUp = (ev: PointerEvent): void => {
          ev.stopImmediatePropagation();
          ev.preventDefault();
          done();
          const r = canvas.getBoundingClientRect();
          const hit = rayHit(v, ev.clientX - r.left, ev.clientY - r.top);
          if (!hit) { toast(t('Nothing under the pointer.'), 'error'); return; }
          const row = renderStore.rows.find((x) => x.id === hit.body);
          if (!row) { toast(t('That body has no render record yet.'), 'error'); return; }
          const n = renderStore.decals.length + 1;
          let name = `decal${n}`;
          while (renderStore.decals.some((d) => d.name === `decal:${name}`)) name = `decal${renderStore.decals.length + 1 + Math.floor(Math.random() * 1000)}`;
          const w = dW.get() ?? 20, h = dH.get() ?? 10;
          void renderStore.addDecal({
            name, label: `Decal ${n}`, body: row.instance_key || row.key, position: hit.point, normal: hit.normal, up: Math.abs(hit.normal[2]) > 0.95 ? [0, 1, 0] : [0, 0, 1],
            size: [w, h], depth: Math.max(w, h) * 0.5, kind: dKind.get() as 'color' | 'image', color: dColor.value, image, opacity: dOpacity.get() ?? 1, roughness: 0.5,
          }).then(() => api.live()?.invalidateScene());
        };
        canvas.addEventListener('pointerup', onUp, true);
        canvas.addEventListener('keydown', onKey, true);
        canvas.focus({ preventScroll: true });
      }

      function paintEnv(): void {
        const s = renderStore.settings;
        const envs = renderStore.envs;
        if (!s || !envs) return;
        const have = Array.from((env.input as HTMLSelectElement).options).map((o) => o.value).join('|');
        const want = envs.environments.map((e) => e.id).join('|');
        if (have !== want) {
          (env.input as HTMLSelectElement).replaceChildren(...envs.environments.map((e) => { const o = document.createElement('option'); o.value = e.id; o.textContent = e.name; return o; }));
        }
        setValue(env.input as HTMLSelectElement, s.environment.id);
        setValue(res.input as HTMLSelectElement, s.environment.resolution);
        const entry = envs.environments.find((e) => e.id === s.environment.id);
        const file = entry?.files.find((f) => f.resolution === s.environment.resolution);
        envNote.set([
          entry ? `${entry.name} by ${entry.author}` : '',
          `${envs.licence.id}, no attribution needed${file ? `; ${file.present ? 'on this computer' : 'downloads when used'}` : ''}`,
          entry?.page ?? '',
        ]);
      }

      function paintLibrary(): void {
        const lib = renderStore.library;
        if (!lib) return;
        const have = (picker.input as HTMLSelectElement).options.length;
        if (have !== lib.appearances.length) {
          const sel2 = picker.input as HTMLSelectElement;
          const groups = new Map<string, HTMLOptGroupElement>();
          sel2.replaceChildren();
          for (const a of lib.appearances) {
            let g = groups.get(a.category);
            if (!g) { g = document.createElement('optgroup'); g.label = t(a.category.charAt(0).toUpperCase() + a.category.slice(1)); groups.set(a.category, g); sel2.appendChild(g); }
            const o = document.createElement('option');
            o.value = a.name;
            o.textContent = a.name;
            g.appendChild(o);
          }
          sel2.value = lib.default;
        }
      }

      function paintSettings(): void {
        const s = renderStore.settings;
        if (!s) return;
        paintEnv();
        setValue(rot.input as HTMLInputElement, String(s.environment.rotation));
        setValue(inten.input as HTMLInputElement, String(s.environment.intensity));
        setChecked(showBg.input as HTMLInputElement, s.environment.show_background);
        if (bgColor.value !== s.environment.background_color) bgColor.value = s.environment.background_color;
        setValue(blur.input as HTMLInputElement, String(s.environment.blur));
        setValue(samples.input as HTMLInputElement, String(s.quality.samples));
        setValue(bounces.input as HTMLInputElement, String(s.quality.bounces));
        setValue(tbounces.input as HTMLInputElement, String(s.quality.transmissive_bounces));
        setValue(tiles.input as HTMLInputElement, String(s.quality.tiles));
        setValue(expo.input as HTMLInputElement, String(s.quality.exposure));
        setValue(tone.input as HTMLSelectElement, s.quality.tone_mapping);
        setChecked(denoise.input as HTMLInputElement, s.quality.denoise);
        setChecked(ground.input as HTMLInputElement, s.ground.mode === 'floor');
        if (groundColor.value !== s.ground.color) groundColor.value = s.ground.color;
        const key = `${s.output.width}x${s.output.height}`;
        setValue(size.input as HTMLSelectElement, SIZES.some(([v]) => v === key) ? key : 'custom');
        setValue(wIn.input as HTMLInputElement, String(s.output.width));
        setValue(hIn.input as HTMLInputElement, String(s.output.height));
        setChecked(transp.input as HTMLInputElement, s.output.transparent);
        setValue(dof.input as HTMLInputElement, String(s.camera.aperture));
        const lim = renderStore.limits;
        setText(qNote, lim ? `${t('Largest edge')} ${lim.max_edge} px, ${lim.max_pixels / 1e6 | 0} ${t('million pixels, up to')} ${lim.max_samples} ${t('samples')}.` : '');
      }

      function paintAll(): void {
        paintLibrary();
        paintSettings();
        paintBodies();
        paintDecals();
        paintProv();
        syncDecalForm();
        syncTurn();
        setText(err, renderStore.error);
        const live = api.live();
        if (live && renderStore.settings && api.isOn()) live.apply(renderStore.settings);
      }

      const stats = (s: LiveStats): void => {
        setText(toggle, api.isOn() ? t('Leave render view') : t('Render view'));
        setClass(toggle, 'is-on', api.isOn());
        prog.set(s.state === 'off' ? '-' : `${Math.floor(s.samples)} / ${s.target}`);
        state.set(s.message || t(({ off: 'Off', building: 'Building the scene', tracing: 'Tracing', done: 'Finished', failed: 'Failed' } as const)[s.state]));
      };
      api.watch(stats);

      renderStore.on(paintAll);
      docStore.onChange(() => { void renderStore.load(); });
      paintAll();
      stats({ samples: 0, target: 0, state: 'off', message: '', scale: 0.5 });
      return { show: () => { void renderStore.load(); } };
    },
  };
}

export function rayHit(vp: Viewport3D, px: number, py: number): { body: number; point: [number, number, number]; normal: [number, number, number] } | null {
  const ray = vp.rayAt(px, py);
  const rc = new THREE.Raycaster(new THREE.Vector3(...ray.origin), new THREE.Vector3(...ray.direction));
  let best: { body: number; d: number; point: THREE.Vector3; normal: THREE.Vector3 } | null = null;
  for (const [id, view] of vp.bodyViews) {
    const objs: THREE.Object3D[] = [];
    view.group.traverse((o) => { if ((o as THREE.Mesh).isMesh && !(o as { isLineSegments2?: boolean }).isLineSegments2 && o.visible) objs.push(o); });
    for (const h of rc.intersectObjects(objs, false)) {
      if (h.face && (!best || h.distance < best.d)) best = { body: id, d: h.distance, point: h.point.clone(), normal: h.face.normal.clone().transformDirection(h.object.matrixWorld) };
      break;
    }
  }
  return best ? { body: best.body, point: [best.point.x, best.point.y, best.point.z], normal: [best.normal.x, best.normal.y, best.normal.z] } : null;
}
