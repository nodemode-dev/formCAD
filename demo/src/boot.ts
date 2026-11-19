import recording from '../recordings/drafting.json';
import { installReplay, type Recording } from './shim/replay';

const rec = recording as unknown as Recording;
const handle = installReplay(rec);

Object.assign(window, { formcadReplay: { document: rec.document, misses: handle.misses } });
