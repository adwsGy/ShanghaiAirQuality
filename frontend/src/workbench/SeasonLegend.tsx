import type { Result } from './model.ts';
import { seasonColors, seasonMaximum } from './seasonScale.ts';
import './seasonLegend.css';

export function SeasonLegend({ result }: { result: Result }) {
  const statistic = result.context.statistic;
  const maximum = seasonMaximum[statistic];
  const aboveMaximum = result.data.cells?.some(cell => cell.n > 0 && (cell[statistic] ?? 0) > maximum);
  const name = statistic === 'mean' ? '月均浓度' : '月度P90';
  return <div className="wb-season-legend" role="group" aria-label={`${name}色阶，0至${maximum}微克每立方米，颜色越深浓度越高`}>
    <div className="wb-season-legend-title">{name}（μg/m³）</div>
    <div className="wb-season-gradient" aria-hidden="true" style={{ background: `linear-gradient(to right, ${seasonColors.join(', ')})` }} />
    <div className="wb-season-ticks" aria-hidden="true">{Array.from({ length: 6 }, (_, i) => <span key={i}>{i === 5 && aboveMaximum ? '≥' : ''}{maximum * i / 5}</span>)}</div>
    {aboveMaximum && <p>高于{maximum} μg/m³使用最深色，悬停查看实际浓度。</p>}
  </div>;
}
