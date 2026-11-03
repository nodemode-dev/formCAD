import { asm, isAssembly } from '../u8/asm';
import { text } from '../u8/net';
import { button, buttons, fmt, numberCtl, readout, section, selectCtl, type Ctl } from '../u8/ui';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setTitle, setValue } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import { boardApi, EASE_LABELS, SOURCE_LABELS, STYLE_LABELS, type Board, type EaseId, type Shot, type SourceId, type StyleId } from './api';
import { exportVideo, type ExportReport } from './export';
import { story } from './store';

const blank = (v: number | null): number | undefined => (v === null ? undefined : v);
const mb = (n: number): string => `${(n / 1048576).toFixed(2)} MB`;

function fill(sel: HTMLSelectElement, options: ReadonlyArray<readonly [string, string]>): void {
  const keep = sel.value;
  patchList(sel, options.map((o) => ({ v: o[0], label: o[1] })), {
    key: (o) => o.v,
    create: (o) => { const n = document.createElement('option'); n.value = o.v; return n; },
    update: (n, o) => setText(n, o.label),
  });
  if (options.some((o) => o[0] === keep)) setValue(sel, keep);
}

async function guarded(fn: () => Promise<unknown>): Promise<boolean> {
  try { await fn(); return true; } catch (e) { toast(text(e), 'error'); return false; }
}

export function exportReportLines(r: ExportReport): string[] {
  return [
    `${r.frames} frames at ${r.fps} per second, ${r.seconds.toFixed(2)} s, ${r.width} by ${r.height}`,
    `codec ${r.codecString || r.codec} in ${r.container.toUpperCase()}`,
    `${mb(r.size)} (${r.size} bytes)`,
    `frames from ${r.source}, encoded in ${(r.ms / 1000).toFixed(1)} s`,
  ];
}

export let lastExport: ExportReport | null = null;
export let exportTask: AbortController | null = null;

export async function runExport(board: Board, path: string | undefined, progress: (done: number, total: number, phase: string) => void): Promise<ExportReport | null> {
  exportTask = new AbortController();
  try {
    const r = await exportVideo({ board, path, signal: exportTask.signal, progress });
    if (r) lastExport = r;
    return r;
  } finally {
    exportTask = null;
  }
}

