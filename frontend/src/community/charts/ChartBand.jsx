import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../../config/apiBase";
import { COLORS, extent, focusedExtent, formatTick, formatValue, interval, peerSubset, position, ticks } from "./scale";
import "./charts.css";

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const update = () => setWidth(Math.max(240, ref.current.clientWidth || 600));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function Marker({ type, x, y, size = 6 }) {
  if (type === "state") return <path data-marker="state" d={`M ${x} ${y - size} L ${x + size} ${y} L ${x} ${y + size} L ${x - size} ${y} Z`} fill={COLORS.state} stroke="#584022" />;
  if (type === "national") return <rect data-marker="national" x={x - size} y={y - size} width={size * 2} height={size * 2} fill={COLORS.national} />;
  return <circle data-marker="area" cx={x} cy={y} r={size} fill={COLORS.area} />;
}

function Grid({ domain, width, row, bottom = 68 }) {
  return <g className="chart-grid">{ticks(domain).map((value) => {
    const x = position(value, domain, 30, width - 30);
    return <g key={value}><line x1={x} x2={x} y1="8" y2={bottom} stroke="#d7e0e4" />
      <text className="chart-axis-label" x={x} y={bottom + 17} textAnchor="middle">{formatTick(value, row)}</text></g>;
  })}</g>;
}

export function ChartTable({ rows, row, trend = false }) {
  const [open, setOpen] = useState(false);
  const label = open ? "Hide table" : "Show as table";
  if (trend) return <div className="chart-table-wrap"><button className="chart-text-button" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{label}</button>
    {open && <div className="chart-table-scroll"><table className="chart-table"><thead><tr><th>Period</th><th>Value</th><th>Interval</th><th>Boundary</th><th>Release</th><th>Note or status</th></tr></thead><tbody>
      {row.trend.series.map((item) => <tr key={item.period}><th scope="row">{item.period}</th><td>{formatValue(item.value, { ...row, status_text: item.status_text })}</td><td>{intervalText(item, row)}</td><td>{item.boundary_vintage || "—"}</td><td>{item.release_label || "—"}</td><td>{item.note || item.status_text || ""}</td></tr>)}
      {row.trend.unavailable_periods.map((item) => <tr key={`unavailable-${item.period}`}><th scope="row">{item.period}</th><td>No published value</td><td>—</td><td>—</td><td>—</td><td>{item.reason}</td></tr>)}
    </tbody></table></div>}</div>;
  return <div className="chart-table-wrap"><button className="chart-text-button" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{label}</button>
    {open && <div className="chart-table-scroll"><table className="chart-table"><thead><tr><th>Measure</th><th>Area value</th><th>Interval</th><th>State value</th><th>U.S. value</th><th>Period</th></tr></thead><tbody>
      {rows.map((item) => <tr key={`${item.product}:${item.measure_id}`}><th scope="row">{item.label}</th><td>{formatValue(item.value, item)}</td><td>{intervalText(item, item)}</td><td>{item.comparisons.state ? formatValue(item.comparisons.state.value, item) : "—"}</td><td>{item.comparisons.national ? formatValue(item.comparisons.national.value, item) : "—"}</td><td>{item.period}</td></tr>)}
    </tbody></table></div>}</div>;
}

function intervalText(item, row) {
  const [low, high] = item.low != null && item.high != null ? [item.low, item.high] : interval(item);
  return low == null ? "—" : `${formatValue(low, row)}–${formatValue(high, row)}`;
}

function axisValues(row) {
  return [row.value, ...interval(row), ...["state", "national"].flatMap((key) => {
    const marker = row.comparisons?.[key];
    return marker ? [marker.value, ...interval(marker)] : [];
  }), ...(row.peers?.values || [])];
}

