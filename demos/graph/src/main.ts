import './boot';
import '../../../frontend/src/main';
import { commands } from '../../../frontend/src/ui/commands';
import { docStore } from '../../../frontend/src/ui/doc-store';
import { graphEditor } from '../../../frontend/src/graph/editor';

const started = Date.now();
let readyAt = 0;
let revealed = false;

const reveal = (): void => {
  if (revealed) return;
  revealed = true;
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add('demo-ready')));
};

const painted = (): boolean => !!document.querySelector('.is-graph .gx-node') && !!graphEditor.record();

const settle = (): void => {
  if (revealed) return;
  if (painted() || Date.now() - readyAt > 4000) { reveal(); return; }
  window.setTimeout(settle, 50);
};

const openGraph = (): void => {
  const ready = document.body.classList.contains('app-ready') && !!docStore.activeId;
  if (ready) {
    readyAt = readyAt || Date.now();
    if (graphEditor.isOpen() || commands.run('gr-open')) { settle(); return; }
  }
  if (Date.now() - started > 30000) { reveal(); return; }
  window.setTimeout(openGraph, 50);
};

window.setTimeout(reveal, 30000);
openGraph();
