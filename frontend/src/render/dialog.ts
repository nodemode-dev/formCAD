import { token } from '../io/api';
import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setDisabled, setStyleVar, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { text } from '../u8/net';
import { reportBox } from '../p10/kit';
import type { CameraSpec } from '../view3d/types';
import { FrameRenderer, loadRenderScene } from './capture';
import { AbortedRender } from './engine';
import { cancelJob, createJob, getJob, jobProgress, postResult, type JobBrief, type RenderSettings } from './net';
import { fitCamera } from './scene';
import { renderStore } from './store';

export type Backend = 'page' | 'headless' | 'window';

export interface FinalRequest {
  settings: RenderSettings;
  view: CameraSpec | null;
  out: string;
  backend: Backend;
  engine: 'path' | 'raster';
  frames?: Array<{ view: CameraSpec; out: string }>;
}

export interface FinalOutcome { ok: boolean; message: string; lines: string[] }

const fmtBytes = (n: number): string => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const fmtTime = (ms: number): string => (ms >= 60000 ? `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s` : `${(ms / 1000).toFixed(1)} s`);

export function summarize(job: JobBrief): string[] {
  const s = job.stats as { samples?: number; ms?: number; tiles?: number; renderer?: string; bytes?: number; wall?: number; bands?: number };
  return [
    `${job.width} by ${job.height} pixels, ${s.samples ?? job.samples} samples${s.tiles ? `, ${s.tiles} by ${s.tiles} tiles` : ''}${s.bands && s.bands > 1 ? `, ${s.bands} bands` : ''}`,
    `Render time ${fmtTime(s.ms ?? job.elapsed * 1000)}, wall time ${fmtTime((s.wall ?? job.elapsed) * 1000)}`,
    `Graphics: ${s.renderer ?? 'unknown'}`,
    `File: ${job.out}${s.bytes ? ` (${fmtBytes(s.bytes)})` : ''}`,
  ];
}

async function runPage(docId: string, req: FinalRequest, job: JobBrief, ctl: AbortController, tick: (done: number, total: number, phase: string) => void): Promise<JobBrief> {
  const scene = await loadRenderScene(docId);
  const fr = await FrameRenderer.create(scene, req.settings);
  try {
    const view = req.view ?? fitCamera(scene, req.settings.output.width / req.settings.output.height);
    let last = 0;
    const result = await fr.frame({
      width: req.settings.output.width, height: req.settings.output.height, samples: req.settings.quality.samples, tiles: req.settings.quality.tiles,
      camera: view, engine: req.engine, transparent: req.settings.output.transparent,
    }, {
      signal: ctl.signal,
      onProgress(done, total, phase) {
        tick(done, total, phase);
        const now = performance.now();
        if (now - last > 700 || done >= total) {
          last = now;
          void jobProgress(job.id, { done, total, phase }).then((r) => { if (r.cancel) ctl.abort(); }).catch(() => undefined);
        }
      },
    });
    const png = await fr.toPng(result);
    const done = await postResult(job.id, png, { samples: result.samples, ms: Math.round(result.ms), tiles: result.tiles, renderer: result.renderer, engine: result.engine, bands: result.bands });
    return done;
  } finally {
    fr.dispose();
    scene.dispose();
  }
}

async function runWindow(job: JobBrief): Promise<() => Promise<void>> {
  const mod = await import('@tauri-apps/api/webviewWindow');
  const url = `${location.origin}/render.html?job=${encodeURIComponent(job.id)}#rt=${encodeURIComponent(token())}`;
  const w = new mod.WebviewWindow(`render-${job.id}`, { url, visible: false, width: 640, height: 360, title: 'FormCAD render' });
  await new Promise<void>((resolve, reject) => {
    void w.once('tauri://created', () => resolve());
    void w.once('tauri://error', (e) => reject(new Error(String((e as { payload?: unknown }).payload ?? 'The hidden window could not be opened.'))));
  });
  return () => w.close();
}

