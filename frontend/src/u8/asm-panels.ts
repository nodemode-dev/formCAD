import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setHidden, setText, setValue } from '../ui/dom';
import { pickPath, type FileKind } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import { asm, explanationOf, isAssembly, type Explanation, type ExplodeStep, type MateRow, type TreeNode } from './asm';
import { docUrl, req, text } from './net';
import { button, buttons, checkCtl, fmt, numberCtl, readout, section, selectCtl } from './ui';

const FCAD: FileKind[] = [{ name: 'FormCAD part or assembly', extensions: ['fcad'] }];
const hint = (s: string): void => { document.dispatchEvent(new CustomEvent('formcad:hint', { detail: s })); };

function shell(body: HTMLElement, noteText: string): { live: HTMLElement; paint: () => void } {
  body.classList.add('u8-panel');
  const note = el('<p class="u8-note"></p>');
  setText(note, t(noteText));
  const live = el('<div class="u8-live"></div>');
  live.style.display = 'grid';
  live.style.gap = 'var(--space-2)';
  body.append(note, live);
  const paint = (): void => { const on = isAssembly(); setHidden(note, on); setHidden(live, !on); };
  paint();
  return { live, paint };
}

const act = (label: string, title: string, on: () => void): HTMLButtonElement => {
  const b = el<HTMLButtonElement>('<button class="u8-mini" type="button"></button>');
  if (label.startsWith('@')) b.innerHTML = icon(label.slice(1), 12);
  else b.textContent = label;
  b.title = title;
  b.addEventListener('click', (e) => { e.stopPropagation(); on(); });
  return b;
};

async function guarded(fn: () => Promise<unknown>): Promise<boolean> {
  try { await fn(); return true; } catch (e) { toast(text(e), 'error'); return false; }
}

async function sceneSettled(): Promise<void> {
  await view3d()?.refresh();
  asm.schedule(0);
}

export async function insertComponent(): Promise<void> {
  const id = asm.id();
  if (!id) return;
  const path = await pickPath('open', 'Insert Component', '', FCAD, 'Insert');
  if (!path) return;
  if (await guarded(() => req('POST', docUrl(id, 'assembly/components'), { path }))) {
    await view3d()?.with3d(() => undefined);
    await sceneSettled();
  }
}

