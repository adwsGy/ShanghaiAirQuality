import type { Statistic } from './model.ts';

// One scale per statistic keeps equal concentrations comparable across filters and sites.
export const seasonMaximum: Record<Statistic, number> = { mean: 100, p90: 200 };
export const seasonColors = ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'];
export const seasonMissingColor = '#d8dddf';

export function seasonLabelColor(concentration: number | null, maximum: number) {
  const position = Math.max(0, Math.min(1, (concentration ?? 0) / maximum)) * (seasonColors.length - 1);
  const index = Math.min(Math.floor(position), seasonColors.length - 2);
  const fraction = position - index;
  const rgb = [1, 3, 5].map(offset => {
    const low = parseInt(seasonColors[index].slice(offset, offset + 2), 16);
    const high = parseInt(seasonColors[index + 1].slice(offset, offset + 2), 16);
    const channel = Math.round(low + (high - low) * fraction) / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  });
  const luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  return luminance > .179 ? '#000000' : '#ffffff';
}
