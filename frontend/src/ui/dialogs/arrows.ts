export const ARROW_NAMES: ReadonlyArray<readonly [string, string]> = [
  ['closed filled', 'Closed filled'], ['closed blank', 'Closed blank'], ['closed', 'Closed'], ['dot', 'Dot'], ['small dot', 'Dot small'],
  ['blank dot', 'Dot blank'], ['oblique', 'Oblique'], ['architectural tick', 'Architectural tick'], ['open', 'Open'], ['right-angle', 'Right angle'],
  ['30-degree open', 'Open 30'], ['origin indicator', 'Origin indicator'], ['origin indicator 2', 'Origin indicator 2'], ['small', 'Small'],
  ['filled box', 'Box filled'], ['blank box', 'Box blank'], ['filled datum triangle', 'Datum triangle filled'], ['blank datum triangle', 'Datum triangle blank'],
  ['integral', 'Integral'], ['none', 'None'],
];

const BLOCKS: Record<string, string> = {
  'closed filled': '_CLOSEDFILLED', 'closed blank': '_CLOSEDBLANK', closed: '_CLOSED', dot: '_DOT', 'small dot': '_DOTSMALL', 'blank dot': '_DOTBLANK',
  oblique: '_OBLIQUE', 'architectural tick': '_ARCHTICK', open: '_OPEN', 'right-angle': '_OPEN90', '30-degree open': '_OPEN30',
  'origin indicator': '_ORIGIN', 'origin indicator 2': '_ORIGIN2', small: '_SMALL', 'filled box': '_BOXFILLED', 'blank box': '_BOXBLANK',
  'filled datum triangle': '_DATUMFILLED', 'blank datum triangle': '_DATUMBLANK', integral: '_INTEGRAL', none: '_NONE',
};

export const blockOf = (name: string): string => BLOCKS[name] ?? '';

export function nameOfBlock(block: string): string {
  const key = block.trim().toUpperCase();
  for (const [name, b] of Object.entries(BLOCKS)) if (b === key) return name;
  return 'closed filled';
}