export async function runFinal(req: FinalRequest, ctl: AbortController, tick: (done: number, total: number, phase: string) => void): Promise<FinalOutcome> {
  const docId = docStore.activeId;
  if (!docId) return { ok: false, message: 'Open a document first.', lines: [] };
  const lines: string[] = [];
  const list = req.frames ?? [{ view: req.view as CameraSpec, out: req.out }];
  let last: JobBrief | null = null;
  for (let i = 0; i < list.length; i++) {
    const frame = list[i];
    const body = {
      backend: req.backend, out: frame.out, view: frame.view, engine: req.engine,
      output: req.settings.output, quality: req.settings.quality, environment: req.settings.environment, ground: req.settings.ground, camera: req.settings.camera,
    };
    let job: JobBrief;
    try {
      job = await createJob(docId, body);
    } catch (e) {
      return { ok: false, message: text(e), lines };
    }
    const label = list.length > 1 ? `Frame ${i + 1} of ${list.length}: ` : '';
    try {
      if (req.backend === 'page') {
        last = await runPage(docId, { ...req, view: frame.view }, job, ctl, (d, tot, ph) => tick(d, tot, label + ph));
      } else {
        const closer = req.backend === 'window' ? await runWindow(job) : null;
        try {
          for (;;) {
            await new Promise((r) => { setTimeout(r, 1000); });
            if (ctl.signal.aborted) { await cancelJob(job.id).catch(() => undefined); throw new AbortedRender(); }
            const st = await getJob(job.id);
            tick(st.done, st.total, label + (st.phase || st.state));
            if (st.state === 'done') { last = st; break; }
            if (st.state === 'failed' || st.state === 'cancelled') return { ok: false, message: st.message || `The render ${st.state}.`, lines };
          }
        } finally {
          await closer?.().catch(() => undefined);
        }
      }
    } catch (e) {
      await cancelJob(job.id).catch(() => undefined);
      if (e instanceof AbortedRender || (e instanceof DOMException && e.name === 'AbortError')) return { ok: false, message: 'Cancelled.', lines };
      return { ok: false, message: text(e), lines };
    }
    if (last) lines.push(...(list.length > 1 ? [`${frame.out}`] : summarize(last)));
  }
  if (list.length > 1 && last) lines.unshift(`${list.length} frames written, last frame ${fmtTime((last.stats as { ms?: number }).ms ?? 0)}`);
  return { ok: true, message: 'Done.', lines };
}

export class RenderDialog extends Dialog {
  private readonly path: HTMLInputElement;
  private readonly backend: HTMLSelectElement;
  private readonly engineSel: HTMLSelectElement;
  private readonly summary: HTMLElement;
  private readonly phase: HTMLElement;
  private readonly fill: HTMLElement;
  private readonly report = reportBox(5);
  private readonly go: HTMLButtonElement;
  private readonly stop: HTMLButtonElement;
  private ctl: AbortController | null = null;
  getView: () => CameraSpec | null = () => null;
  framePlan: (() => Array<{ view: CameraSpec; out: string }>) | null = null;

