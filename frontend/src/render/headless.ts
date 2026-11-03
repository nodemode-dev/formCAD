import { FrameRenderer, loadRenderScene } from './capture';
import { AbortedRender } from './engine';
import { getJob, jobProgress, postResult, type RenderSettings } from './net';
import { fitCamera } from './scene';
import type { CameraSpec } from '../view3d/types';

const status = document.getElementById('rn-status');
const say = (text: string): void => { if (status && status.textContent !== text) status.textContent = text; };

function adoptToken(): string {
  const rt = new URLSearchParams(location.hash.replace(/^#/, '')).get('rt') ?? '';
  let meta = document.querySelector<HTMLMetaElement>('meta[name="formcad-token"]');
  if (rt) {
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'formcad-token';
      document.head.appendChild(meta);
    }
    meta.content = rt;
    history.replaceState(null, '', location.pathname + location.search);
  }
  return rt;
}

async function run(): Promise<void> {
  adoptToken();
  const id = new URLSearchParams(location.search).get('job') ?? '';
  if (!id) { say('No render job was named.'); return; }
  try {
    const job = await getJob(id, true);
    const spec = job.spec;
    if (!spec) throw new Error('The job has no specification.');
    const settings = { name: 'settings', ...spec.settings } as RenderSettings;
    say('Loading the model.');
    await jobProgress(id, { phase: 'Loading the model', done: 0, total: 0 });
    const scene = await loadRenderScene(spec.document);
    const fr = await FrameRenderer.create(scene, settings);
    const ctl = new AbortController();
    let last = 0;
    const camera = (spec.view as CameraSpec | null) ?? fitCamera(scene, settings.output.width / settings.output.height);
    const result = await fr.frame({
      width: settings.output.width, height: settings.output.height, samples: settings.quality.samples, tiles: settings.quality.tiles,
      camera, engine: spec.engine, transparent: settings.output.transparent,
    }, {
      signal: ctl.signal,
      onProgress(done, total, phase) {
        say(`${phase} (${done} of ${total})`);
        const now = performance.now();
        if (now - last < 700 && done < total) return;
        last = now;
        void jobProgress(id, { done, total, phase }).then((r) => { if (r.cancel || r.state === 'cancelled') ctl.abort(); }).catch(() => undefined);
      },
    });
    say('Encoding the image.');
    await jobProgress(id, { phase: 'Encoding the image', done: result.samples, total: result.samples });
    const png = await fr.toPng(result);
    const reply = await postResult(id, png, { samples: result.samples, ms: Math.round(result.ms), tiles: result.tiles, renderer: result.renderer, engine: result.engine, bands: result.bands });
    say(`Done: ${reply.path}`);
    fr.dispose();
    scene.dispose();
    document.title = 'FormCAD render done';
  } catch (e) {
    if (e instanceof AbortedRender) { say('Cancelled.'); return; }
    const message = e instanceof Error ? e.message : String(e);
    say(`Failed: ${message}`);
    await jobProgress(id, { state: 'failed', message }).catch(() => undefined);
  }
}

void run();
