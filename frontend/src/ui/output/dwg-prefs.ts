import { el, setHidden, setText } from '../dom';
import { setDwgRoute } from '../file-dialogs';
import { t } from '../i18n';
import { toggleRow } from '../panels/controls';
import { buttonRow, infoRow, textRow } from '../panels/pref-rows';
import { toast } from '../toast';
import { failure, out, type DwgStatus } from './output-api';

export function dwgRows(register: (sync: () => void) => void): HTMLElement[] {
  const apply = (s: DwgStatus): void => {
    enabled.set(s.enabled);
    path.set(s.converterPath);
    status.set(s.message);
    using.set(s.usable ? `${s.converterKind} · ${s.converter}` : t('None'));
    found.set([s.detected.oda && 'ODA', s.detected.libredwgRead && 'LibreDWG'].filter(Boolean).join(', ') || t('Nothing found'));
    const k = s.tools;
    setDwgRoute(!s.usable ? 'none' : s.writeVersions.length === 1 && s.writeVersions[0] === 'R2000' ? 'r2000' : 'oda');
    for (const node of [tools.el, toolsAct.el, toolsNote]) setHidden(node, !k.published && !k.installed);
    tools.set(k.installing ? `${k.message} ${Math.round(k.progress * 100)} %` : k.installed ? `LibreDWG ${k.release ?? ''} · ${t('reads every DWG version, saves DWG 2000 only')}` : k.message || t('Not installed'));
    setText(toolsAct.button, k.installed ? t('Remove') : k.installing ? t('Installing') : t('Install'));
    toolsAct.button.disabled = k.installing;
    if (k.installing) window.setTimeout(() => { out.dwg().then(apply).catch(() => undefined); }, 1000);
  };
  const tools = infoRow('DWG tools');
  const toolsAct = buttonRow('DWG tools', 'Install', () => {
    const removing = toolsAct.button.textContent === t('Remove');
    (removing ? out.removeDwgTools() : out.installDwgTools()).then(apply).catch((e) => toast(failure(e), 'error'));
  }, 'ghost');
  const toolsNote = el('<p class="cv-note"></p>');
  setText(toolsNote, t('The DWG tools are GNU LibreDWG, a separate program under the GPL, downloaded from FormCAD\'s release page and checked file by file. With them FormCAD opens every DWG version and saves DWG in the 2000 format only.'));
  for (const node of [tools.el, toolsAct.el, toolsNote]) setHidden(node, true);
  const send = (body: { enabled?: boolean; converter?: string }): void => {
    out.setDwg(body).then(apply).catch((e) => toast(failure(e), 'error'));
  };
  const enabled = toggleRow('Open and save DWG files', (v) => send({ enabled: v }));
  const path = textRow('Converter program', (v) => send({ converter: v }), 'Found automatically');
  const status = infoRow('Status');
  const using = infoRow('Converter in use');
  const found = infoRow('Found on this computer');
  const recheck = buttonRow('Converter', 'Check Again', () => { out.dwg().then(apply).catch((e) => toast(failure(e), 'error')); }, 'ghost');
  const note = el('<p class="cv-note"></p>');
  setText(note, t('DWG is read and written through a converter program you install yourself. It stays off until you turn it on, and nothing is bundled with FormCAD.'));
  out.dwg().then(apply).catch(() => undefined);
  register(() => { out.dwg().then(apply).catch(() => undefined); });
  return [enabled.el, path.el, status.el, using.el, found.el, recheck.el, note, tools.el, toolsAct.el, toolsNote];
}
