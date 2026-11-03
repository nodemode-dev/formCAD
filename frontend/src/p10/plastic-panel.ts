import { events } from '../io/events';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setText } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { analysis } from '../u8/register';
import { button, buttons, numberCtl, readout, selectCtl, type Ctl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { docUrl, fixed, jobBar, num, reportBox, req, runCmd, section, text, type Json } from './kit';

interface Finding { id: string; severity: string; kind: string; message: string; feature?: string | null; face?: number | null; value?: number | null; limit?: number | null; at?: number[] | null; at_units?: number[] | null }
interface Field { key: string; label: string; unit: string }

const WALL: Field[] = [
  { key: 'nominal_wall', label: 'Nominal wall', unit: 'mm' }, { key: 'wall_min', label: 'Thinnest wall', unit: 'mm' }, { key: 'wall_max', label: 'Thickest wall', unit: 'mm' },
  { key: 'wall_variation_pct', label: 'Wall variation', unit: '%' }, { key: 'adjacent_ratio_min', label: 'Adjacent wall ratio', unit: '' },
];
const DRAFT: Field[] = [{ key: 'min_draft', label: 'Minimum draft', unit: 'deg' }, { key: 'recommended_draft', label: 'Recommended draft', unit: 'deg' }];
const RIB: Field[] = [
  { key: 'rib_ratio_min', label: 'Rib to wall, least', unit: '' }, { key: 'rib_ratio_max', label: 'Rib to wall, most', unit: '' },
  { key: 'rib_height_max_ratio', label: 'Rib height to thickness', unit: '' }, { key: 'rib_base_fillet_ratio', label: 'Rib base fillet', unit: '' },
];
const BOSS: Field[] = [
  { key: 'boss_od_ratio', label: 'Boss diameter to screw', unit: '' }, { key: 'boss_od_ratio_insert', label: 'Boss diameter, insert', unit: '' },
  { key: 'boss_height_max_ratio', label: 'Boss height to diameter', unit: '' }, { key: 'boss_base_fillet', label: 'Boss base fillet', unit: 'mm' },
];
const SNAP: Field[] = [
  { key: 'snap_strain_allowable', label: 'Snap strain allowed', unit: '%' }, { key: 'snap_repeat_factor', label: 'Repeated assembly factor', unit: '' },
  { key: 'snap_root_radius_min', label: 'Snap root radius', unit: 'mm' }, { key: 'snap_friction', label: 'Friction', unit: '' },
];
const LIP: Field[] = [
  { key: 'lip_width_ratio', label: 'Lip width to wall', unit: '' }, { key: 'lip_height_ratio', label: 'Lip height to wall', unit: '' },
  { key: 'groove_extra_width', label: 'Groove extra width', unit: 'mm' }, { key: 'groove_extra_depth', label: 'Groove extra depth', unit: 'mm' },
  { key: 'lip_clearance', label: 'Lip clearance', unit: 'mm' }, { key: 'lip_draft', label: 'Lip draft', unit: 'deg' },
];
const GROUPS: Array<[string, Field[]]> = [['Walls', WALL], ['Draft', DRAFT], ['Ribs', RIB], ['Bosses', BOSS], ['Snap fits', SNAP], ['Lip and groove', LIP]];
const PULLS: ReadonlyArray<readonly [string, string]> = [['0,0,1', '+Z'], ['0,0,-1', '-Z'], ['1,0,0', '+X'], ['-1,0,0', '-X'], ['0,1,0', '+Y'], ['0,-1,0', '-Y']];
const METHODS: ReadonlyArray<readonly [string, string]> = [['ray', 'Ray (fast, thin walls)'], ['sphere', 'Sphere (thick sections)']];
const FEATURES: Array<[string, string, string]> = [['pl-boss', 'plBoss', 'Boss'], ['pl-rib', 'plRib', 'Rib'], ['pl-snap', 'plSnap', 'Snap hook'], ['pl-lip', 'plLip', 'Lip'], ['pl-groove', 'plGroove', 'Groove']];

const sourceOf = (data: Json | null, key: string, material: string): string => {
  const rules = (data?.rules ?? {}) as Json;
  const mats = Array.isArray(data?.materials) ? (data?.materials as Json[]) : [];
  const own = mats.find((m) => m.id === material)?.[key] as Json | undefined;
  const msrc = (data?.material_sources ?? {}) as Json;
  if (own && typeof own.source === 'string') return `${t('Cited')}: ${typeof msrc[own.source] === 'string' ? String(msrc[own.source]) : own.source}${typeof own.basis === 'string' ? `. ${own.basis}` : ''}`;
  const row = rules[key] as Json | undefined;
  const sources = (data?.rule_sources ?? {}) as Json;
  if (row && typeof row.source === 'string') {
    const cite = typeof sources[row.source] === 'string' ? String(sources[row.source]) : row.source;
    return `${row.kind === 'derived' ? t('Derived') : t('Cited')}: ${cite}${typeof row.basis === 'string' ? `. ${row.basis}` : ''}`;
  }
  return '';
};

export function plasticPanel(): DockPanel {
  return {
    id: 'plastic',
    label: 'Plastic Part',
    icon: 'plastic',
    order: 45,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      let rule: Json = {};
      let data: Json | null = null;
      let busy = false;
      let findings: Finding[] = [];

      const sRule = section('Rule');
      const material = selectCtl('Material', [['', 'Choose...']], () => void setMaterial());
      const cls = readout('Material class');
      const pull = selectCtl('Pull direction', PULLS, () => void writeRule({ pull: pull.get().split(',').map(Number) }));
      sRule.body.append(material.el, cls.el, pull.el);
      const fieldCtl = new Map<string, Ctl<number | null>>();
      for (const [name, fields] of GROUPS) {
        const head = el('<h5 class="xw-sub"></h5>');
        setText(head, t(name));
        sRule.body.appendChild(head);
        for (const f of fields) {
          const c = numberCtl(f.unit ? `${f.label} (${f.unit})` : f.label, 0, () => {
            const v = c.get();
            if (v !== null) void writeRule({ [f.key]: v });
          });
          fieldCtl.set(f.key, c);
          sRule.body.appendChild(c.el);
        }
      }
      const reset = button('Reset to material defaults', () => void resetRule());
      const sourceNote = el('<p class="u8-note xw-sources"></p>');
      setText(sourceNote, t('Hover a value to see where it comes from. Blank means no cited value; you decide.'));
      sRule.body.append(sourceNote, buttons(reset));

      const sFeat = section('Features');
      const featButtons = buttons();
      for (const [cmd, ic, label] of FEATURES) {
        const b = el<HTMLButtonElement>(`<button class="u8-btn xw-fbtn" type="button" data-cmd="${cmd}">${icon(ic, 16)}<span></span></button>`);
        setText(q(b, 'span'), t(label));
        b.addEventListener('click', () => { commands.get(cmd)?.run(); });
        featButtons.appendChild(b);
      }
      sFeat.body.append(featButtons);

      const sCheck = section('Checks');
      const method = selectCtl('Wall method', METHODS);
      const samples = numberCtl('Samples', 4000);
      const bCheck = button('Run checks', () => void runChecks(), 'primary');
      const summary = readout('Summary');
      const wall = reportBox(4);
      const fList = el('<div class="u8-list xw-findings is-scroll" role="list" aria-label="Findings"></div>');
      const fEmpty = el('<p class="u8-note xw-empty"></p>');
      const checkJob = jobBar(['plasticcheck'], (id) => docUrl(id, 'meshes/cancel'));
      sCheck.body.append(method.el, samples.el, buttons(bCheck, button('Clear marks', () => analysis?.clearNaked())), checkJob.el, summary.el, wall.el, fList, fEmpty);

      const sMap = section('Wall thickness map');
      const mMethod = selectCtl('Method', METHODS);
      const lo = numberCtl('Low limit', 0);
      const hi = numberCtl('High limit', 0);
      lo.set(null); hi.set(null);
      const mapNote = el('<p class="u8-note xw-mode"></p>');
      setText(mapNote, t('Blank limits use the wall range of the rule. Colours show on the selected solids, or on all solids when none is selected.'));
      const bMap = button('Show map', () => void showMap(), 'primary');
      const bOff = button('Map off', () => void mapOff());
      const mapJob = jobBar(['plasticwall'], (id) => docUrl(id, 'meshes/cancel'));
      sMap.body.append(mMethod.el, lo.el, hi.el, mapNote, buttons(bMap, bOff), mapJob.el);

      body.append(sRule.root, sFeat.root, sCheck.root, sMap.root);

      const paintRule = (): void => {
        const m = String(rule.material ?? '');
        const list = materialList();
        const sel = material.input as HTMLSelectElement;
        const want = ['', ...list.map((x) => x.id)];
        const have = Array.from(sel.options).map((o) => o.value);
        if (want.join('|') !== have.join('|')) sel.replaceChildren(...want.map((v, i) => { const o = document.createElement('option'); o.value = v; o.textContent = i === 0 ? t('Choose...') : list[i - 1].name; return o; }));
        sel.value = want.includes(m) ? m : '';
        cls.set(String(rule.material_class ?? '-').replace(/_/g, ' '));
        const p = Array.isArray(rule.pull) ? (rule.pull as number[]).join(',') : '0,0,1';
        if (PULLS.some(([v]) => v === p)) pull.set(p);
        for (const [key, c] of fieldCtl) {
          const v = rule[key];
          c.set(typeof v === 'number' ? v : null);
          const tip = sourceOf(data, key, String(rule.material ?? ''));
          if (c.input.title !== tip) c.input.title = tip;
        }
      };

      const materialList = (): Array<{ id: string; name: string }> => {
        const m = data?.materials as unknown;
        if (Array.isArray(m)) return (m as Json[]).map((x) => ({ id: String(x.id ?? x.key ?? x.name), name: String(x.name ?? x.label ?? x.id) }));
        if (m && typeof m === 'object') return Object.entries(m as Json).map(([k, v]) => ({ id: k, name: String((v as Json | undefined)?.name ?? (v as Json | undefined)?.label ?? k) }));
        return [];
      };

      async function writeRule(change: Json): Promise<void> {
        const id = docStore.activeId;
        if (!id) return;
        try { rule = await req<Json>('PUT', docUrl(id, 'plastic/rule'), change); } catch (e) { toast(text(e), 'error'); }
        await loadRule();
      }
      async function setMaterial(): Promise<void> {
        const v = material.get();
        if (v) await writeRule({ material: v });
      }
      async function resetRule(): Promise<void> {
        const id = docStore.activeId;
        if (!id) return;
        try { await req('DELETE', docUrl(id, 'plastic/rule')); } catch (e) { toast(text(e), 'error'); }
        await loadRule();
      }
      async function loadRule(): Promise<void> {
        const id = docStore.activeId;
        if (!id) return;
        try {
          if (!data) data = await req<Json>('GET', docUrl(id, 'plastic/data'));
          const r = await req<Json>('GET', docUrl(id, 'plastic/rule'));
          rule = (r.rule as Json | undefined) ?? r;
        } catch { return; }
        paintRule();
      }

      const mark = (f: Finding): void => {
        const at = f.at_units ?? f.at;
        if (!at || at.length < 3) return;
        const d = 0.8;
        analysis?.setNaked([[[at[0] - d, at[1], at[2]], [at[0] + d, at[1], at[2]]], [[at[0], at[1] - d, at[2]], [at[0], at[1] + d, at[2]]], [[at[0], at[1], at[2] - d], [at[0], at[1], at[2] + d]]]);
        void view3d()?.with3d(() => undefined);
      };

      const paintFindings = (): void => {
        patchList(fList, findings.map((f, i) => ({ ...f, id: `${i}:${f.id}` })), {
          key: (f) => f.id,
          create: (f) => {
            const row = el('<div class="u8-row xw-find" role="listitem"><span class="u8-badge"></span><span class="u8-row-name"></span><span class="u8-row-sub"></span></div>');
            row.addEventListener('click', () => { const i = Number(row.dataset.i ?? -1); if (findings[i]) mark(findings[i]); });
            return row;
          },
          update: (node, f) => {
            node.dataset.i = f.id.split(':')[0];
            const b = q(node, '.u8-badge');
            setText(b, t(f.severity));
            b.dataset.s = f.severity === 'error' ? 'missing' : f.severity === 'warning' ? 'outofdate' : 'loaded';
            setText(q(node, '.u8-row-name'), f.message);
            q(node, '.u8-row-name').title = f.message;
            setText(q(node, '.u8-row-sub'), f.value !== null && f.value !== undefined ? `${fixed(f.value, 3)}${f.limit !== null && f.limit !== undefined ? ` / ${fixed(f.limit, 3)}` : ''}` : '');
          },
        });
        setText(fEmpty, findings.length ? '' : t('No findings. Run the checks to fill this list.'));
      };

      async function runChecks(): Promise<void> {
        const id = docStore.activeId;
        if (!id || busy) return;
        busy = true;
        setDisabled(bCheck, true);
        wall.set([`${t('Checking')}...`]);
        try {
          const r = await req<Json>('POST', docUrl(id, 'plastic/checks'), { pull: pull.get().split(',').map(Number), samples: Math.max(100, Math.round(samples.get() ?? 4000)), method: method.get() });
          const s = (r.summary ?? {}) as Json;
          summary.set(`${num(s.errors)} ${t('errors')} · ${num(s.warnings)} ${t('warnings')} · ${num(s.info)} ${t('info')}`);
          const w = (r.wall ?? {}) as Json;
          wall.set([
            `${t('Method')} ${String(w.method ?? '-')} · ${num(w.samples)} ${t('samples')} · ${num(w.misses)} ${t('misses')}`,
            `${t('Thickness')} ${fixed(num(w.min), 3)} ${t('to')} ${fixed(num(w.max), 3)} · ${t('nominal')} ${fixed(num(w.nominal), 3)}`,
            `${t('Below the least wall')} ${fixed(num(w.below_min_area_pct), 3)} % · ${t('above the greatest')} ${fixed(num(w.above_max_area_pct), 3)} %`,
            `${t('Variation')} ${fixed(num(w.variation_pct), 3)} %`,
          ]);
          findings = (Array.isArray(r.findings) ? r.findings : []) as Finding[];
          paintFindings();
        } catch (e) { wall.set([text(e)], true); } finally { busy = false; setDisabled(bCheck, false); }
      }

      async function showMap(): Promise<void> {
        const vp = view3d()?.vp;
        const args: Json = { method: mMethod.get(), targets: vp ? [...vp.sel.bodies] : [] };
        const l = lo.get(); const h = hi.get();
        if (l !== null) args.low = l;
        if (h !== null) args.high = h;
        const r = await runCmd('wallthickness', args);
        if (r) { await view3d()?.with3d(() => undefined); await analysis?.refresh(); }
      }
      async function mapOff(): Promise<void> {
        if (await runCmd('analysisoff', {})) await analysis?.refresh();
      }

      let timer = 0;
      const later = (): void => { window.clearTimeout(timer); timer = window.setTimeout(() => { void loadRule(); }, 150); };
      events.on('doc', (e) => { if (e.id === docStore.activeId) later(); });
      docStore.onChange(later);
      paintFindings();
      setClass(fEmpty, 'is-quiet', true);
      later();
      return { show: later };
    },
  };
}
