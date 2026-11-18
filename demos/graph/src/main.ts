import './boot';
import '../../../frontend/src/main';
import { commands } from '../../../frontend/src/ui/commands';
import { docStore } from '../../../frontend/src/ui/doc-store';
import { graphEditor } from '../../../frontend/src/graph/editor';

const started = Date.now();
const openGraph = (): void => {
  if (graphEditor.isOpen()) return;
  const ready = document.body.classList.contains('app-ready') && !!docStore.activeId;
  if (ready && commands.run('gr-open')) return;
  if (Date.now() - started < 30000) window.setTimeout(openGraph, 100);
};
openGraph();
