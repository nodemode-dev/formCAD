import { el, setText } from '../dom';
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
  };
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
  register(() => { out.dwg().then(apply).catch(() => undefined); });
  return [enabled.el, path.el, status.el, using.el, found.el, recheck.el, note];
}
