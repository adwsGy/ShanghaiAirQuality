import { useEffect, useState } from 'react';
import { registerMap } from 'echarts/core';
import type { Metadata } from './types.ts';
const registered = new Map<string, string>();
export function useGeometry(metadata: Metadata) {
  const { asset_path: path, sha256: hash } = metadata.geometry;
  const key = `${path}:${hash}`;
  const [result, setResult] = useState<{ key: string; name?: string; error?: string }>({ key: '' });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true; const controller = new AbortController();
    if (registered.has(key)) { setResult({ key, name: registered.get(key)! }); return; }
    setResult({ key });
    (async () => {
      const response = await fetch(path, { signal: controller.signal });
      if (!response.ok) throw new Error('本地边界素材暂不可用，列表与配对图仍可使用。');
      const bytes = await response.arrayBuffer();
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
      if (digest !== hash) throw new Error('地图素材校验值不一致，请重建前端后再试。');
      const json = JSON.parse(new TextDecoder().decode(bytes));
      if (json.type !== 'FeatureCollection' || json.features.length !== 16) throw new Error('边界素材结构不符合本研究版本。');
      if (!active) return;
      const name = `shanghai-${hash}`; registerMap(name, json); registered.set(key, name); setResult({ key, name });
    })().catch(error => { if (active && !controller.signal.aborted) setResult({ key, error: (error as Error).message }); });
    return () => { active = false; controller.abort(); };
  }, [key, path, hash, retry]);
  return { name: result.key === key ? result.name : undefined, error: result.key === key ? result.error : undefined, retry: () => setRetry(v => v + 1) };
}
