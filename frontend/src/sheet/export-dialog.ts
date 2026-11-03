import { messageOf } from '../part/store';
import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { pickPath, type FileKind } from '../ui/file-dialogs';
import { toast } from '../ui/toast';
import { sheet } from './api';
import { checkRow, choiceRow, heading } from './ui';

const DXF: FileKind = { name: 'DXF drawing', extensions: ['dxf'] };
const VERSIONS: Array<[string, string]> = [['R2018', 'R2018'], ['R2013', 'R2013'], ['R2010', 'R2010'], ['R2007', 'R2007'], ['R2004', 'R2004'], ['R2000', 'R2000']];

export class FlatExportDialog extends Dialog {
  private readonly profile = choiceRow('Profile', [['bending', 'Bending: outline, cutouts and bend lines'], ['cutting', 'Cutting: outline and cutouts on one layer']], () => this.paint());
  private readonly version = choiceRow('DXF version', VERSIONS, () => undefined);
  private readonly notes = checkRow('Write a note beside each bend', () => undefined);
  private readonly about: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly go: HTMLButtonElement;

  constructor() {
    super('Export Flat Pattern', 480);
    const form = el('<div class="sm-form"></div>');
    this.about = el('<p class="sm-note"></p>');
    this.msg = el('<p class="sm-msg" role="status"></p>');
    form.append(heading('Flat pattern file'), this.profile.root, this.version.root, this.notes.root, this.about, this.msg);
    this.body.appendChild(form);
    this.button('Close', 'ghost', () => this.close());
    this.go = this.button('Export...', 'primary', () => { void this.run(); });
    this.paint();
  }

  private paint(): void {
    const bending = this.profile.get() === 'bending';
    this.notes.use(bending);
    setText(this.about, bending
      ? t('Layers OUTER, INNER, BEND_UP and BEND_DOWN. Bend lines are dashed. Units are millimetres.')
      : t('One layer, CUT, with the outline and every cutout. No bend lines. Units are millimetres.'));
  }

  showFor(): void {
    setText(this.msg, '');
    this.paint();
    this.open();
  }

  private async run(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const cur = docStore.current();
    const stem = (cur?.name ?? 'part').replace(/\.[^.]*$/, '') || 'part';
    const suggested = `${stem}-flat${this.profile.get() === 'cutting' ? '-cut' : ''}.dxf`;
    const path = await pickPath('save', 'Export Flat Pattern', suggested, [DXF], 'Export');
    if (!path) return;
    setDisabled(this.go, true);
    setText(this.msg, t('Writing...'));
    try {
      const r = await sheet.exportFlat(id, { path, profile: this.profile.get() as 'bending' | 'cutting', version: this.version.get(), notes: this.notes.get() });
      setText(this.msg, `${t('Wrote')} ${r.path}. ${t('Layers')}: ${r.layers.join(', ')}. ${r.outer_loops} ${t('outline')}, ${r.inner_loops} ${t('cutouts')}, ${r.bend_lines} ${t('bend lines')}.`);
      toast(t('The flat pattern was exported.'));
    } catch (e) {
      setText(this.msg, messageOf(e));
    } finally {
      setDisabled(this.go, false);
    }
  }
}