export function treePanel(): DockPanel {
  return {
    id: 'asm-tree', label: 'Assembly', icon: 'add', order: 30,
    build(body) {
      const { live, paint } = shell(body, 'Open an assembly to see its components.');
      const bar = buttons(button('Insert component', () => void insertComponent(), 'primary'), button('Refresh', () => void asm.refresh()));
      const list = el('<div class="u8-list" role="tree" aria-label="Components"></div>');
      const status = el('<p class="u8-note"></p>');
      live.append(bar, list, status);
      const id = (): string => asm.id() ?? '';
      const patch = (cid: string, b: Record<string, unknown>): void => { void guarded(() => req('PATCH', docUrl(id(), `assembly/components/${cid}`), b)).then(() => sceneSettled()); };
      const make = (): HTMLElement => {
        const row = el(`<div class="u8-row" role="treeitem"><span class="u8-row-sub u8-dof"></span><span class="u8-row-name"><span class="u8-name-text"></span><span class="u8-sub-mark">${icon('chevronRight', 10)}</span></span><span class="u8-badge"></span><span class="u8-acts"></span></div>`);
        return row;
      };
      const paintRows = (): void => {
        const rows = asm.flat();
        patchList(list, rows, {
          key: (n) => n.key,
          create: () => make(),
          update: (row, n: TreeNode) => {
            const dof = asm.status?.components[n.cid];
            const top = n.depth === 0 && !n.index;
            setText(q(row, '.u8-dof'), top && dof ? String(dof.dof) : '');
            const dofEl = q(row, '.u8-dof');
            if (dofEl.title !== (dof ? `${t('Degrees of freedom')}: ${dof.dof}` : '')) dofEl.title = dof ? `${t('Degrees of freedom')}: ${dof.dof}` : '';
            const name = q(row, '.u8-row-name');
            setText(q(name, '.u8-name-text'), n.label + (n.pattern ? ` [${n.index + 1}]` : ''));
            setClass(q(name, '.u8-sub-mark'), 'is-on', n.type === 'assembly');
            const pad = `${n.depth * 12}px`;
            if (name.style.paddingLeft !== pad) name.style.paddingLeft = pad;
            const badge = q(row, '.u8-badge');
            const st = n.status + (n.stale && n.status === 'loaded' ? ' (copy)' : '');
            setText(badge, st);
            badge.dataset.s = n.status;
            setClass(row, 'is-suppressed', n.suppressed);
            setClass(row, 'is-hidden', !n.visible);
            setClass(row, 'is-selected', top && asm.selected === n.cid);
            const acts = q(row, '.u8-acts');
            if (acts.childElementCount === 0 && top) {
              acts.append(
                act('H', t('Hide or show'), () => { const cur = asm.flat().find((x) => x.key === n.key); patch(n.cid, { visible: !(cur?.visible ?? true) }); }),
                act('S', t('Suppress or restore'), () => { const cur = asm.flat().find((x) => x.key === n.key); patch(n.cid, { suppressed: !(cur?.suppressed ?? false) }); }),
                act('F', t('Find the file'), () => { void guarded(() => req('POST', docUrl(id(), `assembly/components/${n.cid}/find`), { deep: true })).then(() => sceneSettled()); }),
                act('R', t('Replace with another file'), () => { void (async () => { const p = await pickPath('open', 'Replace Component', '', FCAD, 'Replace'); if (p && await guarded(() => req('POST', docUrl(id(), `assembly/components/${n.cid}/replace`), { path: p }))) await sceneSettled(); })(); }),
                act('@refresh', t('Reload from the file'), () => { void guarded(() => req('POST', docUrl(id(), `assembly/components/${n.cid}/reload`), {})).then(() => sceneSettled()); }),
              );
            }
            row.onclick = () => { if (top) asm.select([n.cid]); };
          },
        });
        const miss = asm.tree.length ? asm.flat().filter((n) => n.status === 'missing').length : 0;
        const old = asm.flat().filter((n) => n.status === 'outofdate').length;
        setText(status, asm.tree.length ? `${asm.flat().length} ${t('instances')} · ${miss} ${t('missing')} · ${old} ${t('out of date')}` : '');
      };
      asm.onChange(() => { paint(); if (isAssembly()) paintRows(); });
      void docStore;
      return { show: () => { paint(); void asm.refresh(); } };
    },
  };
}

function explainBox(): { el: HTMLElement; show(x: Explanation | null, remove: (mateId: number) => void): void } {
  const root = el('<div class="u8-explain" hidden><div class="u8-ex-msg"></div><ul class="u8-ex-list"></ul><div class="u8-ex-fixes"></div></div>');
  return {
    el: root,
    show(x, remove) {
      if (!x) { setHidden(root, true); return; }
      setText(q(root, '.u8-ex-msg'), x.message);
      patchList(q(root, '.u8-ex-list'), x.mates, { key: (m) => `m${m.id}`, create: () => el('<li></li>'), update: (n, m) => setText(n, `${m.name}: ${m.text}${m.new ? ` (${t('new')})` : ''}`) });
      patchList(q(root, '.u8-ex-fixes'), x.fixes ?? [], {
        key: (m) => `f${m.id}`,
        create: (m) => { const b = button('', () => remove(m.id)); return b; },
        update: (n, m) => setText(n, `${t('Remove')} ${m.name}`),
      });
      setHidden(root, false);
    },
  };
}

const MATE_KINDS: ReadonlyArray<readonly [string, string]> = [
  ['concentric', 'Concentric'], ['coincident', 'Coincident'], ['distance', 'Distance'], ['angle', 'Angle'], ['parallel', 'Parallel'],
  ['perpendicular', 'Perpendicular'], ['tangent', 'Tangent'], ['lock', 'Lock'],
];

interface Ref { comp: string; face?: number; edge?: number }