export function storyboardPanel(): DockPanel {
  return {
    id: 'an1-board', label: 'Storyboard', icon: 'storyboard', order: 34,
    build(body) {
      body.classList.add('u8-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open an assembly to build a storyboard.'));
      const live = el('<div class="u8-live"></div>');
      live.style.display = 'grid';
      live.style.gap = 'var(--space-2)';
      body.append(note, live);

      const boardSec = section('Storyboard');
      const boards = selectCtl('Board', [], () => story.select(boards.get()));
      const newName = el<HTMLInputElement>('<input class="cv-input" type="text" placeholder="New storyboard name" aria-label="New storyboard name" spellcheck="false">');
      const baseView = selectCtl('From explode view', []);
      const create = button('Create', () => {
        const id = story.id();
        const name = newName.value.trim();
        if (!id || !name) return;
        const camera = view3d()?.vp?.getCamera();
        void guarded(async () => {
          if (baseView.get()) await boardApi.seed(id, { name, view: baseView.get(), orbit: 0, camera });
          else await boardApi.create(id, { name, shots: [] } as Partial<Board>);
          newName.value = '';
          story.selected = name;
          await story.refresh();
          if (baseView.get()) await story.autoCamera();
        });
      }, 'primary');
      const remove = button('Delete', () => {
        const id = story.id();
        const b = story.board();
        if (id && b) void guarded(async () => { await boardApi.del(id, b.name); await story.refresh(); });
      }, 'danger');
      const width = numberCtl('Width', 1280, () => edit((b) => { b.width = Math.round(width.get() ?? b.width); }));
      const height = numberCtl('Height', 720, () => edit((b) => { b.height = Math.round(height.get() ?? b.height); }));
      const fps = numberCtl('Frames per second', 30, () => edit((b) => { b.fps = Math.round(fps.get() ?? b.fps); }));
      const style = selectCtl('Style', STYLE_LABELS.map((s) => [s[0], s[1]] as const), () => edit((b) => { b.style = style.get() as StyleId; }));
      const source = selectCtl('Frames from', SOURCE_LABELS.map((s) => [s[0], s[1]] as const), () => edit((b) => { b.source = source.get() as SourceId; }));
      const samples = numberCtl('Samples per frame', 16, () => edit((b) => { b.samples = Math.round(samples.get() ?? b.samples); }));
      const length = readout('Length');
      boardSec.body.append(boards.el, newName, baseView.el, buttons(create, remove), width.el, height.el, fps.el, style.el, source.el, samples.el, length.el);

      const shotSec = section('Shots');
      const shotList = el('<div class="u8-list an1-shots" role="listbox" aria-label="Shots"></div>');
      const edit = (fn: (b: Board) => void): Promise<boolean> => guarded(() => story.put(fn));
      const editShot = (fn: (s: Shot, b: Board) => void): void => { void edit((b) => { const s = b.shots.find((x) => x.id === story.shot); if (s) fn(s, b); }); };
      const append = (fn: (b: Board) => void): void => {
        void edit(fn).then((ok) => {
          const last = story.board()?.shots.at(-1);
          if (ok && last) { story.shot = last.id; story.emit(); }
        });
      };
      const addShot = button('Add shot', () => append((b) => { b.shots.push({ id: -1, name: `Shot ${b.shots.length + 1}`, duration: 2, ease: 'ease' }); }));
      const turntable = button('Add turntable', () => {
        const cam = view3d()?.vp?.getCamera();
        append((b) => { b.shots.push({ id: -1, name: 'Turntable', duration: 6, ease: 'linear', loop: true, camera: { keys: cam ? [{ at: 0, camera: cam }] : [], orbit: 360 } }); });
      });
      const dup = button('Duplicate', () => append((b) => { const s = b.shots.find((x) => x.id === story.shot); if (s) { const c = JSON.parse(JSON.stringify(s)) as Shot; c.id = -1; c.name = `${s.name} copy`; b.shots.push(c); } }));
      const del = button('Delete', () => edit((b) => { b.shots = b.shots.filter((x) => x.id !== story.shot); }), 'danger');
      const earlier = button('Earlier', () => edit((b) => { const i = b.shots.findIndex((x) => x.id === story.shot); if (i > 0) b.shots.splice(i - 1, 0, b.shots.splice(i, 1)[0]); }));
      const later = button('Later', () => edit((b) => { const i = b.shots.findIndex((x) => x.id === story.shot); if (i >= 0 && i < b.shots.length - 1) b.shots.splice(i + 1, 0, b.shots.splice(i, 1)[0]); }));
      const framing = button('Frame cameras', () => { void guarded(() => story.autoCamera()); });
      shotSec.body.append(shotList, buttons(addShot, turntable, dup), buttons(earlier, later, del, framing));

      const one = section('Selected shot');
      const sName = el<HTMLInputElement>('<input class="cv-input" type="text" aria-label="Shot name" spellcheck="false">');
      sName.addEventListener('change', () => editShot((s) => { s.name = sName.value.trim() || s.name; }));
      const sDur = numberCtl('Duration (s)', 2, () => editShot((s) => { s.duration = Math.max(0, sDur.get() ?? s.duration); }));
      const sEase = selectCtl('Easing', EASE_LABELS.map((e) => [e[0], e[1]] as const), () => editShot((s) => { s.ease = sEase.get() as EaseId; }));
      const sView = selectCtl('Explode view', [], () => editShot((s) => { s.explode = sView.get() ? { view: sView.get(), from: blank(sFrom.get()), to: blank(sTo.get()) } : undefined; }));
      const sFrom = numberCtl('Explode from', 0, () => editShot((s) => { if (s.explode) s.explode.from = blank(sFrom.get()); }));
      const sTo = numberCtl('Explode to', 0, () => editShot((s) => { if (s.explode) s.explode.to = blank(sTo.get()); }));
      const dMate = selectCtl('Drive mate', [], () => editShot((s) => { s.drive = dMate.get() ? { mate: dMate.get(), from: blank(dFrom.get()), to: dTo.get() ?? 0 } : undefined; }));
      const dFrom = numberCtl('Drive from', 0, () => editShot((s) => { if (s.drive) s.drive.from = blank(dFrom.get()); }));
      const dTo = numberCtl('Drive to', 0, () => editShot((s) => { if (s.drive) s.drive.to = dTo.get() ?? s.drive.to; }));
      const orbit = numberCtl('Orbit (degrees)', 0, () => editShot((s) => { const v = orbit.get(); s.camera = { keys: s.camera?.keys ?? [], orbit: v || undefined }; if (!s.camera.keys.length && !s.camera.orbit) s.camera = undefined; }));
      const sStyle = selectCtl('Style', [['', 'Storyboard style'], ...STYLE_LABELS.map((s) => [s[0], s[1]] as const)], () => editShot((s) => { s.style = (sStyle.get() || undefined) as StyleId | undefined; }));
      const camKeys = readout('Camera keys');
      const keyAt = (at: number): void => {
        const cam = view3d()?.vp?.getCamera();
        if (!cam) { toast(t('Open the 3D view first.'), 'info'); return; }
        editShot((s) => {
          const keys = (s.camera?.keys ?? []).filter((k) => k.at !== at);
          keys.push({ at, camera: cam });
          keys.sort((a, b) => a.at - b.at);
          s.camera = { keys, orbit: s.camera?.orbit };
        });
      };
      const camStart = button('Camera at start', () => keyAt(0));
      const camEnd = button('Camera at end', () => keyAt(1));
      const camClear = button('Clear camera', () => editShot((s) => { s.camera = s.camera?.orbit ? { keys: [], orbit: s.camera.orbit } : undefined; }));
      one.body.append(sName, sDur.el, sEase.el, sView.el, sFrom.el, sTo.el, dMate.el, dFrom.el, dTo.el, orbit.el, sStyle.el, camKeys.el, buttons(camStart, camEnd, camClear));

      const tl = section('Timeline');
      const track = el('<div class="an1-track" role="list" aria-label="Timeline"></div>');
      const slider = el<HTMLInputElement>('<input class="u8-slider" type="range" min="0" max="0" value="0" aria-label="Playhead">');
      slider.addEventListener('input', () => { story.stop(); void story.seek(Number(slider.value)).catch((e: unknown) => toast(text(e), 'error')); });
      const at = readout('Playhead');
      const play = el<HTMLButtonElement>(`<button class="u8-btn" type="button" aria-label="Play"></button>`);
      play.innerHTML = `<span class="an1-ico" data-i="play">${icon('playTri', 12)}</span><span class="an1-ico" data-i="stop" hidden>${icon('stopSq', 12)}</span><span class="an1-lab"></span>`;
      play.addEventListener('click', () => { if (story.playing) { story.stop(); story.emit(); } else void story.play().catch((e: unknown) => toast(text(e), 'error')); });
      const close = button('Close preview', () => { story.stop(); story.stage.hide(); story.emit(); });
      tl.body.append(track, slider, at.el, buttons(play, close));

      const vid = section('Video');
      const run = button('Export video...', () => {
        const b = story.board();
        if (!b) return;
        story.stop();
        void (async () => {
          setDisabled(run, true);
          try {
            const r = await runExport(b, undefined, (d, tot, phase) => setText(prog, phase === 'save' ? t('Saving') : `${d} / ${tot}`));
            if (r) toast(`${t('Saved')} ${r.path}`, 'info');
          } catch (e) {
            if (!(e instanceof DOMException && e.name === 'AbortError')) toast(text(e), 'error');
          } finally {
            setText(prog, '');
            setDisabled(run, false);
            paint();
          }
        })();
      }, 'primary');
      const cancel = button('Cancel export', () => exportTask?.abort());
      const prog = el('<output class="an1-prog" aria-live="polite"></output>');
      const outs = Array.from({ length: 4 }, (_, i) => readout(['Frames', 'Codec', 'File size', 'Source'][i]));
      vid.body.append(buttons(run, cancel), prog, ...outs.map((o) => o.el));

      live.append(boardSec.root, shotSec.root, one.root, tl.root, vid.root);

      const paint = (): void => {
        const on = isAssembly();
        setHidden(note, on);
        setHidden(live, !on);
        if (!on) return;
        const list = story.list;
        const b = story.board();
        const names = Object.keys(list?.boards ?? {});
        fill(boards.input as HTMLSelectElement, names.length ? names.map((n) => [n, n] as const) : [['', '-']]);
        setValue(boards.input as HTMLSelectElement, story.selected);
        fill(baseView.input as HTMLSelectElement, [['', 'Empty storyboard'], ...Object.keys(asm.explode.views).map((n) => [n, n] as const)]);
        setDisabled(remove, !b);
        for (const c of [width, height, fps, style, source]) c.input.disabled = !b;
        samples.input.disabled = !b || b.source !== 'path';
        style.input.disabled = !b || b.source !== 'viewport';
        if (b) {
          width.set(b.width); height.set(b.height); fps.set(b.fps); style.set(b.style); source.set(b.source); samples.set(b.samples);
          length.set(`${b.plan.frames} frames · ${fmt(b.plan.seconds, 4)} s`);
        } else {
          length.set('-');
        }
        patchList(shotList, b?.shots ?? [], {
          key: (s) => `s${s.id}`,
          create: (s) => {
            const row = el('<div class="u8-row" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span></div>');
            row.addEventListener('click', () => { story.shot = s.id; const sp = story.board()?.plan.spans.find((x) => x.id === s.id); if (sp) { story.stop(); void story.seek(sp.first); } story.emit(); });
            return row;
          },
          update: (row, s) => {
            setText(q(row, '.u8-row-sub'), String((b?.shots.indexOf(s) ?? 0) + 1));
            setText(q(row, '.u8-row-name'), s.name);
            setText(q(row, '.u8-badge'), `${fmt(s.duration, 3)} s`);
            setClass(row, 'is-selected', s.id === story.shot);
          },
        });
        const cur = b?.shots.find((s) => s.id === story.shot) ?? null;
        for (const c of [sDur, sEase, sView, sFrom, sTo, dMate, dFrom, dTo, orbit, sStyle] as Array<Ctl<unknown>>) c.input.disabled = !cur;
        sName.disabled = !cur;
        for (const x of [dup, del, earlier, later, camStart, camEnd, camClear]) setDisabled(x, !cur);
        setDisabled(framing, !b || b.shots.length === 0);
        setDisabled(dup, !cur ||(b?.shots.length ?? 0) >= (list?.limits.shots ?? 0));
        if (cur) {
          if (document.activeElement !== sName && sName.value !== cur.name) sName.value = cur.name;
          sDur.set(cur.duration); sEase.set(cur.ease);
          fill(sView.input as HTMLSelectElement, [['', 'None'], ...Object.keys(asm.explode.views).map((n) => [n, n] as const)]);
          sView.set(cur.explode?.view ?? '');
          sFrom.set(cur.explode?.from ?? null); sTo.set(cur.explode?.to ?? null);
          const mates = (asm.status?.mates ?? []).filter((m) => m.kind === 'angle' || m.kind === 'distance');
          fill(dMate.input as HTMLSelectElement, [['', 'None'], ...mates.map((m) => [m.name, `${m.name} ${m.label}`.trim()] as const)]);
          dMate.set(cur.drive?.mate ?? '');
          dFrom.set(cur.drive?.from ?? null); dTo.set(cur.drive?.to ?? null);
          orbit.set(cur.camera?.orbit ?? 0);
          sStyle.set(cur.style ?? '');
          camKeys.set(String(cur.camera?.keys.length ?? 0));
        } else {
          camKeys.set('-');
        }
        const spans = b?.plan.spans ?? [];
        patchList(track, spans, {
          key: (s) => `t${s.id}`,
          create: (s) => {
            const n = el('<button class="an1-block" type="button"></button>');
            n.addEventListener('click', () => { story.shot = s.id; story.stop(); const sp = story.board()?.plan.spans.find((x) => x.id === s.id); if (sp) void story.seek(sp.first); story.emit(); });
            return n;
          },
          update: (n, s) => {
            setText(n, s.name);
            n.style.flexGrow = String(Math.max(s.frames, 1));
            setClass(n, 'is-selected', s.id === story.shot);
            setTitle(n, `${s.name} · ${s.frames}`);
          },
        });
        const total = b?.plan.frames ?? 0;
        slider.max = String(Math.max(0, total - 1));
        if (document.activeElement !== slider && slider.value !== String(story.frame)) slider.value = String(story.frame);
        slider.disabled = total === 0;
        at.set(total ? `${story.frame + 1} / ${total}${story.loading ? ` · ${t('loading')} ${story.loading}` : ''}` : '-');
        setText(q(play, '.an1-lab'), story.playing ? t('Stop') : t('Play'));
        setHidden(q(play, '[data-i="play"]'), story.playing);
        setHidden(q(play, '[data-i="stop"]'), !story.playing);
        setDisabled(play, total === 0);
        setDisabled(close, !story.stage.on);
        setDisabled(cancel, !exportTask);
        const r = lastExport;
        outs[0].set(r ? `${r.frames} · ${r.seconds.toFixed(2)} s · ${r.width}x${r.height}` : '-');
        outs[1].set(r ? `${r.codecString || r.codec} · ${r.container}` : '-');
        outs[2].set(r ? mb(r.size) : '-');
        outs[3].set(r ? r.source : '-');
      };
      story.onChange(paint);
      asm.onChange(paint);
      paint();
      void story.refresh();
      return { show: () => { void story.refresh(); } };
    },
  };
}
