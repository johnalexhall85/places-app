import { useEffect, useState } from "react";
import { API_BASE } from "../../config/apiBase";

export function useCharts(level, geoid, ready) {
  const [charts, setCharts] = useState(null);
  useEffect(() => {
    setCharts(null);
    if (!ready) return;
    const controller = new AbortController();
    fetch(`${API_BASE}/community/${level}/${geoid}/charts`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() : null)
      .then(setCharts)
      .catch(() => {});
    return () => controller.abort();
  }, [level, geoid, ready]);
  return charts;
}