export function matesPanel(drag: () => { enabled: boolean; set(on: boolean): void } | null): DockPanel {
  return {
    id: 'asm-mates', label: 'Mates and Motion', icon: 'link', order: 31,
    build(body) {
      const { live, paint } = shell(body, 'Open an assembly to add mates and move it.');
      const state = el('<div class="u8-head"><span class="u8-pill" data-s=""></span> <span class="u8-note u8-solve"></span></div>');
      const pill = q(state, '.u8-pill');
      const solveNote = q(state, '.u8-solve');
      const explain = explainBox();

      const add = section('New mate');
      const kind = selectCtl('Kind', MATE_KINDS);
      const value = numberCtl('Value', 0);
      const refs: Array<Ref | null> = [null, null];
      const refRead = [readout('First reference'), readout('Second reference')];
      let picking = -1;
      const setPick = (i: number): void => {
        const vp = view3d()?.vp;
        if (!vp) return;
        picking = i;
        if (i < 0) { vp.onPick = null; hint(''); return; }
        hint(t('Pick a face or an edge on a component.'));
        vp.onPick = (s) => {
          const f = s.faces[0], e = s.edges[0];
          const bodyId = f ? f.body : e ? e.body : -1;
          const comp = bodyId >= 0 ? asm.componentOfBody(bodyId) : '';
          if (!comp) return;
          refs[i] = f ? { comp, face: f.face } : { comp, edge: (e as { edge: number }).edge };
          refRead[i].set(`${comp} · ${f ? `${t('face')} ${f.face}` : `${t('edge')} ${(e as { edge: number }).edge}`}`);
          setPick(-1);
        };
      };
      const pickA = button('Pick first', () => setPick(picking === 0 ? -1 : 0));
      const pickB = button('Pick second', () => setPick(picking === 1 ? -1 : 1));
      const addBtn = button('Add mate', () => void addMate(), 'primary');
      add.body.append(kind.el, value.el, refRead[0].el, refRead[1].el, buttons(pickA, pickB, addBtn));

      const showExplain = (x: Explanation | null): void => explain.show(x, (mid) => { void guarded(() => req('DELETE', docUrl(asm.id() ?? '', `mates/${mid}`))).then(() => { showExplain(null); return sceneSettled(); }); });
      const addMate = async (): Promise<void> => {
        const id = asm.id();
        if (!id) return;
        if (!refs[0] || (!refs[1] && kind.get() !== 'lock')) { toast(t('Pick both references first.'), 'info'); return; }
        const k = kind.get();
        const list = (k === 'lock' && !refs[1] ? [refs[0], refs[0]] : refs).filter(Boolean);
        try {
          const res = await req<{ ms: number; iterations: number }>('POST', docUrl(id, 'mates'), { kind: k, refs: list, value: k === 'distance' || k === 'angle' ? value.get() : null });
          showExplain(null);
          setText(solveNote, `${t('Solved in')} ${fmt(res.ms, 3)} ms · ${res.iterations} ${t('iterations')}`);
          await view3d()?.refresh();
          asm.showPoses(null);
          asm.schedule(0);
        } catch (e) {
          const x = explanationOf(e);
          if (x) showExplain(x); else toast(text(e), 'error');
        }
      };

      const mates = section('Mates');
      const mlist = el('<div class="u8-list" aria-label="Mates"></div>');
      const solveBtn = button('Solve now', () => void solve());
      mates.body.append(mlist, buttons(solveBtn));
      const solve = async (): Promise<void> => {
        const id = asm.id();
        if (!id) return;
        try {
          const res = await req<{ ms: number; iterations: number }>('POST', docUrl(id, 'mates/solve'));
          showExplain(null);
          setText(solveNote, `${t('Solved in')} ${fmt(res.ms, 3)} ms · ${res.iterations} ${t('iterations')}`);
          await view3d()?.refresh();
          asm.schedule(0);
        } catch (e) {
          const x = explanationOf(e);
          if (x) showExplain(x); else toast(text(e), 'error');
        }
      };

      const dofs = section('Degrees of freedom');
      const dlist = el('<div class="u8-list" aria-label="Degrees of freedom"></div>');
      dofs.body.append(dlist);

      const dr = section('Drive');
      const driveMate = selectCtl('Mate', [['', '-']]);
      const lo = numberCtl('From', 0);
      const hi = numberCtl('To', 360);
      const slider = el<HTMLInputElement>('<input class="u8-slider" type="range" min="0" max="1000" value="0" aria-label="Driven value">');
      const driveRead = readout('Value');
      const dragTog = checkCtl('Drag components', false, () => { drag()?.set(dragTog.get()); });
      const sweepBtn = button('Play range', () => void play());
      const driveRows = new Map<string, { kind: string; value: number }>();
      dr.body.append(driveMate.el, lo.el, hi.el, slider, driveRead.el, dragTog.el, buttons(sweepBtn));
      let inflight = false;
      let wantV: number | null = null;
      const valueAt = (): number => { const a = lo.get() ?? 0, b = hi.get() ?? 1; return a + ((b - a) * Number(slider.value)) / 1000; };
      const previewDrive = async (v: number): Promise<void> => {
        const id = asm.id();
        const mid = driveMate.get();
        if (!id || !mid) return;
        wantV = v;
        if (inflight) return;
        inflight = true;
        try {
          while (wantV !== null) {
            const val = wantV;
            wantV = null;
            const res = await req<{ ok: boolean; samples: Array<{ poses?: Record<string, number[]> }> }>('POST', docUrl(id, `mates/${mid}/drive`), { value: val, commit: false, report: true });
            if (res.ok && res.samples[0]?.poses) asm.showPoses(res.samples[0].poses);
          }
        } catch (e) {
          toast(text(e), 'error');
        } finally {
          inflight = false;
        }
      };
      slider.addEventListener('input', () => { const v = valueAt(); setText(q(driveRead.el, 'output'), fmt(v)); void previewDrive(v); });
      slider.addEventListener('change', () => {
        const id = asm.id();
        const mid = driveMate.get();
        if (!id || !mid) return;
        void (async () => {
          while (inflight) await new Promise((r) => window.setTimeout(r, 20));
          if (await guarded(() => req('POST', docUrl(id, `mates/${mid}/drive`), { value: valueAt(), commit: true }))) await view3d()?.refresh();
          asm.showPoses(null);
          asm.schedule(0);
        })();
      });
      let playing = 0;
      const play = async (): Promise<void> => {
        const id = asm.id();
        const mid = driveMate.get();
        if (!id || !mid) return;
        if (playing) { cancelAnimationFrame(playing); playing = 0; asm.showPoses(null); return; }
        try {
          const res = await req<{ ok: boolean; message: string; samples: Array<{ value: number; poses?: Record<string, number[]> }> }>('POST', docUrl(id, `mates/${mid}/drive`), { start: lo.get() ?? 0, end: hi.get() ?? 360, count: 60, commit: false, report: true });
          if (!res.ok) toast(res.message, 'info');
          let i = 0;
          const tick = (): void => {
            const s = res.samples[i];
            if (!s) { playing = 0; asm.showPoses(null); return; }
            if (s.poses) asm.showPoses(s.poses);
            setText(q(driveRead.el, 'output'), fmt(s.value));
            i++;
            playing = requestAnimationFrame(tick);
          };
          playing = requestAnimationFrame(tick);
        } catch (e) {
          toast(text(e), 'error');
        }
      };

      live.append(state, explain.el, add.root, mates.root, dofs.root, dr.root);

      const paintAll = (): void => {
        paint();
        const st = asm.status;
        pill.dataset.s = st ? (st.state === 'conflict' ? 'fail' : 'pass') : '';
        setText(pill, st ? `${st.state} · ${st.dof} ${t('DOF')}` : '-');
        if (st?.conflict) showExplain(st.conflict);
        patchList(mlist, st?.mates ?? [], {
          key: (m: MateRow) => `m${m.id}`,
          create: (m) => {
            const row = el('<div class="u8-row"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(
              act('S', t('Suppress or restore'), () => { const cur = asm.status?.mates.find((x) => x.id === m.id); void guarded(() => req('PATCH', docUrl(asm.id() ?? '', `mates/${m.id}`), { suppressed: !(cur?.suppressed ?? false) })).then(() => sceneSettled()); }),
              act('@close', t('Delete this mate'), () => { void guarded(() => req('DELETE', docUrl(asm.id() ?? '', `mates/${m.id}`))).then(() => sceneSettled()); }),
            );
            return row;
          },
          update: (row, m) => {
            setText(q(row, '.u8-row-sub'), m.name);
            const n = q(row, '.u8-row-name');
            setText(n, m.text);
            n.title = m.text;
            const b = q(row, '.u8-badge');
            setText(b, m.state);
            b.dataset.s = m.state;
            setClass(row, 'is-suppressed', m.suppressed);
          },
        });
        const comps = Object.entries(st?.components ?? {});
        patchList(dlist, comps, {
          key: ([c]) => c,
          create: () => el('<div class="u8-row"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span></span></div>'),
          update: (row, [c, v]) => {
            setText(q(row, '.u8-row-sub'), c);
            setText(q(row, '.u8-row-name'), `${asm.flat().find((n) => n.cid === c && n.depth === 0)?.label ?? c} · ${v.dof} ${t('DOF')}`);
            const b = q(row, '.u8-badge');
            setText(b, v.state);
            b.dataset.s = v.state;
          },
        });
        if (!isAssembly() || !asm.id()) return;
        void req<{ mates: Array<{ id: number; name: string; label: string; kind: string; value: number | null; suppressed: boolean }> }>('GET', docUrl(asm.id() ?? '', 'mates')).then((r) => {
          driveRows.clear();
          const opts = r.mates.filter((m) => (m.kind === 'distance' || m.kind === 'angle') && !m.suppressed);
          const sel = driveMate.input as HTMLSelectElement;
          const keep = sel.value;
          patchList(sel, opts, {
            key: (m) => String(m.id),
            create: (m) => { const o = document.createElement('option'); o.value = String(m.id); return o; },
            update: (o, m) => { setText(o, `${m.label || m.name} (${m.kind})`); driveRows.set(String(m.id), { kind: m.kind, value: m.value ?? 0 }); },
          });
          if (!opts.length) { if (!sel.querySelector('option[data-none]')) { sel.replaceChildren(); } }
          setValue(sel, keep && driveRows.has(keep) ? keep : opts[0] ? String(opts[0].id) : '');
        }).catch(() => undefined);
      };
      asm.onChange(paintAll);
      const syncRange = (): void => {
        const row = driveRows.get(driveMate.get());
        if (!row) return;
        if (row.kind === 'angle') { lo.set(0); hi.set(360); } else { lo.set(row.value - 25); hi.set(row.value + 25); }
        slider.value = String(Math.round(((row.value - (lo.get() ?? 0)) / Math.max((hi.get() ?? 1) - (lo.get() ?? 0), 1e-9)) * 1000));
        setText(q(driveRead.el, 'output'), fmt(row.value));
      };
      (driveMate.input as HTMLSelectElement).addEventListener('change', syncRange);
      let firstRange = true;
      asm.onChange(() => { if (firstRange && driveRows.size) { firstRange = false; window.setTimeout(syncRange, 0); } });
      return { show: () => { paint(); void asm.refresh(); } };
    },
  };
}

