import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { deleteNamedView, failure, listNamedViews, saveNamedView, type NamedView3d } from './named-views';
import type { CameraSpec } from './types';

export interface ViewHooks {
  current: () => CameraSpec;
  restore: (c: CameraSpec) => void;
}

const row = (key: string): HTMLElement => {
  const n = el<HTMLElement>('<button class="cv-list-row u3-row" type="button" role="option"><span></span><span class="u3-row-name"></span><span class="cv-list-meta"></span></button>');
  n.dataset.key = key;
  return n;
};

export class NamedViews3dDialog extends Dialog {
  private views: NamedView3d[] = [];
  private selected = '';
  private openedFor = '';
  private readonly list: HTMLElement;
  private readonly name: HTMLInputElement;
  private readonly detail: HTMLElement;
  private readonly bRestore: HTMLButtonElement;
  private readonly bSave: HTMLButtonElement;
  private readonly bDelete: HTMLButtonElement;

  constructor(private readonly hooks: ViewHooks) {
    super('3D Views', 520);
    this.body.appendChild(el(
      '<div class="u3-vm"><div class="u3-vm-left"><div class="cv-list u3-list" role="listbox"></div></div>' +
      '<div class="u3-vm-right"><div class="u3-detail"></div>' +
      '<input class="cv-input u3-name" type="text" spellcheck="false" autocomplete="off">' +
      '<div class="u3-btns"></div></div></div>'));
    this.list = q(this.body, '.u3-list');
    this.name = q<HTMLInputElement>(this.body, '.u3-name');
    this.detail = q(this.body, '.u3-detail');
    this.name.placeholder = t('View name');
    const btns = q(this.body, '.u3-btns');
    const mk = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      btns.appendChild(b);
      return b;
    };
    this.bRestore = mk('Set Current', () => this.restore(this.selected));
    this.bSave = mk('Save Current View', () => void this.save());
    this.bDelete = mk('Delete', () => void this.remove());
    this.button('Close', 'primary', () => this.close());
    this.name.addEventListener('input', () => this.gate());
    this.name.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !this.bSave.disabled) { e.preventDefault(); void this.save(); } });
    this.list.addEventListener('click', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (key) { this.selected = key; this.paint(); }
    });
    this.list.addEventListener('dblclick', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (key) this.restore(key);
    });
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.openedFor) this.close(); });
  }

  async show(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.openedFor = id;
    await this.reload();
    this.open(this.name);
  }

  private async reload(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      this.views = await listNamedViews(id);
      if (!this.views.some((v) => v.name === this.selected)) this.selected = this.views[0]?.name ?? '';
      this.paint();
    } catch (e) {
      toast(failure(e), 'error');
    }
  }

  private restore(name: string): void {
    const v = this.views.find((x) => x.name === name);
    if (!v) return;
    this.hooks.restore(v.camera);
    this.close();
  }

  private async save(): Promise<void> {
    const id = docStore.activeId;
    const name = this.name.value.trim();
    if (!id || !name) return;
    try {
      await saveNamedView(id, name, this.hooks.current());
      this.selected = name;
      this.name.value = '';
      await this.reload();
    } catch (e) {
      toast(failure(e), 'error');
    }
  }

  private async remove(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.selected) return;
    try {
      await deleteNamedView(id, this.selected);
      await this.reload();
    } catch (e) {
      toast(failure(e), 'error');
    }
  }

  private gate(): void {
    setDisabled(this.bSave, !this.name.value.trim());
    setDisabled(this.bRestore, !this.selected);
    setDisabled(this.bDelete, !this.selected);
  }

  private paint(): void {
    patchList(this.list, this.views, {
      key: (v) => v.name,
      create: (v) => row(v.name),
      update: (n, v) => {
        const cells = n.querySelectorAll('span');
        setText(cells[1], v.name);
        setText(cells[2], v.camera.projection === 'parallel' ? t('Parallel') : t('Perspective'));
        setClass(n, 'is-selected', v.name === this.selected);
        n.setAttribute('aria-selected', String(v.name === this.selected));
      },
    });
    setText(this.detail, this.views.length ? t('Pick a saved view to set it as the current view.') : t('No named 3D views.'));
    this.gate();
  }
}
