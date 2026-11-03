import { dv } from '../draw/api';
import { palette } from '../draw/state';
import { drawStore } from '../draw/store';
import type { Tool, ToolHost } from '../draw/tool-host';
import { createdView } from '../draw/tools-view';
import { partStore } from '../part/store';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';

export function flatViewTool(h: ToolHost): Tool {
  return {
    id: 'flat',
    title: 'Flat pattern view',
    hint: () => `${t('Click the sheet where the flat pattern goes. Scale')} ${palette.scale}. ${t('Bend lines carry a note with direction, angle and radius. Hold Shift to place more.')}`,
    move: (p) => h.env.overlay.setGhost({ cross: p }),
    click: async (p, e) => {
      if (!partStore.tree?.body) await partStore.load();
      const body = partStore.tree?.body ?? 0;
      if (!body) { toast(t('This drawing has no sheet metal part to flatten.'), 'error'); return; }
      const info = await createdView({
        type: 'base',
        layout: drawStore.layout,
        scale: palette.scale,
        position: p,
        flat: true,
        label: t('Flat pattern'),
        source: { component: String(body) },
      });
      if (info && !(info as { flat?: boolean }).flat) await drawStore.run((id) => dv.patch(id, info.handle, { changes: { flat: true } }));
      if (info && !e.shiftKey) h.disarm();
    },
  };
}
