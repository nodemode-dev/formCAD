import { api } from '../../io/api';
import { commands } from '../../ui/commands';
import { docStore } from '../../ui/doc-store';
import { anyDialogOpen } from '../../ui/dialogs';
import { stored } from '../../ui/dom';
import { loadPrefs } from '../../ui/prefs';
import { sysvars } from '../../ui/sysvar-store';
import { toast } from '../../ui/toast';
import type { CanvasApi, Pt } from '../types';
import { Interaction } from './controller';
import type { SysApi } from './settings';

const sys: SysApi = {
  num: (name, fallback) => sysvars.num(name, fallback),
  text: (name, fallback = '') => sysvars.text(name, fallback),
  vec: (name, fallback) => {
    const v = sysvars.get(name);
    return Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number' ? ([v[0], v[1]] as Pt) : fallback;
  },
};

function recall(): string[] {
  try {
    const v: unknown = JSON.parse(stored('formCAD.cmdRecall') ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export function attachInteraction(canvas: CanvasApi, host: HTMLElement): Interaction {
  return new Interaction(canvas, host, {
    docId: () => docStore.activeId,
    onDoc: (fn) => {
      let last = docStore.activeId;
      return docStore.onChange(() => {
        if (docStore.activeId === last) return;
        last = docStore.activeId;
        fn();
      });
    },
    sys,
    onSys: (fn) => sysvars.onChange(fn),
    timeRightClick: () => loadPrefs().timeRightClick,
    toast: (text) => toast(text, 'error'),
    runUi: (id) => { commands.run(id); },
    commandNames: async () => {
      const { commands: list } = await api.commands();
      return list.flatMap((c) => [c.name, ...c.aliases]);
    },
    cmdInput: () => document.querySelector<HTMLInputElement>('.cv-cmd-input'),
    typing: (t) => t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)),
    dialogOpen: () => anyDialogOpen(),
    recall,
  });
}
