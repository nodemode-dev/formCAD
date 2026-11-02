import { Dialog } from '../dialogs';
import { el, q, setText } from '../dom';
import { t } from '../i18n';

export interface FileKind { name: string; extensions: string[] }

const extOf = (p: string): string => { const m = /\.([A-Za-z0-9]+)$/.exec(p.trim()); return m ? m[1].toLowerCase() : ''; };
const withExt = (p: string, ext: string): string => {
  const cur = extOf(p);
  const base = cur ? p.trim().slice(0, -(cur.length + 1)) : p.trim();
  return base ? `${base}.${ext}` : '';
};

export class PathDialog extends Dialog {
  private readonly input: HTMLInputElement;
  private readonly kind: HTMLSelectElement;
  private readonly note: HTMLElement;
  private readonly ok: HTMLButtonElement;
  private kinds: FileKind[] = [];
  private save = false;
  private resolve: ((v: string | null) => void) | null = null;

  constructor() {
    super('Choose a File', 560);
    this.body.appendChild(el(
      '<label class="cv-field"><span>File path</span><input class="cv-input" type="text" spellcheck="false" autocomplete="off" aria-label="File path"></label>'));
    this.body.appendChild(el('<label class="cv-field"><span>File type</span><select class="cv-input" aria-label="File type"></select></label>'));
    this.body.appendChild(el('<p class="cv-note op-pathnote"></p>'));
    this.input = q<HTMLInputElement>(this.body, 'input');
    this.kind = q<HTMLSelectElement>(this.body, 'select');
    this.note = q(this.body, '.op-pathnote');
    this.button('Cancel', 'ghost', () => this.finish(null));
    this.ok = this.button('OK', 'primary', () => this.commit());
    this.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.commit(); } });
    this.kind.addEventListener('change', () => {
      const k = this.kinds[this.kind.selectedIndex];
      if (this.save && k && this.input.value.trim()) this.input.value = withExt(this.input.value, k.extensions[0]);
    });
    this.onClose = () => this.finish(null);
  }

  ask(title: string, suggested: string, kinds: FileKind[], save: boolean, okLabel: string): Promise<string | null> {
    this.setTitle(title);
    this.kinds = kinds;
    this.save = save;
    while (this.kind.firstChild) this.kind.removeChild(this.kind.firstChild);
    for (const k of kinds) {
      const o = document.createElement('option');
      o.textContent = `${t(k.name)} (${k.extensions.map((x) => `*.${x}`).join(', ')})`;
      this.kind.appendChild(o);
    }
    const ext = extOf(suggested);
    const at = kinds.findIndex((k) => k.extensions.includes(ext));
    this.kind.selectedIndex = at >= 0 ? at : 0;
    this.input.value = suggested;
    setText(this.ok, t(okLabel));
    setText(this.note, save ? t('The file type follows the extension of the name.') : t('Type the full path of the file.'));
    this.open(this.input);
    this.input.select();
    return new Promise((r) => { this.resolve = r; });
  }

  private commit(): void {
    let p = this.input.value.trim();
    if (!p) return;
    const k = this.kinds[this.kind.selectedIndex];
    if (this.save && k && !extOf(p)) p = withExt(p, k.extensions[0]);
    this.finish(p);
  }

  private finish(v: string | null): void {
    const r = this.resolve;
    this.resolve = null;
    if (this.isOpen) this.close();
    r?.(v);
  }
}
