import { boolRow, choiceRow, colorRow, numberRow, readRow, textRow, type Commit, type PropRow } from './prop-rows';
import type { RowDef } from './props-kinds';

const lineweightName = (v: string): string => (/^[\d.]+$/.test(v) ? `${v} mm` : v);

export function buildRow(def: RowDef, commit: Commit, digits: () => number): PropRow {
  switch (def.type) {
    case 'number': return numberRow(def.label, commit, digits);
    case 'text': return textRow(def.label, commit);
    case 'choice': return choiceRow(def.label, commit);
    case 'lineweight': return choiceRow(def.label, commit, { label: lineweightName });
    case 'bool': return boolRow(def.label, commit);
    case 'color': return colorRow(def.label, commit);
    default: return readRow(def.label, digits);
  }
}
