import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setHidden, setStyleVar, setText, setValue } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { asm, isAssembly } from '../u8/asm';
import { button, buttons, checkCtl, fmt, numberCtl, readout, selectCtl, type Ctl } from '../u8/ui';
import { guard, progressBar, reportBox, req, section, type Json } from './kit';
import { COORD_LABEL, joints, jurl, type ContactSet, type Study, type Track } from './joint-store';
import { FRAME_CAP, run } from './motion-run';
import { PlotView, type Series } from './plot';

const EASES: ReadonlyArray<readonly [string, string]> = [['linear', 'Linear'], ['smooth', 'Smooth'], ['hold', 'Hold']];
const MODES: ReadonlyArray<readonly [string, string]> = [['stop', 'Stop at contact'], ['report', 'Report contacts'], ['off', 'Ignore contacts']];
const TRACK_ROWS = 5;
const KEY_W = 10;

const mini = (label: string, title: string, on: () => void): HTMLButtonElement => {
  const b = el<HTMLButtonElement>('<button class="u8-mini" type="button"></button>');
  if (label.startsWith('@')) b.innerHTML = icon(label.slice(1), 12); else b.textContent = label;
  b.title = title;
  b.addEventListener('click', (e) => { e.stopPropagation(); on(); });
  return b;
};

const tk = (t: Track): string => `${t.joint}.${t.coord}`;
const jname = (id: number | string): string => joints.joint(id)?.name ?? String(id);

let studyId = '';
let contactId = '';

const curStudy = (): Study | undefined => joints.study(studyId) ?? joints.motion.studies[0];
const curContact = (): ContactSet | undefined => joints.motion.contacts.find((c) => c.id === contactId) ?? joints.motion.contacts[0];

async function patchStudy(patch: Json): Promise<void> {
  const s = curStudy();
  if (!s) return;
  await guard(() => req('PATCH', jurl(`motion/studies/${s.id}`), patch));
  joints.schedule(0);
}

function reportLines(): { lines: string[]; bad: boolean } {
  const j = run.job;
  if (run.error && !j) return { lines: [run.error], bad: true };
  if (!j) return { lines: [], bad: false };
  const r = j.result;
  const lines: string[] = [];
  lines.push(`${t(j.kind === 'dynamics' ? 'Dynamics' : 'Study')} · ${t(j.state)}${j.message ? ` · ${j.message}` : ''}`);
  if (r) {
    lines.push(`${r.frames}${r.planned ? ` ${t('of')} ${r.planned}` : ''} ${t('frames')} · ${r.duration ? fmt(r.duration, 4) : fmt(j.progress.t ?? 0, 4)} s${r.solve_ms !== undefined ? ` · ${fmt(r.solve_ms, 4)} ms` : ''}`);
    if (r.stopped) {
      const s = r.stopped;
      const gap = (s as { gap_mm?: number }).gap_mm ?? s.gap;
      lines.push(`${t('Stopped at')} ${fmt(s.time, 5)} s · ${t(s.reason === 'contact' ? 'contact' : s.reason)}${s.pair ? ` ${s.pair.join(' / ')}` : ''}`);
      lines.push(s.reason === 'contact' ? `${t('Gap at the stop')}: ${fmt(gap, 4)} mm` : (s.message ?? ''));
    } else if (j.state === 'cancelled') lines.push(`${t('Cancelled after')} ${fmt(j.progress.t ?? 0, 4)} s`);
    else lines.push(t('Ran to the end without a stop.'));
    lines.push(`${r.contacts.length} ${t('contact events')}`);
  } else lines.push(`${Math.round((j.progress.fraction ?? 0) * 100)} % · t ${fmt(j.progress.t ?? 0, 4)} s`);
  return { lines, bad: j.state === 'failed' };
}