  constructor() {
    super('Render image', 520);
    this.body.appendChild(el(
      '<div class="rn-dlg">' +
      '<label class="cv-field"><span data-l="file"></span><input class="cv-input rn-path" type="text" spellcheck="false" autocomplete="off"></label>' +
      '<label class="cv-field"><span data-l="how"></span><select class="cv-input rn-backend"></select></label>' +
      '<label class="cv-field"><span data-l="eng"></span><select class="cv-input rn-engine"></select></label>' +
      '<p class="u8-note rn-summary"></p>' +
      '<div class="xw-job is-idle rn-job"><div class="xw-job-top"><span class="xw-job-phase"></span></div><div class="xw-bar"><span class="xw-fill"></span></div></div>' +
      '</div>'));
    this.path = q<HTMLInputElement>(this.body, '.rn-path');
    this.backend = q<HTMLSelectElement>(this.body, '.rn-backend');
    this.engineSel = q<HTMLSelectElement>(this.body, '.rn-engine');
    this.summary = q(this.body, '.rn-summary');
    this.phase = q(this.body, '.xw-job-phase');
    this.fill = q(this.body, '.xw-fill');
    setText(q(this.body, '[data-l="file"]'), t('Image file'));
    setText(q(this.body, '[data-l="how"]'), t('Render with'));
    setText(q(this.body, '[data-l="eng"]'), t('Method'));
    this.path.placeholder = t('/path/to/image.png');
    const opts: Array<[Backend, string]> = [['page', 'This window'], ['headless', 'Headless browser'], ['window', 'Hidden window (desktop app)']];
    for (const [v, l] of opts) { const o = document.createElement('option'); o.value = v; o.textContent = t(l); this.backend.appendChild(o); }
    for (const [v, l] of [['path', 'Path tracing'], ['raster', 'Fast preview pass']]) { const o = document.createElement('option'); o.value = v; o.textContent = t(l); this.engineSel.appendChild(o); }
    this.body.appendChild(this.report.el);
    this.stop = this.button('Cancel render', 'ghost', () => this.ctl?.abort());
    this.go = this.button('Render', 'primary', () => void this.start());
    this.stop.disabled = true;
    this.button('Close', 'ghost', () => { if (!this.ctl) this.close(); });
  }

  show(mode: 'image' | 'turntable'): void {
    const s = renderStore.settings;
    if (!s) return;
    this.setTitle(mode === 'turntable' ? 'Render turntable' : 'Render image');
    const lim = renderStore.limits;
    setText(this.summary, `${s.output.width} by ${s.output.height} pixels, ${s.quality.samples} samples, ${s.quality.tiles} by ${s.quality.tiles} tiles${lim ? `. Largest edge ${lim.max_edge}, up to ${lim.max_samples} samples.` : ''}`);
    this.path.placeholder = mode === 'turntable' ? t('/path/to/frames.png (a number is added)') : t('/path/to/image.png');
    this.report.set([]);
    setText(this.phase, '');
    this.open(this.path);
  }

  private async start(): Promise<void> {
    const s = renderStore.settings;
    if (!s || this.ctl) return;
    const out = this.path.value.trim();
    if (!out) { toast(t('Type the image file name first.'), 'error'); return; }
    const plan = this.framePlan ? this.framePlan() : null;
    const frames = plan && plan.length ? plan.map((f, i) => ({ view: f.view, out: numbered(out, i, plan.length) })) : undefined;
    this.ctl = new AbortController();
    setDisabled(this.go, true);
    setDisabled(this.stop, false);
    setClass(q(this.body, '.rn-job'), 'is-idle', false);
    this.report.set([]);
    const t0 = performance.now();
    const out2 = await runFinal({ settings: s, view: this.getView(), out, backend: this.backend.value as Backend, engine: this.engineSel.value as 'path' | 'raster', frames }, this.ctl, (done, total, ph) => {
      setText(this.phase, `${t(ph)} (${done} / ${total})`);
      setStyleVar(this.fill, '--xw-p', String(total ? Math.round((done / total) * 100) : 0));
    });
    this.ctl = null;
    setDisabled(this.go, false);
    setDisabled(this.stop, true);
    setText(this.phase, out2.ok ? t('Finished in') + ` ${fmtTime(performance.now() - t0)}` : t(out2.message));
    setStyleVar(this.fill, '--xw-p', out2.ok ? '100' : '0');
    this.report.set(out2.ok ? out2.lines : [out2.message, ...out2.lines], !out2.ok);
    if (out2.ok) toast(t('The render is saved.'), 'info');
  }
}

export function numbered(path: string, i: number, total: number): string {
  if (total <= 1) return path;
  const at = path.toLowerCase().endsWith('.png') ? path.length - 4 : path.length;
  return `${path.slice(0, at)}_${String(i + 1).padStart(4, '0')}.png`;
}