export function DotIntervalRow({ row, domain, areaName = "This area" }) {
  const [ref, width] = useWidth();
  const scale = domain || extent(axisValues(row), row);
  const px = (value) => position(value, scale, 30, width - 30);
  const [low, high] = interval(row);
  const peers = !!row.peers;
  return <div ref={ref} className="chart-svg-wrap"><svg role="img" aria-label={`${row.label}: ${formatValue(row.value, row)}${row.peers ? `; ${row.peers.count} peers on the same scale` : ""}`} viewBox={`0 0 ${width} ${peers ? 91 : 68}`} width="100%">
    <Grid domain={scale} width={width} row={row} bottom={peers ? 68 : 45} />
    {row.value != null && <><line x1={px(low)} x2={px(high)} y1="24" y2="24" stroke={COLORS.area} strokeWidth="4" /><Marker type="area" x={px(row.value)} y={24} />
      <text className="chart-value-label" x={Math.min(width - 30, px(row.value) + 9)} y="19" textAnchor={px(row.value) > width - 90 ? "end" : "start"}>{formatValue(row.value, row)}</text></>}
    {peers && <PeerStrip row={row} domain={scale} width={width} />}
    {row.comparisons?.state && <Marker type="state" x={px(row.comparisons.state.value)} y={42} size={4} />}
    {row.comparisons?.national && <Marker type="national" x={px(row.comparisons.national.value)} y={42} size={4} />}
  </svg>{row.value == null && <p className="chart-missing">{row.status_text || "No published value"}</p>}
    {(row.comparisons?.state || row.comparisons?.national) && <p className="chart-comparisons">{row.comparisons.state && <span><i className="state-shape" />{row.comparisons.state.name || "State"} {formatValue(row.comparisons.state.value, row)}</span>}{row.comparisons.national && <span><i className="national-shape" />United States {formatValue(row.comparisons.national.value, row)}</span>}</p>}
    {peers && <PeerCaption row={row} areaName={areaName} />}</div>;
}

export function PeerStrip({ row, domain, width }) {
  const peers = row.peers;
  if (!peers) return null;
  const px = (value) => position(value, domain, 30, width - 30);
  return <g data-testid="peer-strip">{peers.values.map((value, index) => <line key={index} x1={px(value)} x2={px(value)} y1="38" y2="54" stroke="#91a2aa" strokeWidth="1" />)}
    {row.value != null && <Marker type="area" x={px(row.value)} y={46} size={5} />}</g>;
}

function PeerCaption({ row, areaName }) {
  const peers = row.peers;
  const peerName = (item) => peers.level === "county" ? `${item.name || item.geoid} County` : (item.name || item.geoid);
  return <p className="chart-peer-caption">{peers.parent_geoid ? `${areaName.split(",").at(-1).trim()} counties` : "States and DC"} ({peers.count}): lowest {formatValue(peers.min.value, row)} {peerName(peers.min)}, highest {formatValue(peers.max.value, row)} {peerName(peers.max)}</p>;
}

function overlaps(a, b) {
  const [aLow, aHigh] = interval(a);
  const [bLow, bHigh] = interval(b);
  return aLow != null && bLow != null && aLow <= bHigh && bLow <= aHigh;
}