export function explodePanel(): DockPanel {
  return {
    id: 'asm-explode', label: 'Exploded View', icon: 'zoomOut', order: 32,
    build(body) {
      const { live, paint } = shell(body, 'Open an assembly to build an exploded view.');
      const views = selectCtl('View', [['', '-']]);
      const newName = el<HTMLInputElement>('<input class="cv-input" type="text" placeholder="New view name" aria-label="New view name" spellcheck="false">');
      const steps = el('<div class="u8-list" aria-label="Steps"></div>');
      const dir = selectCtl('Direction', [['x', '+X'], ['-x', '-X'], ['y', '+Y'], ['-y', '-Y'], ['z', '+Z'], ['-z', '-Z']]);
      dir.set('z');
      const dist = numberCtl('Distance', 50);
      const scrub = el<HTMLInputElement>('<input class="u8-slider" type="range" min="0" max="1000" value="0" aria-label="Explode position">');
      const url = (tail: string): string => docUrl(asm.id() ?? '', `mates/explode/${encodeURIComponent(views.get())}${tail}`);
      const run = (fn: () => Promise<unknown>): void => { void guarded(fn).then(() => asm.refresh()); };
      const create = button('Create view', () => { const n = newName.value.trim(); if (!n) return; run(async () => { await req('POST', docUrl(asm.id() ?? '', 'mates/explode'), { name: n }); newName.value = ''; }); });
      const auto = button('Suggest steps', () => run(async () => { const n = newName.value.trim() || 'Auto'; await req('POST', docUrl(asm.id() ?? '', 'mates/explode/auto'), { save_as: n }); newName.value = ''; }));
      const addStep = button('Add step from selection', () => {
        const sel = asm.selected;
        const vp = view3d()?.vp;
        const comps = new Set<string>(sel ? [sel] : []);
        if (vp) for (const b of vp.sel.bodies) { const c = asm.componentOfBody(b); if (c) comps.add(c); }
        if (!views.get()) { toast(t('Create a view first.'), 'info'); return; }
        if (!comps.size) { toast(t('Select a component first.'), 'info'); return; }
        run(() => req('POST', url('/steps'), { comps: [...comps], dir: dir.get(), dist: dist.get() ?? 50, name: `Step ${(asm.explode.views[views.get()]?.steps.length ?? 0) + 1}` }));
      });
      const del = button('Delete view', () => { if (views.get()) run(() => req('DELETE', url(''))); }, 'danger');
      live.append(views.el, el('<div class="u8-btns"></div>'), steps, dir.el, dist.el, buttons(addStep, del), scrub);
      const row0 = live.children[1] as HTMLElement;
      row0.append(newName, create, auto);
      const label = readout('Position');
      live.append(label.el);
      const player = buttons(button('Play', () => void animate(true)), button('Collapse', () => void animate(false)));
      live.append(player);

      let frames: Array<Record<string, number[]>> = [];
      let loadedFor = '';
      const ensure = async (): Promise<number> => {
        const v = views.get();
        const n = asm.explode.views[v]?.steps.length ?? 0;
        const stamp = `${v}|${JSON.stringify(asm.explode.views[v]?.steps ?? [])}`;
        if (stamp !== loadedFor) {
          frames = [];
          for (let i = 0; i <= n; i++) {
            const p = await req<{ offsets: Record<string, number[]> }>('GET', url(`/pose?t=${i}`));
            frames.push(p.offsets);
          }
          loadedFor = stamp;
        }
        return n;
      };
      const at = (tt: number): Record<string, number[]> => {
        const i = Math.min(frames.length - 2, Math.max(0, Math.floor(tt)));
        const f = Math.min(1, Math.max(0, tt - i));
        const a = frames[i] ?? {}, b = frames[i + 1] ?? a;
        const out: Record<string, number[]> = {};
        for (const c of new Set([...Object.keys(a), ...Object.keys(b)])) {
          const p = a[c] ?? [0, 0, 0], r = b[c] ?? [0, 0, 0];
          out[c] = [p[0] + (r[0] - p[0]) * f, p[1] + (r[1] - p[1]) * f, p[2] + (r[2] - p[2]) * f];
        }
        return out;
      };
      let raf = 0;
      const show = (tt: number, n: number): void => {
        asm.showOffsets(tt <= 0 ? null : at(tt));
        setText(q(label.el, 'output'), `${fmt(tt, 3)} / ${n}`);
        scrub.value = String(n ? Math.round((tt / n) * 1000) : 0);
      };
      const animate = async (forward: boolean): Promise<void> => {
        if (!views.get()) return;
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
        let n = 0;
        try { n = await ensure(); } catch (e) { toast(text(e), 'error'); return; }
        if (!n) return;
        const t0 = performance.now();
        const total = n * 700;
        const tick = (now: number): void => {
          const k = Math.min(1, (now - t0) / total);
          const eased = k * k * (3 - 2 * k);
          show((forward ? eased : 1 - eased) * n, n);
          raf = k < 1 ? requestAnimationFrame(tick) : 0;
        };
        raf = requestAnimationFrame(tick);
      };
      scrub.addEventListener('input', () => {
        void (async () => {
          if (raf) { cancelAnimationFrame(raf); raf = 0; }
          try { const n = await ensure(); show((Number(scrub.value) / 1000) * n, n); } catch (e) { toast(text(e), 'error'); }
        })();
      });
      (views.input as HTMLSelectElement).addEventListener('change', () => {
        run(async () => { if (views.get()) await req('PUT', url('/active'), {}); });
      });

      const paintAll = (): void => {
        paint();
        const ex = asm.explode;
        const names = Object.keys(ex.views);
        const sel = views.input as HTMLSelectElement;
        const keep = sel.value;
        patchList(sel, names, { key: (n) => n, create: (n) => { const o = document.createElement('option'); o.value = n; return o; }, update: (o, n) => setText(o, n) });
        setValue(sel, names.includes(keep) ? keep : names.includes(ex.active) ? ex.active : names[0] ?? '');
        const list: ExplodeStep[] = ex.views[views.get()]?.steps ?? [];
        patchList(steps, list, {
          key: (s) => `s${s.id}`,
          create: (s) => {
            const row = el('<div class="u8-row"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(
              act('@chevronUp', t('Move earlier'), () => { const i = (asm.explode.views[views.get()]?.steps ?? []).findIndex((x) => x.id === s.id); if (i > 0) run(() => req('POST', url(`/steps/${s.id}/move`), { index: i - 1 })); }),
              act('@chevronDown', t('Move later'), () => { const i = (asm.explode.views[views.get()]?.steps ?? []).findIndex((x) => x.id === s.id); run(() => req('POST', url(`/steps/${s.id}/move`), { index: i + 1 })); }),
              act('@close', t('Delete this step'), () => run(() => req('DELETE', url(`/steps/${s.id}`)))),
            );
            return row;
          },
          update: (row, s) => {
            setText(q(row, '.u8-row-sub'), String(list.indexOf(s) + 1));
            setText(q(row, '.u8-row-name'), `${s.name} · ${s.comps.join(', ')}`);
            setText(q(row, '.u8-badge'), `${fmt(s.dist)}`);
          },
        });
      };
      asm.onChange(paintAll);
      return { show: () => { paint(); void asm.refresh(); } };
    },
  };
}

