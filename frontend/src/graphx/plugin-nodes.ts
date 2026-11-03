import { el, patchList, q, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { pluginNodeTypes, type PluginNodeType } from './net';

export function pluginNodeRows(register: (sync: () => void) => void): HTMLElement[] {
  const list = el('<div class="ap-list gp-pnodes" role="list"></div>');
  const empty = el('<p class="cv-note"></p>');
  setText(empty, t('No plugin has added graph nodes.'));
  const pull = async (): Promise<void> => {
    let rows: PluginNodeType[] = [];
    try { rows = await pluginNodeTypes(); } catch { rows = []; }
    patchList(list, rows, {
      key: (r) => r.id,
      create: () => el('<div class="ap-item" role="listitem"><div class="ap-head"><b class="ap-name"></b><span class="ap-state"></span></div><p class="ap-desc"></p></div>'),
      update: (node, r) => {
        setText(q(node, '.ap-name'), r.name);
        setText(q(node, '.ap-state'), r.plugin);
        setText(q(node, '.ap-desc'), r.description ? `${r.category}: ${r.description}` : r.category);
      },
    });
    setHidden(empty, rows.length > 0);
  };
  register(() => { void pull(); });
  return [list, empty];
}
