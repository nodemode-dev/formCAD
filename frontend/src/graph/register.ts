import { onShellMounted } from '../app';
import { registerInterceptor } from '../ui/dialogs/intercept';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { graphEditor } from './editor';

const hasDoc = (): boolean => !!docStore.activeId;

registerInterceptor(['graph'], () => {
  if (!hasDoc()) return false;
  void graphEditor.show();
  return true;
});

onShellMounted((ctx) => {
  graphEditor.mount(ctx.hosts.stage);
  if (!commands.get('gr-open')) {
    commands.add({
      id: 'gr-open',
      label: 'Graph Editor',
      icon: 'graph',
      group: 'Window',
      enabled: hasDoc,
      checked: () => graphEditor.isOpen(),
      run: () => { if (graphEditor.isOpen()) graphEditor.hide(); else void graphEditor.show(); },
    });
  }
});