interface Hit { a: string; b: string; label_a: string; label_b: string; components: string[]; volume?: number; distance?: number }
interface CheckReply { interferences: Hit[]; clearances: Hit[]; count: number; ms: number; bodies: number; errors: unknown[] }

export function checkPanel(): DockPanel {
  return {
    id: 'asm-check', label: 'Interference', icon: 'warning', order: 33,
    build(body) {
      const { live, paint } = shell(body, 'Open an assembly to check it for interference.');
      const clearance = numberCtl('Clearance', 0);
      const head = el('<div class="u8-head"><span class="u8-pill" data-s=""></span> <span class="u8-note u8-ms"></span></div>');
      const pill = q(head, '.u8-pill');
      const ms = q(head, '.u8-ms');
      const list = el('<div class="u8-list" aria-label="Results"></div>');
      const sweepMate = selectCtl('Sweep mate', [['', '-']]);
      const sFrom = numberCtl('From', 0);
      const sTo = numberCtl('To', 360);
      const sCount = numberCtl('Samples', 24);
      const sweepOut = readout('Sweep');
      let rows: Array<{ key: string; main: string; sub: string; comps: string[] }> = [];
      const paintRows = (): void => {
        patchList(list, rows, {
          key: (r) => r.key,
          create: () => el('<div class="u8-row"><span></span><span class="u8-row-name"></span><span class="u8-row-sub"></span><span></span></div>'),
          update: (row, r) => {
            setText(q(row, '.u8-row-name'), r.main);
            setText(q(row, '.u8-row-sub'), r.sub);
            row.onclick = () => { asm.select(r.comps); };
          },
        });
      };
      const check = button('Check interference', () => {
        const id = asm.id();
        if (!id) return;
        void (async () => {
          try {
            const res = await req<CheckReply>('POST', docUrl(id, 'mates/interference'), { clearance: clearance.get() || null });
            pill.dataset.s = res.count === 0 ? 'pass' : 'fail';
            setText(pill, `${res.count} ${t('interferences')}`);
            setText(ms, `${res.bodies} ${t('bodies')} · ${fmt(res.ms, 3)} ms`);
            rows = [
              ...res.interferences.map((h, i) => ({ key: `i${i}`, main: `${h.label_a} / ${h.label_b}`, sub: `${fmt(h.volume)} ${t('volume')}`, comps: h.components })),
              ...res.clearances.map((h, i) => ({ key: `c${i}`, main: `${h.label_a} / ${h.label_b}`, sub: `${fmt(h.distance)} ${t('apart')}`, comps: h.components })),
            ];
            paintRows();
            const all = [...new Set(res.interferences.flatMap((h) => h.components))];
            asm.select(all);
          } catch (e) {
            toast(text(e), 'error');
          }
        })();
      }, 'primary');
      const sweep = button('Check along range', () => {
        const id = asm.id();
        const mid = sweepMate.get();
        if (!id || !mid) return;
        void (async () => {
          try {
            const res = await req<{ rows: Array<{ value: number; count: number }>; samples: number; worst_volume: number; interference_total: number; message?: string }>('POST', docUrl(id, 'mates/interference/sweep'), { mate: mid, start: sFrom.get() ?? 0, end: sTo.get() ?? 360, count: Math.round(sCount.get() ?? 24) });
            const worst = Math.max(0, ...res.rows.map((s) => s.count ?? 0));
            sweepOut.set(`${res.samples} ${t('samples')} · ${t('most interferences')}: ${worst}`);
            pill.dataset.s = worst === 0 ? 'pass' : 'fail';
            setText(pill, `${worst} ${t('interferences')}`);
          } catch (e) {
            toast(text(e), 'error');
          }
        })();
      });
      live.append(clearance.el, buttons(check), head, list, sweepMate.el, sFrom.el, sTo.el, sCount.el, buttons(sweep), sweepOut.el);
      asm.onChange(() => {
        paint();
        if (!isAssembly() || !asm.id()) return;
        void req<{ mates: Array<{ id: number; name: string; label: string; kind: string }> }>('GET', docUrl(asm.id() ?? '', 'mates')).then((r) => {
          const opts = r.mates.filter((m) => m.kind === 'distance' || m.kind === 'angle');
          const sel = sweepMate.input as HTMLSelectElement;
          const keep = sel.value;
          patchList(sel, opts, { key: (m) => String(m.id), create: (m) => { const o = document.createElement('option'); o.value = String(m.id); return o; }, update: (o, m) => setText(o, `${m.label || m.name} (${m.kind})`) });
          setValue(sel, keep || (opts[0] ? String(opts[0].id) : ''));
        }).catch(() => undefined);
      });
      return { show: () => { paint(); void asm.refresh(); } };
    },
  };
}