export function motionPanel(): DockPanel {
  return {
    id: 'motion', label: 'Motion Study', icon: 'motion', order: 34,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open an assembly to make a motion study.'));
      const live = el('<div class="u8-live p11-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = isAssembly(); setHidden(note, on); setHidden(live, !on); };

      const sStudy = section('Study');
      const pick = selectCtl('Study', [['', '-']], () => { studyId = pick.get(); paint(); });
      const nameIn = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(nameIn, 'span'), t('Name'));
      const nameInput = q<HTMLInputElement>(nameIn, 'input');
      nameInput.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); nameInput.blur(); } });
      nameInput.addEventListener('change', () => { if (nameInput.value.trim()) void patchStudy({ name: nameInput.value.trim() }); });
      const dur = numberCtl('Duration (s)', 5, () => { const v = dur.get(); if (v !== null && v > 0) void patchStudy({ duration: v }); });
      const fps = numberCtl('Frames per second', 30, () => { const v = fps.get(); if (v !== null && v > 0) void patchStudy({ fps: Math.round(v) }); });
      const newBtn = button('New study', () => void guard(() => req<{ study: Study }>('POST', jurl('motion/studies'), { name: `Study ${joints.motion.studies.length + 1}` })).then((r) => { if (r) { studyId = r.study.id; joints.schedule(0); } }), 'primary');
      const delBtn = button('Delete study', () => { const s = curStudy(); if (s) void guard(() => req('DELETE', jurl(`motion/studies/${s.id}`))).then(() => { studyId = ''; run.clear(); joints.schedule(0); }); }, 'danger');
      sStudy.body.append(pick.el, nameIn, dur.el, fps.el, buttons(newBtn, delBtn));

      const sLine = section('Timeline');
      const tj = selectCtl('Joint', [['', '-']], () => fillCoord());
      const tc = selectCtl('Motion', [['', '-']]);
      const addTrack = button('Add track', () => {
        const s = curStudy();
        if (!s || !tj.get() || !tc.get()) { toast(t('Make a study and choose a joint first.'), 'info'); return; }
        if (s.tracks.some((x) => String(x.joint) === tj.get() && x.coord === tc.get())) { toast(t('That track exists.'), 'info'); return; }
        const j = joints.joint(tj.get());
        const c = j?.coords.find((x) => x.key === tc.get());
        const v = c ? Number(c.value.toFixed(4)) : 0;
        void patchStudy({ tracks: [...s.tracks, { joint: j?.name ?? tj.get(), coord: tc.get(), keys: [{ t: 0, v, ease: 'smooth' }] }] });
      });
      const fillSel = (c: Ctl<string>, opts: Array<readonly [string, string]>): void => {
        const sel = c.input as HTMLSelectElement;
        const keep = sel.value;
        patchList(sel, opts as Array<readonly [string, string]>, { key: (o) => o[0], create: (o) => { const n = document.createElement('option'); n.value = o[0]; return n; }, update: (n, o) => setText(n, o[1]) });
        setValue(sel, opts.some((o) => o[0] === keep) ? keep : opts[0]?.[0] ?? '');
      };
      const fillCoord = (): void => {
        const j = joints.joint(tj.get());
        fillSel(tc, (j ? j.coords.map((c) => c.key) : []).map((k) => [k, t(COORD_LABEL[k] ?? k)] as const));
      };

      const timeline = el('<div class="p11-tl"><div class="p11-tl-rows"></div></div>');
      const rows = q(timeline, '.p11-tl-rows');
      const tlEmpty = el('<p class="u8-note p11-tl-empty"></p>');
      setText(tlEmpty, t('No tracks yet. Choose a joint and add a track.'));
      timeline.style.setProperty('--p11-rows', String(TRACK_ROWS));
      const lanePx = (): void => {
        const lane = rows.querySelector<HTMLElement>('.p11-lane');
        const w = lane ? lane.clientWidth - 12 : timeline.clientWidth - 96 - 28;
        if (w > 0) setStyleVar(timeline, '--p11-lw', `${w}px`);
      };
      new ResizeObserver(lanePx).observe(timeline);
      const scrub = el<HTMLInputElement>('<input class="u8-slider" type="range" min="0" max="1000" value="0" aria-label="Playhead">');
      const timeRead = readout('Time');
      const playBtn = button('Play', () => { run.play(); });
      playBtn.classList.add('p11-wide');
      const kT = numberCtl('Key time (s)', 0);
      const kV = numberCtl('Key value', 0);
      const kE = selectCtl('Easing', EASES);
      let sel: { track: string; i: number } | null = null;
      const selKey = (): { tr: Track; i: number } | null => {
        const s = curStudy();
        if (!s || !sel) return null;
        const tr = s.tracks.find((x) => tk(x) === sel?.track);
        return tr && tr.keys[sel.i] ? { tr, i: sel.i } : null;
      };
      const writeTracks = (mut: (tracks: Track[]) => void): void => {
        const s = curStudy();
        if (!s) return;
        const tracks: Track[] = JSON.parse(JSON.stringify(s.tracks)) as Track[];
        mut(tracks);
        for (const tr of tracks) tr.keys.sort((a, b) => a.t - b.t);
        void patchStudy({ tracks });
      };
      const applyKey = (): void => {
        const k = selKey();
        if (!k || !sel) return;
        const tv = kT.get(), vv = kV.get();
        if (tv === null || vv === null) return;
        const s = curStudy();
        const clamped = Math.max(0, Math.min(tv, s?.duration ?? tv));
        writeTracks((tracks) => {
          const tr = tracks.find((x) => tk(x) === sel?.track);
          if (tr) tr.keys[sel?.i ?? 0] = { t: clamped, v: vv, ease: kE.get() as 'linear' };
        });
      };
      kT.input.addEventListener('change', applyKey);
      kV.input.addEventListener('change', applyKey);
      kE.input.addEventListener('change', applyKey);
      const keyAtHead = button('Key at playhead', () => {
        const s = curStudy();
        if (!s) return;
        const tr = s.tracks.find((x) => tk(x) === sel?.track) ?? s.tracks[0];
        if (!tr) { toast(t('Add a track first.'), 'info'); return; }
        const j = joints.joint(tr.joint);
        const c = j?.coords.find((x) => x.key === tr.coord);
        const fr = run.frameAt(run.at);
        const fromRun = fr?.q?.[j?.name ?? '']?.[tr.coord];
        const v = fromRun ?? c?.value ?? 0;
        const at = Math.round(run.at * 1000) / 1000;
        writeTracks((tracks) => {
          const x = tracks.find((y) => tk(y) === tk(tr));
          if (x) { x.keys.push({ t: at, v: Number(v.toFixed(4)), ease: 'smooth' }); x.keys.sort((a, b) => a.t - b.t); sel = { track: tk(tr), i: x.keys.findIndex((k) => k.t === at) }; }
        });
      });
      const delKey = button('Delete key', () => {
        const k = selKey();
        if (!k || !sel) return;
        writeTracks((tracks) => {
          const tr = tracks.find((x) => tk(x) === sel?.track);
          if (tr) tr.keys.splice(sel?.i ?? 0, 1);
        });
        sel = null;
      }, 'danger');
      const delTrack = button('Delete track', () => {
        const s = curStudy();
        if (!s || !sel) return;
        const id = sel.track;
        sel = null;
        void patchStudy({ tracks: s.tracks.filter((x) => tk(x) !== id) });
      }, 'danger');
      sLine.body.append(tj.el, tc.el, buttons(addTrack), timeline, tlEmpty, scrub, timeRead.el, buttons(playBtn, keyAtHead), kT.el, kV.el, kE.el, buttons(delKey, delTrack));

      let drag: { track: string; i: number; moved: boolean; lane: HTMLElement } | null = null;
      const tAt = (lane: HTMLElement, clientX: number): number => {
        const r = lane.getBoundingClientRect();
        const s = curStudy();
        return Math.max(0, Math.min(1, (clientX - r.left - 6) / Math.max(r.width - 12, 1))) * (s?.duration ?? 1);
      };
      rows.addEventListener('pointerdown', (e) => {
        const target = e.target as HTMLElement;
        const lane = target.closest<HTMLElement>('.p11-lane');
        if (!lane) return;
        const track = lane.dataset.track ?? '';
        const keyEl = target.closest<HTMLElement>('.p11-key');
        if (keyEl) {
          drag = { track, i: Number(keyEl.dataset.i), moved: false, lane };
          sel = { track, i: drag.i };
          lane.setPointerCapture(e.pointerId);
          paint();
        } else {
          sel = { track, i: sel?.track === track ? sel.i : 0 };
          run.seek(tAt(lane, e.clientX));
          paint();
        }
      });
      rows.addEventListener('pointermove', (e) => {
        if (!drag) return;
        drag.moved = true;
        const tt = tAt(drag.lane, e.clientX);
        const s = curStudy();
        const keyEl = drag.lane.querySelector<HTMLElement>(`.p11-key[data-i="${drag.i}"]`);
        if (keyEl && s) setStyleVar(keyEl, '--p11-x', String((tt / s.duration) * 100));
        setValue(kT.input as HTMLInputElement, String(Number(tt.toFixed(3))));
      });
      rows.addEventListener('pointerup', (e) => {
        if (!drag) return;
        const d = drag;
        drag = null;
        if (!d.moved) return;
        const tt = Math.round(tAt(d.lane, e.clientX) * 1000) / 1000;
        writeTracks((tracks) => {
          const tr = tracks.find((x) => tk(x) === d.track);
          if (!tr) return;
          const key = tr.keys[d.i];
          key.t = tt;
          tr.keys.sort((a, b) => a.t - b.t);
          sel = { track: d.track, i: tr.keys.indexOf(key) };
        });
      });
      rows.addEventListener('dblclick', (e) => {
        const lane = (e.target as HTMLElement).closest<HTMLElement>('.p11-lane');
        if (!lane || (e.target as HTMLElement).closest('.p11-key')) return;
        const track = lane.dataset.track ?? '';
        const tt = Math.round(tAt(lane, e.clientX) * 1000) / 1000;
        const tr0 = curStudy()?.tracks.find((x) => tk(x) === track);
        const j = tr0 ? joints.joint(tr0.joint) : undefined;
        const c = j?.coords.find((x) => x.key === tr0?.coord);
        writeTracks((tracks) => {
          const tr = tracks.find((x) => tk(x) === track);
          if (!tr) return;
          tr.keys.push({ t: tt, v: Number((c?.value ?? 0).toFixed(4)), ease: 'smooth' });
          tr.keys.sort((a, b) => a.t - b.t);
          sel = { track, i: tr.keys.findIndex((k) => k.t === tt) };
        });
      });
      scrub.addEventListener('input', () => { const s = curStudy(); run.seek((Number(scrub.value) / 1000) * (run.duration || s?.duration || 1)); });

      const sContact = section('Contact');
      const cMode = selectCtl('When a part touches', MODES, () => { void patchStudy({ contact: { ...(curStudy()?.contact ?? { sets: [] }), mode: cMode.get() } }); });
      const cSets = el('<div class="u8-list p11-csets" role="group" aria-label="Contact sets in this study"></div>');
      const cList = el('<div class="u8-list p11-clist" role="listbox" aria-label="Contact sets"></div>');
      const cName = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(cName, 'span'), t('Set name'));
      const cNameIn = q<HTMLInputElement>(cName, 'input');
      cNameIn.addEventListener('keydown', (e) => e.stopPropagation());
      const cAll = checkCtl('Every part touches every part', false, () => { const c = curContact(); if (c) void guard(() => req('PATCH', jurl(`motion/contacts/${c.id}`), { all: cAll.get() })).then(() => joints.schedule(0)); });
      const cTouch = numberCtl('Counts as touching below', 0, () => { const c = curContact(); const v = cTouch.get(); if (c && v !== null && v >= 0) void guard(() => req('PATCH', jurl(`motion/contacts/${c.id}`), { touch: v })).then(() => joints.schedule(0)); });
      const pA = selectCtl('Part', [['', '-']]);
      const pB = selectCtl('Touches part', [['', '-']]);
      const pairList = el('<div class="u8-list p11-plist" aria-label="Pairs"></div>');
      const cNew = button('New contact set', () => void guard(() => req<{ contact: ContactSet }>('POST', jurl('motion/contacts'), { name: cNameIn.value.trim() || `Contacts ${joints.motion.contacts.length + 1}`, all: false, pairs: [] })).then((r) => { if (r) { contactId = r.contact.id; cNameIn.value = ''; joints.schedule(0); } }), 'primary');
      const cDel = button('Delete set', () => { const c = curContact(); if (c) void guard(() => req('DELETE', jurl(`motion/contacts/${c.id}`))).then(() => { contactId = ''; joints.schedule(0); }); }, 'danger');
      const cPair = button('Add pair', () => {
        const c = curContact();
        if (!c || !pA.get() || !pB.get() || pA.get() === pB.get()) { toast(t('Choose a set and two different parts.'), 'info'); return; }
        const next: Array<[string, string]> = [...c.pairs, [pA.get(), pB.get()]];
        void guard(() => req('PATCH', jurl(`motion/contacts/${c.id}`), { pairs: next })).then(() => joints.schedule(0));
      });
      sContact.body.append(cMode.el, cSets, cName, buttons(cNew, cDel), cList, cAll.el, cTouch.el, pA.el, pB.el, buttons(cPair), pairList);

      const sRun = section('Run');
      const bar = progressBar();
      bar.onCancel(() => { void run.cancel(); });
      const out = reportBox(6);
      const runBtn = button('Run study', () => {
        const s = curStudy();
        if (!s) { toast(t('Make a study first.'), 'info'); return; }
        void run.start(`motion/studies/${s.id}/run`, {});
      }, 'primary');
      const applyBtn = button('Apply the playhead pose', () => { void run.apply(run.at).then((m) => { if (m) toast(m, 'error'); else toast(t('Poses applied as one step.'), 'info'); }); });
      const releaseBtn = button('Back to the model', () => run.release());
      const capNote = el('<p class="u8-note p11-cap"></p>');
      sRun.body.append(buttons(runBtn, applyBtn, releaseBtn), bar.el, out.el, capNote);

      const sPlot = section('Plots');
      const plot = new PlotView();
      plot.onScrub = (tt) => run.seek(tt);
      const plJ = selectCtl('Joint', [['', '-']], () => fillPlotCoord());
      const plC = selectCtl('Motion', [['', '-']]);
      const plotList = el('<div class="u8-list p11-plist" aria-label="Plotted values"></div>');
      const fillPlotCoord = (): void => {
        const j = joints.joint(plJ.get());
        fillSel(plC, (j ? j.coords.map((c) => c.key) : []).map((k) => [k, t(COORD_LABEL[k] ?? k)] as const));
      };
      const plAdd = button('Plot this value', () => {
        const s = curStudy();
        if (!s || !plJ.get() || !plC.get()) return;
        const j = joints.joint(plJ.get());
        if (s.plots.some((p) => String(p.joint) === plJ.get() && p.coord === plC.get())) return;
        void patchStudy({ plots: [...s.plots, { joint: j?.name ?? plJ.get(), coord: plC.get() }] });
      });
      sPlot.body.append(plot.el, plJ.el, plC.el, buttons(plAdd), plotList);

      const sDyn = section('Dynamics');
      const gx = numberCtl('Gravity X (m/s2)', 0), gy = numberCtl('Gravity Y (m/s2)', 0), gz = numberCtl('Gravity Z (m/s2)', -9.81);
      const dens = numberCtl('Density (kg/m3)', 7800);
      const fric = numberCtl('Friction', 0.6);
      const step = numberCtl('Time step (s)', 0.002);
      const servo = numberCtl('Drive stiffness (Hz)', 20);
      const damp = numberCtl('Drive damping ratio', 1);
      const loop = numberCtl('Loop closure time constant (s)', 0.005);
      const soft = numberCtl('Contact softness (s)', 0.006);
      const setBtn = button('Apply settings', () => {
        const v = { gravity: [gx.get() ?? 0, gy.get() ?? 0, gz.get() ?? -9.81], density: dens.get(), friction: fric.get(), timestep: step.get(), servo_hz: servo.get(), damping_ratio: damp.get(), solref_loop: loop.get(), contact_time: soft.get() };
        void guard(() => req('PUT', jurl('motionsettings'), v)).then(() => joints.schedule(0));
      });
      const dDur = numberCtl('Run for (s)', 2);
      const dFps = numberCtl('Record frames per second', 60);
      const dStop = checkCtl('Stop at the first contact', false);
      const dStudy = checkCtl('Follow this study', true);
      const freeList = el('<div class="u8-list p11-free" role="group" aria-label="Parts that may fall"></div>');
      const dSets = el('<div class="u8-list p11-csets" role="group" aria-label="Contact sets for dynamics"></div>');
      const dBar = progressBar();
      dBar.onCancel(() => { void run.cancel(); });
      const dRun = button('Run dynamics', () => {
        const s = curStudy();
        const free = [...freeList.querySelectorAll<HTMLInputElement>('input:checked')].map((i) => i.value);
        const sets = [...dSets.querySelectorAll<HTMLInputElement>('input:checked')].map((i) => i.value);
        const body: Json = { duration: dDur.get() ?? 2, record_fps: dFps.get() ?? 60, free, contacts: sets, stop_on_contact: dStop.get() };
        const st = step.get();
        if (st) body.timestep = st;
        if (dStudy.get() && s) body.study = s.id;
        void run.start('motion/dynamics/run', body);
      }, 'primary');
      sDyn.body.append(gx.el, gy.el, gz.el, dens.el, fric.el, step.el, servo.el, damp.el, loop.el, soft.el, buttons(setBtn), dDur.el, dFps.el, dStudy.el, dStop.el, el('<p class="xw-sub p11-freehead"></p>'), freeList, el('<p class="xw-sub p11-setshead"></p>'), dSets, buttons(dRun), dBar.el);
      setText(sDyn.body.querySelector('.p11-freehead') as HTMLElement, t('Parts that may fall'));
      setText(sDyn.body.querySelector('.p11-setshead') as HTMLElement, t('Contact sets to use'));

      live.append(sStudy.root, sLine.root, sContact.root, sRun.root, sPlot.root, sDyn.root);

      const checkRows = (host: HTMLElement, opts: Array<readonly [string, string]>, checked: (id: string) => boolean, on: (id: string, v: boolean) => void): void => {
        patchList(host, opts as Array<readonly [string, string]>, {
          key: (o) => o[0],
          create: (o) => {
            const row = el('<label class="u8-row p11-check"><input type="checkbox"><span class="u8-row-name"></span></label>');
            const box = q<HTMLInputElement>(row, 'input');
            box.value = o[0];
            box.addEventListener('change', () => on(o[0], box.checked));
            return row;
          },
          update: (row, o) => {
            setText(q(row, '.u8-row-name'), o[1]);
            const box = q<HTMLInputElement>(row, 'input');
            const v = checked(o[0]);
            if (box.checked !== v && document.activeElement !== box) box.checked = v;
          },
        });
      };

      let lastSig = '';
      let lastTracks = -1;
      const paint = (): void => {
        paintShell();
        const st = curStudy();
        if (st) studyId = st.id;
        fillSel(pick, joints.motion.studies.map((s) => [s.id, s.name] as const));
        setValue(pick.input as HTMLSelectElement, st?.id ?? '');
        if (st) {
          setValue(nameInput, st.name);
          dur.set(st.duration); fps.set(st.fps);
          setValue(cMode.input as HTMLSelectElement, st.contact.mode);
        }
        fillSel(tj, joints.joints.map((j) => [String(j.id), `${j.name} · ${j.label || j.type}`] as const));
        fillCoord();
        fillSel(plJ, joints.joints.map((j) => [String(j.id), `${j.name} · ${j.label || j.type}`] as const));
        fillPlotCoord();
        const dur1 = st?.duration ?? 1;

        patchList(rows, st?.tracks ?? [], {
          key: tk,
          create: (tr) => {
            const row = el('<div class="p11-trow"><span class="p11-tname"></span><div class="p11-lane"></div></div>');
            q(row, '.p11-lane').dataset.track = tk(tr);
            return row;
          },
          update: (row, tr) => {
            const name = `${jname(tr.joint)} · ${t(COORD_LABEL[tr.coord] ?? tr.coord)}`;
            const n = q(row, '.p11-tname');
            setText(n, name);
            if (n.title !== name) n.title = name;
            setClass(row, 'is-selected', sel?.track === tk(tr));
            patchList(q(row, '.p11-lane'), tr.keys.map((k, i) => ({ k, i })), {
              key: (o) => `k${o.i}`,
              create: (o) => { const b = el<HTMLButtonElement>('<button class="p11-key" type="button"></button>'); b.dataset.i = String(o.i); return b; },
              update: (b, o) => {
                setStyleVar(b, '--p11-x', String((o.k.t / dur1) * 100));
                const tt = `t ${fmt(o.k.t, 4)} s · ${fmt(o.k.v, 5)} · ${t(o.k.ease)}`;
                if (b.title !== tt) b.title = tt;
                setClass(b, 'is-selected', sel?.track === tk(tr) && sel.i === o.i);
                setClass(b, 'is-hold', o.k.ease === 'hold');
              },
            });
          },
        });
        setHidden(tlEmpty, (st?.tracks.length ?? 0) > 0);
        if (!timeline.style.getPropertyValue('--p11-lw') || (st?.tracks.length ?? 0) !== lastTracks) { lastTracks = st?.tracks.length ?? 0; lanePx(); }
        const k = selKey();
        if (k) { kT.set(Number(k.tr.keys[k.i].t.toFixed(4))); kV.set(Number(k.tr.keys[k.i].v.toFixed(5))); setValue(kE.input as HTMLSelectElement, k.tr.keys[k.i].ease); }
        for (const c of [kT, kV, kE]) setDisabled(c.input as HTMLInputElement, !k);

        const total = run.duration || dur1;
        const pos = total > 0 ? run.at / total : 0;
        setStyleVar(timeline, '--p11-t', String(Math.max(0, Math.min(1, run.at / dur1)) * 100));
        if (document.activeElement !== scrub) scrub.value = String(Math.round(Math.max(0, Math.min(1, pos)) * 1000));
        setText(q(timeRead.el, 'output'), `${fmt(run.at, 5)} s / ${fmt(total, 5)} s`);
        setText(playBtn, run.playing ? t('Stop') : t('Play'));
        setDisabled(playBtn, !run.frames.length);
        setDisabled(applyBtn, !run.frames.length);
        setDisabled(releaseBtn, !run.frames.length);

        const sets = joints.motion.contacts;
        checkRows(cSets, sets.map((c) => [c.id, c.name] as const), (id) => !!st?.contact.sets.includes(id), (id, v) => {
          const cur = curStudy();
          if (!cur) return;
          const next = v ? [...new Set([...cur.contact.sets, id])] : cur.contact.sets.filter((x) => x !== id);
          void patchStudy({ contact: { ...cur.contact, sets: next } });
        });
        patchList(cList, sets, {
          key: (c) => c.id,
          create: (c) => { const row = el('<div class="u8-row"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span></span></div>'); row.addEventListener('click', () => { contactId = c.id; paint(); }); return row; },
          update: (row, c) => {
            setText(q(row, '.u8-row-sub'), c.id);
            setText(q(row, '.u8-row-name'), c.name);
            setText(q(row, '.u8-badge'), c.all ? t('all') : `${c.pairs.length} ${t('pairs')}`);
            setClass(row, 'is-selected', curContact()?.id === c.id);
          },
        });
        const cc = curContact();
        if (cc) { cAll.set(cc.all); cTouch.set(cc.touch); }
        for (const c of [cAll, cTouch, pA, pB]) setDisabled(c.input as HTMLInputElement, !cc);
        const comps = asm.tree.map((n) => [n.cid, `${n.cid} · ${n.label}`] as const);
        fillSel(pA, comps);
        fillSel(pB, comps);
        patchList(pairList, (cc?.pairs ?? []).map((p, i) => ({ p, i })), {
          key: (o) => `p${o.i}${o.p.join('-')}`,
          create: (o) => {
            const row = el('<div class="u8-row"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(mini('@close', t('Remove this pair'), () => {
              const c = curContact();
              if (!c) return;
              void guard(() => req('PATCH', jurl(`motion/contacts/${c.id}`), { pairs: c.pairs.filter((_, k2) => k2 !== o.i) })).then(() => joints.schedule(0));
            }));
            return row;
          },
          update: (row, o) => { setText(q(row, '.u8-row-sub'), String(o.i + 1)); setText(q(row, '.u8-row-name'), `${o.p[0]} / ${o.p[1]}`); },
        });
        setHidden(pairList, false);

        const j = run.job;
        const busy = !!j && (j.state === 'running' || j.state === 'queued');
        const frac = j?.progress.fraction ?? 0;
        const label = j ? `${t(j.kind)} · ${Math.round(frac * 100)} % · t ${fmt(j.progress.t ?? 0, 3)} s${j.progress.steps ? ` · ${j.progress.steps} ${t('steps')}` : ''}` : '';
        (j?.kind === 'dynamics' ? dBar : bar).set(frac, label, busy);
        (j?.kind === 'dynamics' ? bar : dBar).set(0, '', false);
        setDisabled(runBtn, busy);
        setDisabled(dRun, busy);
        const rep = reportLines();
        out.set(rep.lines, rep.bad);

        const results = j?.result?.plots ?? [];
        const series: Series[] = results.map((p) => ({ name: `${jname(p.joint)} ${p.coord}`, t: p.t, v: p.v, unit: p.unit }));
        const stopT = j?.result?.stopped?.time ?? null;
        const sig = `${j?.id ?? ''}|${j?.state ?? ''}|${series.length}|${run.frames.length}|${stopT}`;
        if (sig !== lastSig) { lastSig = sig; plot.set(series, run.at, stopT); } else plot.setCursor(run.at);
        patchList(plotList, st?.plots ?? [], {
          key: (p) => `${p.joint}.${p.coord}`,
          create: (p) => {
            const row = el('<div class="u8-row"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(mini('@close', t('Remove this plot'), () => { const cur = curStudy(); if (cur) void patchStudy({ plots: cur.plots.filter((x) => !(String(x.joint) === String(p.joint) && x.coord === p.coord)) }); }));
            return row;
          },
          update: (row, p) => { setText(q(row, '.u8-row-name'), `${jname(p.joint)} · ${t(COORD_LABEL[p.coord] ?? p.coord)}`); },
        });

        checkRows(freeList, asm.tree.map((n) => [n.cid, `${n.cid} · ${n.label}`] as const), (id) => (freeSet.has(id)), (id, v) => { if (v) freeSet.add(id); else freeSet.delete(id); });
        checkRows(dSets, sets.map((c) => [c.id, c.name] as const), (id) => dynSets.has(id), (id, v) => { if (v) dynSets.add(id); else dynSets.delete(id); });
        const dy = joints.motion.dynamics;
        if (dy) {
          gx.set(dy.gravity[0]); gy.set(dy.gravity[1]); gz.set(dy.gravity[2]);
          dens.set(dy.density); fric.set(dy.friction); step.set(dy.timestep); servo.set(dy.servo_hz); damp.set(dy.damping_ratio); loop.set(dy.solref_loop); soft.set(dy.contact_time ?? 0.006);
        }
        const lim = joints.motion.limits.window;
        setText(capNote, lim ? `${t('Limits')}: ${lim.frames} ${t('frames')} · ${lim.duration} s · ${t('dynamics')} ${lim.dyn_duration} s, ${lim.dyn_bodies} ${t('bodies')}${(joints.motion.limits.restricted?.frames ?? 0) ? ` · ${t('macros')} ${joints.motion.limits.restricted?.frames} ${t('frames')}` : ''} · ${t('shown')} ${FRAME_CAP}` : '');
      };
      const freeSet = new Set<string>();
      const dynSets = new Set<string>();
      joints.onChange(paint);
      run.onChange(paint);
      asm.onChange(() => paint());
      paintShell();
      return { show: () => { paintShell(); joints.schedule(0); } };
    },
  };
}
