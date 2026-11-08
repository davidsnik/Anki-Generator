import { describe, expect, it } from 'vitest';
import { sourceHighlight } from './geometry';
describe('original source coordinate highlighting', () => {
  it('maps source points onto a resized tile without using raster pixel dimensions', () => {
    expect(sourceHighlight([120, 250, 300, 350], [100, 200, 500, 600])).toEqual({
      left: '5%',
      top: '12.5%',
      width: '45%',
      height: '25%',
    });
  });
  it('clips a source crossing an overlapping tall-page tile', () => {
    expect(sourceHighlight([10, 900, 90, 1100], [0, 1000, 100, 1500])).toEqual({
      left: '10%',
      top: '0%',
      width: '80%',
      height: '20%',
    });
  });
  it('highlights an entire explicitly selected region', () => {
    expect(sourceHighlight([0, 100, 200, 500], [0, 100, 200, 500])).toEqual({
      left: '0%',
      top: '0%',
      width: '100%',
      height: '100%',
    });
  });
  it('does not fabricate a highlight outside the tile or for invalid bounds', () => {
    expect(sourceHighlight([0, 0, 10, 10], [20, 20, 30, 30])).toBeNull();
    expect(sourceHighlight([0, 0, 0, 1], [0, 0, 1, 1])).toBeNull();
    expect(sourceHighlight([0, 0, NaN, 1], [0, 0, 1, 1])).toBeNull();
    expect(sourceHighlight(undefined, [0, 0, 1, 1])).toBeNull();
  });
});