export function PeerList({ row, areaGeoid, areaName, controlledOpen }) {
  const [localOpen, setLocalOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [ref, width] = useWidth();
  const open = controlledOpen ?? localOpen;
  useEffect(() => { setData(null); setError(false); setAll(false); }, [row.peers?.peers_url, areaGeoid]);
  useEffect(() => {
    if (!open || !row.peers || data || error) return;
    let active = true;
    fetch(`${API_BASE}${row.peers.peers_url}`)
      .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
      .then((result) => { if (active) setData(result); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [open, row.peers, data, error]);
  if (!row.peers) return null;
  const subset = data ? peerSubset(data.values, areaGeoid) : null;
  const published = data?.values.filter((item) => item.value != null) || [];
  const shown = all ? [...published].sort((a, b) => b.value - a.value || a.geoid.localeCompare(b.geoid)) : subset?.selected;
  const area = published.find((item) => item.geoid === areaGeoid);
  const scale = focusedExtent(published.flatMap((item) => [item.value, ...interval(item)]), row);
  const left = Math.round(width * (width < 640 ? 0.38 : 0.31));
  const right = width - 73;
  const px = (value) => position(value, scale, left, right);
  const clipName = (name) => { const limit = Math.max(7, Math.floor((left - 12) / 7)); return name.length > limit ? `${name.slice(0, limit - 1)}…` : name; };
  const rowHeight = 30;
  return <div ref={ref} className="chart-peer-list">{controlledOpen === undefined && <button className="chart-text-button" type="button" aria-expanded={open} onClick={() => setLocalOpen(!open)}>{row.peers.level === "county" ? "Compare counties" : "Compare states"}</button>}
    {open && <div className="chart-peer-panel">
      <p className="chart-peer-legend"><span><i className="area-shape" />Interval overlaps this area's</span><span><i className="other-shape" />Other areas</span><span><i className="band-shape" />This area's 95% CI</span></p>
      <p>Overlapping intervals are a display aid, not a test of statistical difference.</p>
      {error && <p>Peer list unavailable.</p>}{!data && !error && <p>Loading comparisons…</p>}
      {shown && <><svg className="chart-peer-chart" role="img" aria-label={`${areaName} and ${shown.length - 1} areas, values and 95% intervals`} viewBox={`0 0 ${width} ${Math.max(1, shown.length) * rowHeight}`} width="100%">
        {area && <rect x={px(interval(area)[0])} y="0" width={Math.max(0, px(interval(area)[1]) - px(interval(area)[0]))} height={shown.length * rowHeight} fill="#e7f2f8" />}
        {shown.map((item, index) => {
          const y = index * rowHeight + 16;
          const name = `${item.name || item.geoid}${item.geoid === areaGeoid ? " (this area)" : ""}${!all && subset.fringe?.has(item.geoid) ? item.geoid === published.reduce((a, b) => a.value < b.value ? a : b).geoid ? " (lowest)" : " (highest)" : ""}`;
          const color = overlaps(item, area) ? COLORS.area : "#78909C";
          const [low, high] = interval(item);
          return <g key={item.geoid} data-peer-row={item.geoid} aria-label={`${name}: ${formatValue(item.value, row)}; interval ${intervalText(item, row)}`}>
            {!all && subset.fringe?.has(item.geoid) && <line x1="0" x2={width} y1={index * rowHeight} y2={index * rowHeight} stroke="#78909c" strokeDasharray="4 4" />}
            <text className={item.geoid === areaGeoid ? "chart-peer-area-name" : ""} x="2" y={y + 4}>{clipName(name)}</text>
            <line x1={px(low)} x2={px(high)} y1={y} y2={y} stroke={color} strokeWidth="3" />
            <circle cx={px(item.value)} cy={y} r="5" fill={color} />
            <text className={item.geoid === areaGeoid ? "chart-peer-area-name" : ""} x={width - 2} y={y + 4} textAnchor="end">{formatValue(item.value, row)}</text>
          </g>;
        })}</svg>
        <details className="chart-peer-table"><summary>Peer values as table</summary><div className="chart-table-scroll"><table className="chart-table"><thead><tr><th>Area</th><th>Value</th><th>Interval</th></tr></thead><tbody>{shown.map((item) => <tr key={item.geoid}><th scope="row">{item.name || item.geoid}</th><td>{formatValue(item.value, row)}</td><td>{intervalText(item, row)}</td></tr>)}</tbody></table></div></details>
        {!!subset.remaining.length && <button className="chart-text-button" type="button" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show nearby" : `Show all ${published.length}`}</button>}</>}
    </div>}</div>;
}

export function TrendChart({ row }) {
  const [ref, width] = useWidth();
  const trend = row.trend;
  if (!trend) return null;
  const available = trend.series;
  const periods = [...new Set([...available.map((point) => point.period), ...trend.unavailable_periods.map((item) => item.period)])].sort();
  const state = new Map((trend.state_series || []).map((point) => [point.period, point]));
  const national = new Map((trend.national_series || []).map((point) => [point.period, point]));
  const values = [...available, ...state.values(), ...national.values()].flatMap((point) => [point.value, point.low, point.high]);
  const domain = extent(values, row);
  const yTicks = ticks(domain, 3);
  const x = (period) => position(periods.indexOf(period), [0, Math.max(1, periods.length - 1)], 62, width - 30);
  const y = (value) => position(value, domain, 120, 22);
  const linePath = (points) => points.reduce((path, point, index) => {
    if (point.value == null) return path;
    const previous = points[index - 1];
    const connected = previous?.value != null && periods.indexOf(point.period) === periods.indexOf(previous.period) + 1;
    return `${path}${connected ? " L" : " M"}${x(point.period)} ${y(point.value)}`;
  }, "");
  const drawSeries = (points, type) => <g key={type}>
    {trend.style === "line_band" && points.slice(1).map((point, index) => {
      const previous = points[index];
      if (previous.value == null || point.value == null || previous.low == null || point.low == null || previous.high == null || point.high == null || periods.indexOf(point.period) !== periods.indexOf(previous.period) + 1) return null;
      return <path key={`${previous.period}-${point.period}`} d={`M${x(previous.period)} ${y(previous.low)} L${x(point.period)} ${y(point.low)} L${x(point.period)} ${y(point.high)} L${x(previous.period)} ${y(previous.high)} Z`} fill={COLORS[type]} opacity="0.13" />;
    })}
    {trend.style !== "dots_ci" && trend.style !== "dots" && linePath(points) && <path className="chart-trend-line" d={linePath(points)} fill="none" stroke={COLORS[type]} strokeWidth="2" />}
    {points.filter((point) => point.value != null).map((point) => <g key={point.period}>
      {(trend.style === "line_band" || trend.style === "dots_ci") && point.low != null && point.high != null && <line x1={x(point.period)} x2={x(point.period)} y1={y(point.low)} y2={y(point.high)} stroke={COLORS[type]} strokeWidth="3" />}
      <Marker type={type} x={x(point.period)} y={y(point.value)} size={4} /></g>)}
  </g>;
  const published = available.filter((point) => point.value != null);
  const first = published[0]?.period;
  const last = published.at(-1)?.period;
  return <div ref={ref} className="chart-trend"><p className="chart-trend-legend"><span><i className="area-shape" />This area</span>{trend.state_series && <span><i className="state-shape" />State</span>}{trend.national_series && <span><i className="national-shape" />United States</span>}</p><svg role="img" aria-label={`${row.label} over time: ${available.map((point) => `${point.period} ${formatValue(point.value, row)}`).join("; ")}`} viewBox={`0 0 ${width} 171`} width="100%">
    {yTicks.map((tick) => <g key={tick}><line x1="62" x2={width - 30} y1={y(tick)} y2={y(tick)} stroke="#d7e0e4" /><text className="chart-axis-label" x="56" y={y(tick) + 4} textAnchor="end">{formatTick(tick, row)}</text></g>)}
    {drawSeries(available, "area")}{drawSeries([...state.values()], "state")}{drawSeries([...national.values()], "national")}
    {published.map((point) => {
      const endpoint = point.period === first || point.period === last;
      if (!endpoint && trend.style !== "dots_ci") return null;
      return <text key={point.period} className={!endpoint ? "chart-trend-extra-label" : "chart-trend-value-label"} x={x(point.period)} y={Math.max(13, y(point.value) - 10)} textAnchor={point.period === first ? "start" : point.period === last ? "end" : "middle"}>{formatValue(point.value, row)}</text>;
    })}
    {periods.map((period) => <text key={period} x={x(period)} y="157" textAnchor="middle">{period.split(/[-–]/).at(-1)}</text>)}
  </svg>{trend.note && <p>{trend.note}</p>}
    <details className="chart-year-details"><summary>About these years</summary><ul>{available.map((point) => <li key={point.period}>{point.period}: {point.release_label || "Release not specified"}; boundary {point.boundary_vintage || "not specified"}{point.note ? `; ${point.note}` : ""}</li>)}</ul></details>
    <ChartTable row={row} trend /></div>;
}

export function Sparkline({ row }) {
  const [ref, width] = useWidth();
  const series = row.trend?.series || [];
  const points = series.filter((point) => point.value != null);
  if (points.length < 2) return <span className="chart-missing">{row.status_text || "No comparison available"}</span>;
  const values = points.map((point) => point.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = Math.max((high - low) * 0.15, Math.abs(high) * 0.01, 0.01);
  const domain = [low - pad, high + pad];
  const line = series.map((point, index) => {
    if (point.value == null) return "";
    const prior = series[index - 1];
    const connected = prior?.value != null;
    return `${connected ? "L" : "M"}${10 + index * (width - 20) / Math.max(1, series.length - 1)} ${38 - position(point.value, domain, 6, 28)}`;
  }).join(" ");
  return <div ref={ref} className="chart-svg-wrap"><svg role="img" aria-label={`${row.label} over time; ${points.length} published periods; latest ${formatValue(points.at(-1).value, row)}`} viewBox={`0 0 ${width} 66`} width="100%" className="chart-sparkline"><path d={line} fill="none" stroke={COLORS.area} strokeWidth="2" /><text x="10" y="60">{points[0].period.split(/[-–]/).at(-1)}</text><text x={width - 10} y="60" textAnchor="end">{points.at(-1).period.split(/[-–]/).at(-1)}</text></svg><span className="chart-sparkline-value">{formatValue(points.at(-1).value, row)}</span></div>;
}

function ChartRow({ row, domain, areaGeoid, areaName }) {
  const [open, setOpen] = useState(false);
  const [peerOpen, setPeerOpen] = useState(false);
  const trendOnly = row.kind === "count" || ["people", "beneficiaries", "physicians", "dentists", "hospitals", "beds", "days"].includes(row.unit) || (!row.peers && !row.comparisons.state && !row.comparisons.national);
  return <div className="chart-row"><div className="chart-row-label"><strong>{row.label}</strong><span>{row.period} · {row.population}</span></div>
    <div className="chart-row-content">{trendOnly ? <Sparkline row={row} /> : <DotIntervalRow row={row} domain={domain} areaName={areaName} />}
      {row.value == null && trendOnly && <p className="chart-missing">{row.status_text}</p>}
      <div className="chart-row-actions">{row.trend && <button className="chart-text-button" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Over time</button>}{row.trend && row.peers && <span aria-hidden="true">·</span>}{row.peers && <button className="chart-text-button" type="button" aria-expanded={peerOpen} onClick={() => setPeerOpen(!peerOpen)}>{row.peers.level === "county" ? "Compare counties" : "Compare states"}</button>}</div>
      {row.peers && <PeerList row={row} areaGeoid={areaGeoid} areaName={areaName} controlledOpen={peerOpen} />}
      {row.comparisons.side_note && <p className="chart-side-note">{row.comparisons.side_note.label}: {formatValue(row.comparisons.side_note.value, row)}. {row.comparisons.side_note.text}</p>}
      {open && <TrendChart row={row} />}
    </div></div>;
}

export function ChartBand({ section, areaGeoid, areaName, stateName }) {
  const sources = [...new Map(section.groups.flatMap((group) => group.rows).map((row) => [`${row.source.publisher}:${row.source.product_name}:${row.citation}`, row])).values()];
  return <div className="chart-band"><div className="chart-band-head"><h3>At a glance</h3><div className="chart-band-legend" aria-label="Chart symbols"><span><i className="area-shape" />{areaName}</span><span><i className="state-shape" />{stateName}</span><span><i className="national-shape" />United States</span></div></div>
    {section.groups.map((group) => {
      const domain = group.shared_axis ? extent(group.rows.flatMap(axisValues), group.rows[0]) : null;
      return <div className="chart-group" key={group.key}><h4>{group.title}</h4>{group.rows.map((row) => <ChartRow key={`${row.product}:${row.measure_id}`} row={row} domain={domain} areaGeoid={areaGeoid} areaName={areaName} />)}<ChartTable rows={group.rows} /></div>;
    })}
    <p className="chart-sources">Sources: {sources.map((row) => `${row.source.publisher} · ${row.source.product_name}${row.source.credit ? ` · ${row.source.credit}` : ""}${row.citation ? ` · ${row.citation}` : ""}`).join("; ")}</p>
  </div>;
}
