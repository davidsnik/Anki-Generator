export interface Highlight {
  left: string;
  top: string;
  width: string;
  height: string;
}
/** Clip a source rectangle to a rendered tile using the shared original-page coordinates. */
export function sourceHighlight(source?: number[], tile?: number[]): Highlight | null {
  if (
    !source ||
    !tile ||
    source.length !== 4 ||
    tile.length !== 4 ||
    ![...source, ...tile].every(Number.isFinite)
  )
    return null;
  const [sx0, sy0, sx1, sy1] = source;
  const [tx0, ty0, tx1, ty1] = tile;
  if (sx1 <= sx0 || sy1 <= sy0 || tx1 <= tx0 || ty1 <= ty0) return null;
  const x0 = Math.max(sx0, tx0),
    y0 = Math.max(sy0, ty0),
    x1 = Math.min(sx1, tx1),
    y1 = Math.min(sy1, ty1);
  if (x1 <= x0 || y1 <= y0) return null;
  return {
    left: `${((x0 - tx0) / (tx1 - tx0)) * 100}%`,
    top: `${((y0 - ty0) / (ty1 - ty0)) * 100}%`,
    width: `${((x1 - x0) / (tx1 - tx0)) * 100}%`,
    height: `${((y1 - y0) / (ty1 - ty0)) * 100}%`,
  };
}
