import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setValue } from '../ui/dom';
import { pickPath, type FileKind } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { button, buttons, checkCtl, readout, selectCtl, type Ctl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { CommentLayer, entityHandle } from './comment-layer';
import { bytes, guard, isoTime, reportBox, req, section, type Json } from './kit';
import { graphView } from './vault-graph';
import { vstore, type Comment, type Conflict, type DiffRec, type VDoc } from './vault-store';

const FCAD: FileKind[] = [{ name: 'FormCAD part or assembly', extensions: ['fcad'] }];
const STATES: ReadonlyArray<readonly [string, string]> = [['wip', 'Work in progress'], ['review', 'In review'], ['released', 'Released'], ['obsolete', 'Obsolete']];
const tail = (p: string): string => p.split(/[\\/]/).pop() ?? p;

export const commentLayer: { layer: CommentLayer | null } = { layer: null };

const mini = (label: string, title: string, on: () => void): HTMLButtonElement => {
  const b = el<HTMLButtonElement>('<button class="u8-mini" type="button"></button>');
  if (label.startsWith('@')) b.innerHTML = icon(label.slice(1), 12); else b.textContent = label;
  b.title = title;
  b.addEventListener('click', (e) => { e.stopPropagation(); on(); });
  return b;
};

const short = (v: unknown): string => {
  if (v === null || v === undefined) return t('(none)');
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s.length > 38 ? `${s.slice(0, 36)}...` : s;
};

function describe(item: unknown): string {
  if (!item || typeof item !== 'object') return String(item);
  const o = item as Json;
  if (typeof o.from_name === 'string') return [o.from_name, o.comp, o.short, o.state && `${o.state}${o.revision ? ` ${String(o.revision)}` : ''}`, o.mode].filter(Boolean).join(' · ');
  if (typeof o.comp === 'string' && typeof o.doc === 'string') return [o.comp, o.name, o.mode, o.in_vault === false ? t('not in the vault') : o.state && `${String(o.state)}${o.revision ? ` ${String(o.revision)}` : ''}`].filter(Boolean).join(' · ');
  const parts: string[] = [];
  for (const k of ['name', 'doc_name', 'doc', 'comp', 'to_doc', 'from_doc', 'path', 'branch', 'version', 'state', 'revision', 'status', 'reason']) {
    const v = o[k];
    if (v !== undefined && v !== null && v !== '') parts.push(typeof v === 'string' ? (v.length > 14 && /^[0-9a-f]+$/.test(v) ? v.slice(0, 12) : v) : JSON.stringify(v));
  }
  return parts.join(' · ') || JSON.stringify(item).slice(0, 80);
}

export function vaultPanel(): DockPanel {
  return {
    id: 'vault', label: 'Vault', icon: 'vault', order: 36,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note p11-vnote"></p>');
      body.append(note);
      const live = el('<div class="u8-live p11-live"></div>');
      body.append(live);

      const run = async <T,>(fn: () => Promise<T>, done?: string): Promise<T | null> => {
        const r = await guard(fn);
        if (r !== null && done) toast(t(done), 'info');
        await vstore.refresh();
        return r;
      };
      const vurl = (tailPath: string): string => vstore.base(tailPath);

      const sDoc = section('This document');
      const vsel = selectCtl('Vault', [['default', 'default']], () => { vstore.vid = vsel.get(); vstore.docId = ''; void vstore.refresh(); });
      const bindRead = readout('Bound to');
      const statusRead = readout('Status');
      const lockRead = readout('Lock');
      const message = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(message, 'span'), t('Message'));
      const msgInput = q<HTMLInputElement>(message, 'input');
      msgInput.addEventListener('keydown', (e) => e.stopPropagation());
      const branchSel = selectCtl('Branch', [['', '-']]);
      const keepLock = checkCtl('Keep the lock after check-in', false);
      const intoSel = checkCtl('Add to the selected vault document', false);
      const checkin = button('Check in', () => {
        const id = docStore.activeId;
        if (!id) { toast(t('Open a document first.'), 'info'); return; }
        const b = vstore.binding?.binding;
        const args: Json = { doc_session: id, message: msgInput.value.trim() || t('Check-in'), keep_lock: keepLock.get() };
        if (b) args.doc = b.doc; else if (intoSel.get() && vstore.docId) args.doc = vstore.docId; else args.name = (docStore.current()?.name ?? 'Untitled').replace(/\.fcad$/i, '');
        if (branchSel.get()) args.branch = branchSel.get();
        void run(() => req('POST', vurl('/checkin'), args), 'Checked in.').then((r) => { if (r) msgInput.value = ''; });
      }, 'primary');
      const coBtn = button('Check out for editing', () => void checkout(true));
      const roBtn = button('Open this version', () => void checkout(false));
      const undoBtn = button('Undo check-out', () => {
        const b = vstore.binding?.binding;
        if (b) void run(() => req('POST', vurl('/undo-checkout'), { path: b.path }), 'Check-out undone.');
      });
      const lockBtn = button('Lock', () => { const d = vstore.doc(); if (d) void run(() => req('POST', vurl(`/docs/${d.id}/lock`), {}), 'Locked.'); });
      const unlockBtn = button('Unlock', () => { const d = vstore.doc(); if (d) void run(() => req('DELETE', vurl(`/docs/${d.id}/lock`), {}), 'Unlocked.'); });
      const breakBtn = button('Break lock', () => { const d = vstore.doc(); if (d) void run(() => req('DELETE', vurl(`/docs/${d.id}/lock?force=true&note=${encodeURIComponent(msgInput.value.trim())}`), undefined), 'Lock broken. The other work is kept as a branch.'); }, 'danger');
      const newVault = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(newVault, 'span'), t('New vault name'));
      const nvInput = q<HTMLInputElement>(newVault, 'input');
      nvInput.addEventListener('keydown', (e) => e.stopPropagation());
      const nvBtn = button('Create vault', () => { const n = nvInput.value.trim(); if (!n) return; void run(() => req('POST', vault0(), { name: n }), 'Vault created.').then((r) => { if (r) nvInput.value = ''; }); });
      const vault0 = (): string => '/api/vault';
      sDoc.body.append(vsel.el, bindRead.el, statusRead.el, lockRead.el, message, branchSel.el, keepLock.el, intoSel.el, buttons(checkin, coBtn, roBtn), buttons(undoBtn, lockBtn, unlockBtn, breakBtn), newVault, buttons(nvBtn));

      const checkout = async (edit: boolean): Promise<void> => {
        const d = vstore.doc();
        if (!d) { toast(t('Choose a document in the list first.'), 'info'); return; }
        const name = `${d.name.replace(/\.fcad$/i, '')}${edit ? '' : `-${vstore.selected.slice(0, 7)}`}.fcad`;
        const path = await pickPath('save', edit ? 'Check out for editing' : 'Open this version', name, FCAD, edit ? 'Check out' : 'Open');
        if (!path) return;
        const args: Json = { path, edit, open: true };
        if (edit) args.branch = branchSel.get() || d.default_branch; else args.version = vstore.selected;
        await run(() => req('POST', vurl(`/docs/${d.id}/checkout`), args), edit ? 'Checked out.' : 'Opened.');
        void docStore.refresh();
      };

      const sDocs = section('Documents');
      const dlist = el('<div class="u8-list p11-vlist" role="listbox" aria-label="Documents in the vault"></div>');
      const dempty = el('<p class="u8-note p11-vempty"></p>');
      setText(dempty, t('The vault has no documents yet. Check one in.'));
      sDocs.body.append(dlist, dempty);

      const sHist = section('History');
      const graph = graphView((id, compare) => {
        if (compare) { vstore.compare = vstore.compare === id ? '' : id; vstore.emit(); void showDiff(); } else void vstore.pickVersion(id);
      });
      const vRead = [readout('Version'), readout('Saved'), readout('Stored')];
      const nameIn = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(nameIn, 'span'), t('Branch or tag name'));
      const nameInput = q<HTMLInputElement>(nameIn, 'input');
      nameInput.addEventListener('keydown', (e) => e.stopPropagation());
      const mkBranch = button('Branch from here', () => {
        const d = vstore.doc();
        if (!d || !nameInput.value.trim()) { toast(t('Type a branch name.'), 'info'); return; }
        void run(() => req('POST', vurl(`/docs/${d.id}/branches`), { name: nameInput.value.trim(), frm: vstore.selected }), 'Branch made.').then((r) => { if (r) nameInput.value = ''; });
      });
      const mkTag = button('Tag this version', () => {
        const d = vstore.doc();
        if (!d || !nameInput.value.trim()) { toast(t('Type a tag name.'), 'info'); return; }
        void run(() => req('POST', vurl(`/docs/${d.id}/tags`), { name: nameInput.value.trim(), version: vstore.selected }), 'Tag made.').then((r) => { if (r) nameInput.value = ''; });
      });
      const diffBtn = button('Compare with the marked version', () => void showDiff());
      const diffList = el('<div class="u8-list p11-difflist" aria-label="Changes between versions"></div>');
      const diffNote = el('<p class="u8-note p11-diffnote"></p>');
      sHist.body.append(graph.el, vRead[0].el, vRead[1].el, vRead[2].el, nameIn, buttons(mkBranch, mkTag, diffBtn), diffNote, diffList);

      const showDiff = async (): Promise<void> => {
        const d = vstore.doc();
        if (!d || !vstore.selected) return;
        if (!vstore.compare) { setText(diffNote, t('Shift-click another version to mark it, then compare.')); return; }
        const r = await guard(() => req<DiffRec>('GET', vurl(`/diff?a=${vstore.compare}&b=${vstore.selected}&limit=200`)));
        if (!r) return;
        const sum = (r as unknown as { summary?: Record<string, number> }).summary ?? {};
        setText(diffNote, `${vstore.compare.slice(0, 7)} → ${vstore.selected.slice(0, 7)} · ${sum.added ?? 0} ${t('added')} · ${sum.removed ?? 0} ${t('removed')} · ${sum.changed ?? 0} ${t('changed')} · ${sum.reordered ?? 0} ${t('reordered')}`);
        const items = ((r as unknown as { items?: Array<{ entity: string; name: string; change: string; fields: unknown[] }> }).items ?? []);
        patchList(diffList, items, {
          key: (i) => `${i.change}${i.entity}`,
          create: () => el('<div class="u8-row p11-drow"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span></span></div>'),
          update: (row, i) => { setText(q(row, '.u8-row-sub'), i.change); setText(q(row, '.u8-row-name'), i.name); const b = q(row, '.u8-badge'); setText(b, i.fields.length ? `${i.fields.length}` : ''); const n = q(row, '.u8-row-name'); if (n.title !== i.entity) n.title = i.entity; },
        });
      };

      const sBr = section('Branches');
      const blist = el('<div class="u8-list p11-blist" aria-label="Branches"></div>');
      const src = selectCtl('Merge this branch', [['', '-']]);
      const into = selectCtl('Into', [['', '-']]);
      const mergeBtn = button('Start merge', () => {
        const d = vstore.doc();
        if (!d || !src.get() || src.get() === into.get()) { toast(t('Choose two different branches.'), 'info'); return; }
        void run(() => req('POST', vurl(`/docs/${d.id}/merge`), { source: src.get(), branch: into.get() }));
      }, 'primary');
      const renameIn = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(renameIn, 'span'), t('Rename selected to'));
      const renInput = q<HTMLInputElement>(renameIn, 'input');
      renInput.addEventListener('keydown', (e) => e.stopPropagation());
      let selBranch = '';
      const renBtn = button('Rename', () => {
        const d = vstore.doc();
        if (!d || !selBranch || !renInput.value.trim()) return;
        void run(() => req('PATCH', vurl(`/docs/${d.id}/branches/${encodeURIComponent(selBranch)}`), { to: renInput.value.trim() }), 'Branch renamed.').then((r) => { if (r) { renInput.value = ''; selBranch = ''; } });
      });
      sBr.body.append(blist, renameIn, buttons(renBtn), src.el, into.el, buttons(mergeBtn));

      const sConf = section('Conflicts');
      const mState = reportBox(3);
      const clist = el('<div class="p11-conflicts" role="list" aria-label="Merge conflicts"></div>');
      const cempty = el('<p class="u8-note p11-cempty"></p>');
      const mmsg = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(mmsg, 'span'), t('Merge message'));
      const mmInput = q<HTMLInputElement>(mmsg, 'input');
      mmInput.addEventListener('keydown', (e) => e.stopPropagation());
      const completeBtn = button('Complete merge', () => {
        const d = vstore.doc();
        if (d) void run(() => req('POST', vurl(`/docs/${d.id}/merge/complete`), { message: mmInput.value.trim() || undefined }), 'Merged.').then((r) => { if (r) mmInput.value = ''; });
      }, 'primary');
      const abortBtn = button('Abort merge', () => { const d = vstore.doc(); if (d) void run(() => req('DELETE', vurl(`/docs/${d.id}/merge`), {}), 'Merge aborted.'); }, 'danger');
      const allOurs = button('Take ours for all', () => chooseAll('ours'));
      const allTheirs = button('Take theirs for all', () => chooseAll('theirs'));
      sConf.body.append(mState.el, clist, cempty, mmsg, buttons(allOurs, allTheirs), buttons(completeBtn, abortBtn));
      const choose = (c: Conflict, v: string): void => {
        const d = vstore.doc();
        if (d) void run(() => req('PUT', vurl(`/docs/${d.id}/merge`), { choices: { [c.id]: v } }));
      };
      const chooseAll = (v: string): void => {
        const d = vstore.doc();
        const m = vstore.merge;
        if (!d || !m) return;
        const choices: Record<string, string> = {};
        for (const c of m.conflicts) choices[c.id] = v;
        void run(() => req('PUT', vurl(`/docs/${d.id}/merge`), { choices }));
      };

      const sLife = section('Lifecycle');
      const lState = selectCtl('State', STATES);
      const lNote = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(lNote, 'span'), t('Note'));
      const lNoteInput = q<HTMLInputElement>(lNote, 'input');
      lNoteInput.addEventListener('keydown', (e) => e.stopPropagation());
      const cascade = checkCtl('Release the parts it uses too', false);
      const lApply = button('Set state', () => {
        if (!vstore.selected) return;
        const args: Json = { state: lState.get(), cascade: cascade.get() };
        if (lNoteInput.value.trim()) args.note = lNoteInput.value.trim();
        void run(() => req('POST', vurl(`/versions/${vstore.selected}/state`), args), 'State changed.').then((r) => { if (r) lNoteInput.value = ''; });
      }, 'primary');
      const revise = button('Revise (new working version)', () => { const d = vstore.doc(); if (d) void run(() => req('POST', vurl(`/docs/${d.id}/revise`), {}), 'Revised.'); });
      const verify = button('Verify storage', () => {
        const d = vstore.doc();
        if (!d) return;
        void guard(() => req<Json>('POST', vurl('/verify'), { doc: d.id })).then((r) => { if (r) toast(`${t('Verified')}: ${JSON.stringify(r).slice(0, 120)}`, 'info'); });
      });
      const audit = el('<div class="u8-list p11-audit" aria-label="Audit log"></div>');
      sLife.body.append(lState.el, lNote, cascade.el, buttons(lApply, revise, verify), audit);

      const sUsed = section('Where used');
      const scope = selectCtl('Search', [['heads', 'Current heads'], ['all', 'All versions']], () => void reloadUsed());
      const usedList = el('<div class="u8-list p11-used" aria-label="Where this document is used"></div>');
      const usesList = el('<div class="u8-list p11-used" aria-label="What this document uses"></div>');
      sUsed.body.append(scope.el, el('<p class="xw-sub p11-usedhead"></p>'), usedList, el('<p class="xw-sub p11-useshead"></p>'), usesList);
      setText(sUsed.body.querySelector('.p11-usedhead') as HTMLElement, t('Used by'));
      setText(sUsed.body.querySelector('.p11-useshead') as HTMLElement, t('Uses'));
      const reloadUsed = async (): Promise<void> => {
        const d = vstore.doc();
        if (!d) return;
        const w = await guard(() => req<unknown>('GET', vurl(`/docs/${d.id}/whereused?scope=${scope.get()}${vstore.selected ? `&version=${vstore.selected}` : ''}`)));
        if (w) { const o = w as Json; vstore.whereUsed = [].concat((o.used_by ?? o.items ?? o.whereused ?? (Array.isArray(w) ? w : [])) as []); }
        vstore.emit();
      };

      const sCom = section('Comments');
      const cfilter = selectCtl('Show', [['', 'All'], ['open', 'Open'], ['resolved', 'Resolved']], () => { vstore.commentStatus = cfilter.get(); void vstore.side().then(() => vstore.emit()); });
      const comList = el('<div class="u8-list p11-comments" role="list" aria-label="Comments"></div>');
      const comEmpty = el('<p class="u8-note p11-cempty"></p>');
      setText(comEmpty, t('No comments on this version.'));
      const anchorRead = readout('Pinned to');
      const bodyIn = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(bodyIn, 'span'), t('Comment'));
      const bodyInput = q<HTMLInputElement>(bodyIn, 'input');
      bodyInput.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); void addComment(); } });
      const withCam = checkCtl('Keep the camera', true);
      const markBtn = button('Draw markup', () => toggleMarkup());
      markBtn.classList.add('p11-wide');
      const clearMark = button('Clear markup', () => { commentLayer.layer?.overlay.clear(); toggleMarkup(false); });
      const showMarks = checkCtl('Show comment markers in the view', true, () => commentLayer.layer?.setShown(showMarks.get()));
      let replyTo: number | null = null;
      const replyRead = readout('Replying to');
      const cancelReply = button('Cancel reply', () => { replyTo = null; paintReply(); });
      const addBtn = button('Add comment', () => void addComment(), 'primary');
      sCom.body.append(cfilter.el, comList, comEmpty, anchorRead.el, bodyIn, withCam.el, buttons(markBtn, clearMark), replyRead.el, buttons(addBtn, cancelReply), showMarks.el);

      const toggleMarkup = (force?: boolean): void => {
        const ov = commentLayer.layer?.overlay;
        if (!ov) return;
        const on = force ?? !ov.drawing;
        ov.setDrawing(on);
        setText(markBtn, on ? t('Finish markup') : t('Draw markup'));
      };
      const paintReply = (): void => {
        setHidden(replyRead.el, replyTo === null);
        setDisabled(cancelReply, replyTo === null);
        if (replyTo !== null) setText(q(replyRead.el, 'output'), `#${replyTo}`);
      };
      const anchorOf = (): { entity: string; anchor: Json } => {
        const vp = view3d()?.vp;
        const s = vp?.sel;
        if (s && s.bodies.length) return { entity: `entity:${s.bodies[0]}`, anchor: s.faces.length ? { face: s.faces[0].face } : s.edges.length ? { edge: (s.edges[0] as { edge: number }).edge } : {} };
        if (s && s.faces.length) return { entity: `entity:${s.faces[0].body}`, anchor: { face: s.faces[0].face } };
        return { entity: '', anchor: {} };
      };
      const addComment = async (): Promise<void> => {
        const d = vstore.doc();
        if (!d || !vstore.selected) { toast(t('Choose a version first.'), 'info'); return; }
        if (!bodyInput.value.trim()) { toast(t('Type the comment.'), 'info'); return; }
        const a = anchorOf();
        const args: Json = { version: vstore.selected, entity: a.entity || 'doc:', anchor: a.anchor, body: bodyInput.value.trim() };
        if (replyTo !== null) args.parent = replyTo;
        const vp = view3d()?.vp;
        if (withCam.get() && vp) args.camera = vp.getCamera();
        const ov = commentLayer.layer?.overlay;
        if (ov && ov.hasStrokes()) args.markup_svg = ov.svgText();
        const r = await run(() => req('POST', vurl(`/docs/${d.id}/comments`), args), 'Comment added.');
        if (r) { bodyInput.value = ''; replyTo = null; paintReply(); ov?.clear(); toggleMarkup(false); }
      };

      live.append(sDoc.root, sDocs.root, sHist.root, sBr.root, sConf.root, sLife.root, sUsed.root, sCom.root);

      const showComment = async (c: Comment): Promise<void> => {
        const vp = view3d()?.vp;
        commentLayer.layer?.highlight(c.id);
        const h = entityHandle(c.entity);
        if (vp && h !== null && vp.bodyViews.has(h)) vp.setBodySelection([h]);
        if (vp && c.camera) { try { vp.rig.setSpec(c.camera as never, true); } catch { /* an older camera shape */ } }
        if (c.markup) await commentLayer.layer?.overlay.show(vurl(''), c.id);
        else commentLayer.layer?.overlay.clear();
      };

      const paint = (): void => {
        const d = vstore.doc();
        setHidden(note, vstore.ready);
        setText(note, vstore.ready ? '' : (vstore.lastError || t('The vault is not available yet.')));
        setHidden(live, !vstore.ready);
        fillSel(vsel, vstore.vaults.map((v) => [v.id, v.name || v.id] as const));
        setValue(vsel.input as HTMLSelectElement, vstore.vid);
        const b = vstore.binding?.binding ?? null;
        const lk = vstore.binding?.lock ?? d?.lock ?? null;
        setText(q(bindRead.el, 'output'), b ? `${tail(b.path)} · ${vstore.docs.find((x) => x.id === b.doc)?.name ?? b.doc} · ${b.branch}` : t('Not in the vault'));
        setText(q(statusRead.el, 'output'), b ? `${t(b.status)}${b.edit ? ` · ${t('checked out')}` : ''}` : '-');
        setText(q(lockRead.el, 'output'), lk ? `${lk.owner}@${lk.machine} · ${isoTime(lk.since)}` : t('Not locked'));
        fillSel(branchSel, (d?.branches ?? []).map((x) => [x.name, x.name] as const));
        if (b && document.activeElement !== branchSel.input) setValue(branchSel.input as HTMLSelectElement, b.branch);
        setDisabled(undoBtn, !b?.edit);
        setDisabled(unlockBtn, !lk);
        setDisabled(breakBtn, !lk);
        setDisabled(lockBtn, !!lk || !d);
        setDisabled(coBtn, !d);
        setDisabled(roBtn, !d || !vstore.selected);

        setHidden(dempty, vstore.docs.length > 0);
        patchList(dlist, vstore.docs, {
          key: (x) => x.id,
          create: (x) => { const row = el('<div class="u8-row p11-vrow" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="p11-vlock"></span></div>'); row.addEventListener('click', () => void vstore.pickDoc(x.id)); return row; },
          update: (row, x: VDoc) => {
            setText(q(row, '.u8-row-sub'), x.id.replace(/^D-/, '').slice(0, 4));
            setText(q(row, '.u8-row-name'), x.name);
            const bd = q(row, '.u8-badge');
            setText(bd, x.head_revision ? `${x.head_state} ${x.head_revision}` : x.head_state);
            bd.dataset.s = x.head_state === 'released' ? 'fully' : x.head_state === 'obsolete' ? 'conflict' : x.head_state === 'review' ? 'under' : '';
            const lock = q(row, '.p11-vlock');
            const want = x.lock ? 'lock' : x.merging ? 'merge' : '';
            if (lock.dataset.k !== want) { lock.dataset.k = want; lock.innerHTML = want ? icon(want === 'lock' ? 'lock' : 'merge', 12) : ''; }
            const tt = x.lock ? `${x.lock.owner}@${x.lock.machine}` : '';
            if (lock.title !== tt) lock.title = tt;
            setClass(row, 'is-selected', x.id === vstore.docId);
          },
        });

        graph.update();
        const n = vstore.node(vstore.selected);
        setText(q(vRead[0].el, 'output'), n ? `${n.short}${n.revision ? ` · ${t('revision')} ${n.revision}` : ''}` : '-');
        setText(q(vRead[1].el, 'output'), n ? `${n.author} · ${isoTime(n.ts)}` : '-');
        setText(q(vRead[2].el, 'output'), n ? `${bytes(n.size)} · ${n.members} ${t('members')} · ${n.identical ? t('byte-identical') : t('rebuilt')}` : '-');
        for (const r of vRead) { const o = q(r.el, 'output'); if (o.title !== o.textContent) o.title = o.textContent ?? ''; }
        for (const c of [mkBranch, mkTag]) setDisabled(c, !n);
        setDisabled(diffBtn, !n || !vstore.compare);

        const branches = d?.branches ?? [];
        patchList(blist, branches, {
          key: (x) => x.name,
          create: (x) => {
            const row = el('<div class="u8-row p11-brow"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(mini('@close', t('Delete this branch'), () => { const dd = vstore.doc(); if (dd) void run(() => req('DELETE', vurl(`/docs/${dd.id}/branches/${encodeURIComponent(x.name)}`), {}), 'Branch deleted.'); }));
            row.addEventListener('click', () => { selBranch = x.name; void vstore.pickVersion(x.head); });
            return row;
          },
          update: (row, x) => {
            setText(q(row, '.u8-row-sub'), x.head.slice(0, 7));
            setText(q(row, '.u8-row-name'), x.name + (x.name === d?.default_branch ? ` (${t('main line')})` : ''));
            setText(q(row, '.u8-badge'), x.state);
            setClass(row, 'is-selected', selBranch === x.name);
          },
        });
        const names = branches.map((x) => [x.name, x.name] as const);
        fillSel(src, names);
        fillSel(into, names);
        if (d && document.activeElement !== into.input && !into.get()) setValue(into.input as HTMLSelectElement, d.default_branch);
        setDisabled(mergeBtn, !d || !!vstore.merge);

        const m = vstore.merge;
        setHidden(clist, !m);
        setText(cempty, m ? '' : t('No merge in progress. Start one from Branches.'));
        setHidden(cempty, !!m);
        const merged = m?.merged ?? {};
        mState.set(m ? [
          `${m.status} · ${m.branch} ← ${m.theirs.slice(0, 7)}`,
          `${m.conflicts.length} ${t('conflicts')} · ${m.unresolved} ${t('unresolved')}`,
          `${t('auto-merged')}: ${Object.entries(merged).filter(([, v]) => Number(v) > 0).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ') || '-'}`,
        ] : [t('No merge in progress.'), '', ''], false);
        patchList(clist, m?.conflicts ?? [], {
          key: (c) => c.id,
          create: (c) => {
            const row = el('<div class="p11-conf" role="listitem"><div class="p11-conf-head"><span class="u8-badge p11-conf-kind"></span><span class="p11-conf-name"></span></div><div class="p11-conf-vals"></div></div>');
            const vals = q(row, '.p11-conf-vals');
            for (const side of ['base', 'ours', 'theirs'] as const) {
              const b = el<HTMLButtonElement>('<button class="p11-pick" type="button"><span class="p11-pick-k"></span><span class="p11-pick-v"></span></button>');
              b.dataset.side = side;
              setText(q(b, '.p11-pick-k'), t(side));
              b.addEventListener('click', () => choose(c, side));
              vals.append(b);
            }
            return row;
          },
          update: (row, c) => {
            setText(q(row, '.p11-conf-kind'), c.kind.replace(/_/g, ' '));
            const nm = q(row, '.p11-conf-name');
            const label = `${c.name}${c.path ? ` · ${c.path}` : ''}`;
            setText(nm, label);
            if (nm.title !== c.entity) nm.title = c.entity;
            for (const side of ['base', 'ours', 'theirs'] as const) {
              const b = q<HTMLButtonElement>(row, `[data-side="${side}"]`);
              const v = short(c[side]);
              setText(q(b, '.p11-pick-v'), v);
              if (b.title !== v) b.title = v;
              setClass(b, 'is-chosen', c.choice === side);
            }
            setClass(row, 'is-resolved', c.choice !== null && c.choice !== undefined);
          },
        });
        setDisabled(completeBtn, !m || m.unresolved > 0 || m.status === 'conflicts');
        setDisabled(abortBtn, !m);
        setDisabled(allOurs, !m || !m.conflicts.length);
        setDisabled(allTheirs, !m || !m.conflicts.length);

        if (n && document.activeElement !== lState.input) setValue(lState.input as HTMLSelectElement, n.state);
        setDisabled(lApply, !n);
        setDisabled(revise, !d);
        patchList(audit, vstore.audit, {
          key: (a) => `${a.id ?? a.ts}${a.action ?? ''}${a.detail ?? ''}`,
          create: () => el('<div class="u8-row p11-arow"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span></span></div>'),
          update: (row, a) => { setText(q(row, '.u8-row-sub'), String(a.action ?? a.event ?? '')); const nm = q(row, '.u8-row-name'); const tx = describe({ ...a, action: undefined, ts: undefined, id: undefined }); setText(nm, tx); if (nm.title !== tx) nm.title = tx; setText(q(row, '.u8-badge'), typeof a.ts === 'number' ? isoTime(a.ts) : ''); },
        });

        const used = (host: HTMLElement, list: unknown[]): void => patchList(host, list.map((x, i) => ({ x, i })), {
          key: (o) => `u${o.i}${describe(o.x)}`,
          create: () => el('<div class="u8-row p11-urow"><span class="u8-row-name"></span><span></span><span></span><span></span></div>'),
          update: (row, o) => { const nm = q(row, '.u8-row-name'); const tx = describe(o.x); setText(nm, tx); if (nm.title !== tx) nm.title = tx; },
        });
        used(usedList, vstore.whereUsed);
        used(usesList, vstore.uses);

        const a = anchorOf();
        setText(q(anchorRead.el, 'output'), a.entity || t('This document'));
        patchList(comList, vstore.comments.map((c, i) => ({ c, i })), {
          key: (o) => `c${o.c.id}`,
          create: (o) => {
            const row = el('<div class="p11-com" role="listitem"><div class="p11-com-head"><span class="p11-com-n"></span><span class="p11-com-who"></span><span class="u8-badge p11-com-state"></span><span class="u8-acts"></span></div><div class="p11-com-body"></div><div class="p11-com-note"></div></div>');
            q(row, '.u8-acts').append(
              mini('R', t('Reply'), () => { replyTo = o.c.id; paintReply(); bodyInput.focus(); }),
              mini('V', t('Resolve or reopen'), () => { const cur = vstore.comments.find((x) => x.id === o.c.id); void run(() => req('PATCH', vurl(`/comments/${o.c.id}`), { status: cur?.status === 'open' ? 'resolved' : 'open' })); }),
              mini('@close', t('Delete this comment'), () => { void run(() => req('DELETE', vurl(`/comments/${o.c.id}`), {})); }),
            );
            row.addEventListener('click', () => { const cur = vstore.comments.find((x) => x.id === o.c.id); if (cur) void showComment(cur); });
            return row;
          },
          update: (row, o) => {
            const c = o.c;
            setText(q(row, '.p11-com-n'), c.parent === null ? String(o.i + 1) : '↳');
            setText(q(row, '.p11-com-who'), `${c.author} · ${isoTime(c.ts)}`);
            const st = q(row, '.p11-com-state');
            setText(st, c.status);
            st.dataset.s = c.status === 'resolved' ? 'fully' : 'under';
            setText(q(row, '.p11-com-body'), c.body);
            const nt = c.orphan_note || (c.attached ? '' : t('Its object is not in this version.'));
            setText(q(row, '.p11-com-note'), `${c.entity}${nt ? ` · ${nt}` : ''}${c.markup ? ` · ${t('markup')}` : ''}`);
            setClass(row, 'is-reply', c.parent !== null);
            setClass(row, 'is-orphan', !c.attached);
          },
        });
        setHidden(comEmpty, vstore.comments.length > 0);
        commentLayer.layer?.set(vstore.comments);
        paintReply();
      };

      function fillSel(c: Ctl<string>, opts: Array<readonly [string, string]>): void {
        const sel = c.input as HTMLSelectElement;
        const keep = sel.value;
        patchList(sel, opts as Array<readonly [string, string]>, { key: (o) => o[0], create: (o) => { const n = document.createElement('option'); n.value = o[0]; return n; }, update: (n, o) => setText(n, o[1]) });
        if (document.activeElement !== sel) setValue(sel, opts.some((o) => o[0] === keep) ? keep : opts[0]?.[0] ?? '');
      }

      vstore.onChange(paint);
      document.addEventListener('formcad:selection', () => { const a = anchorOf(); setText(q(anchorRead.el, 'output'), a.entity || t('This document')); });
      paint();
      return { show: () => { vstore.active = true; void vstore.refresh(); } };
    },
  };
}
