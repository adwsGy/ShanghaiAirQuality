import { useEffect, useRef } from 'react';
import { useReducedMotion } from 'motion/react';
import * as echarts from 'echarts/core';
import { LineChart, HeatmapChart, ScatterChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, BrushComponent, MarkAreaComponent, ToolboxComponent, GeoComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';
echarts.use([LineChart, HeatmapChart, ScatterChart, BarChart, GeoComponent, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, BrushComponent, MarkAreaComponent, ToolboxComponent, CanvasRenderer]);
type Events = Record<string, (event: any, chart: echarts.ECharts) => void>;
export function EChart({ option, label, height = 280, events = {}, brushing = false, animated = false, animationKey }: { option: EChartsOption; label: string; height?: number; events?: Events; brushing?: boolean; animated?: boolean; animationKey?: string }) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.ECharts | null>(null);
  const callbacks = useRef(events); callbacks.current = events;
  const previousData = useRef<string | undefined>(undefined);
  const painted = useRef(false);
  const reducedMotion = useReducedMotion();
  const latest = useRef({ option, animated, animationKey, reducedMotion });
  latest.current = { option, animated, animationKey, reducedMotion };
  const paint = useRef<(() => void) | null>(null);
  useEffect(() => {
    const host = element.current!;
    let chart: echarts.ECharts | null = null;
    let renderedOption: EChartsOption | null = null;
    const names = ['click', 'datazoom', 'brushEnd', 'georoam'];
    function bind(current: echarts.ECharts) {
    names.forEach(name => current.on(name, (event: unknown) => callbacks.current[name]?.(event, current)));
    // A category can also be selected through its plot column, without hitting a tiny symbol.
    current.getZr().on('click', event => {
      if (!event.target && current.containPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY])) {
        const category = current.convertFromPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY]) as number[];
        callbacks.current.plotclick?.({ dataIndex: Math.round(category[0]) }, current);
      }
    });
    }
    function draw(resizeOnly = false) {
      // Hidden or temporarily collapsed layouts have no invertible geo transform.
      // Wait for a measurable host before initializing or resizing any chart.
      if (host.clientWidth <= 0 || host.clientHeight <= 0) return;
      const created = !chart;
      if (!chart) { chart = echarts.init(host); instance.current = chart; bind(chart); }
      chart.resize();
      const config = latest.current;
      if (resizeOnly && !created && renderedOption === config.option) return;
      const animate = config.animated && !config.reducedMotion && (!painted.current || previousData.current !== config.animationKey);
      chart.setOption({ ...config.option, animation: animate, animationDuration: 360, animationDurationUpdate: 300,
        animationEasing: 'cubicOut', animationEasingUpdate: 'cubicOut' }, { notMerge: true });
      renderedOption = config.option; previousData.current = config.animationKey; painted.current = true;
    }
    paint.current = () => draw();
    const observer = new ResizeObserver(() => draw(true)); observer.observe(host);
    return () => { observer.disconnect(); paint.current = null; if (chart) { names.forEach(name => chart!.off(name)); chart.dispose(); } instance.current = null; };
  }, []);
  useEffect(() => {
    paint.current?.();
  }, [option, animated, animationKey, reducedMotion]);
  useEffect(() => { instance.current?.dispatchAction({ type: 'takeGlobalCursor', key: 'brush', brushOption: { brushType: brushing ? 'lineX' : false } }); }, [brushing, option]);
  return <div ref={element} className="chart" role="img" aria-label={label} style={{ height }} />;
}