interface BomRow { item: string; name: string; qty: number; ext_qty: number; part_number: string; description: string; material: string; status: string; level: number; cid: string }
interface BomReply { mode: string; rows: BomRow[]; warnings: string[]; total_parts: number; items: number }

export function bomPanel(): DockPanel {
  return {
    id: 'asm-bom', label: 'Bill of Materials', icon: 'table', order: 34,
    build(body) {
      const { live, paint } = shell(body, 'Open an assembly to see its bill of materials.');
      const mode = selectCtl('Mode', [['indented', 'Indented'], ['top', 'Top level'], ['flat', 'Flat']], () => void load());
      const wrap = el('<div class="u8-list" aria-label="Bill of materials"><table class="u8-table"><thead><tr><th>#</th><th></th><th>Qty</th><th>Part number</th><th>Description</th><th>Material</th><th>Status</th></tr></thead><tbody></tbody></table></div>');
      const tbody = q(wrap, 'tbody');
      const warn = el('<p class="u8-note"></p>');
      const total = readout('Parts');
      const exportBtn = button('Export CSV', () => {
        const id = asm.id();
        if (!id) return;
        void (async () => {
          const p = await pickPath('save', 'Export Bill of Materials', 'bom.csv', [{ name: 'CSV table', extensions: ['csv'] }], 'Export');
          if (p && await guarded(() => req('POST', docUrl(id, 'assembly/bom/export'), { path: p, mode: mode.get() }))) toast(t('Bill of materials exported.'), 'info');
        })();
      });
      live.append(mode.el, wrap, total.el, warn, buttons(button('Refresh', () => void load()), exportBtn));
      const load = async (): Promise<void> => {
        const id = asm.id();
        if (!id || !isAssembly()) return;
        try {
          const r = await req<BomReply>('GET', docUrl(id, `assembly/bom?mode=${mode.get()}`));
          patchList(tbody, r.rows.map((x, i) => ({ ...x, key: `${i}:${x.item}` })), {
            key: (x) => x.key,
            create: () => el('<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>'),
            update: (tr, x) => {
              const c = Array.from(tr.children) as HTMLElement[];
              setText(c[0], String(Number(x.key.split(':')[0]) + 1));
              setText(c[1], x.name);
              c[1].style.paddingLeft = `${x.level * 10 + 4}px`;
              setText(c[2], String(mode.get() === 'flat' ? x.ext_qty : x.qty));
              setText(c[3], x.part_number);
              setText(c[4], x.description);
              setText(c[5], x.material);
              setText(c[6], x.status);
            },
          });
          total.set(`${r.total_parts} · ${r.items} ${t('lines')}`);
          setText(warn, r.warnings.join(' '));
        } catch (e) {
          setText(warn, text(e));
        }
      };
      asm.onChange(() => { paint(); void load(); });
      return { show: () => { paint(); void load(); } };
    },
  };
}
