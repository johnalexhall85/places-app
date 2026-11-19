import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../../config/apiBase";
import { COLORS, extent, formatValue, interval, peerSubset, position } from "./scale";
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

function Grid({ domain, width, bottom = 76 }) {
  return <g className="chart-grid">{[0, 0.5, 1].map((fraction) => {
    const x = 24 + fraction * (width - 48);
    return <line key={fraction} x1={x} x2={x} y1="8" y2={bottom} stroke="#d7e0e4" />;
  })}</g>;
}

export function ChartTable({ row, trend = false }) {
  const [open, setOpen] = useState(false);
  const records = trend ? (row.trend?.series || []).map((item) => ({ label: item.period, ...item }))
    : [{ label: "Area", value: row.value, status_text: row.status_text },
      ...["state", "national"].filter((key) => row.comparisons?.[key]).map((key) => ({ label: key === "national" ? "United States" : "State", ...row.comparisons[key] }))];
  return <div className="chart-table-wrap"><button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Show as table</button>
    {open && <table className="chart-table"><thead><tr><th scope="col">Area or period</th><th scope="col">Published value</th><th scope="col">Status or note</th></tr></thead>
      <tbody>{records.map((item, index) => <tr key={`${item.label}-${index}`}><th scope="row">{item.label}</th><td>{formatValue(item.value, row)}</td><td>{item.note || item.status_text || ""}</td></tr>)}
      {trend && row.trend?.unavailable_periods?.map((item) => <tr key={`unavailable-${item.period}`}><th scope="row">{item.period}</th><td>No published value</td><td>{item.reason}</td></tr>)}</tbody></table>}</div>;
}

export function DotIntervalRow({ row, domain }) {
  const [ref, width] = useWidth();
  const all = [row.value, ...interval(row), ...["state", "national"].flatMap((key) => {
    const marker = row.comparisons?.[key];
    return marker ? [marker.value, ...interval(marker)] : [];
  })];
  const scale = domain || extent(all);
  const px = (value) => position(value, scale, 24, width - 24);
  const [low, high] = interval(row);
  return <div ref={ref} className="chart-svg-wrap"><svg role="img" aria-label={`${row.label}: ${formatValue(row.value, row)}; state ${formatValue(row.comparisons?.state?.value, row)}; United States ${formatValue(row.comparisons?.national?.value, row)}`} viewBox={`0 0 ${width} 96`} width="100%">
    <Grid domain={scale} width={width} />
    {row.value != null && <><line x1={px(low)} x2={px(high)} y1="27" y2="27" stroke={COLORS.area} strokeWidth="4" /><Marker type="area" x={px(row.value)} y={27} /></>}
    {row.comparisons?.state && <Marker type="state" x={px(row.comparisons.state.value)} y={50} />}
    {row.comparisons?.national && <Marker type="national" x={px(row.comparisons.national.value)} y={70} />}
    <text x="24" y="91">{formatValue(scale[0], row)}</text><text x={width - 24} y="91" textAnchor="end">{formatValue(scale[1], row)}</text>
  </svg>{row.value == null && <p className="chart-missing">{row.status_text || "No published value"}</p>}</div>;
}

export function PeerStrip({ row, areaName }) {
  const peers = row.peers;
  const [ref, width] = useWidth();
  if (!peers) return null;
  const domain = extent([...peers.values, row.value]);
  const px = (value) => position(value, domain, 24, width - 24);
  const peerName = (item) => peers.level === "county" ? `${item.name || item.geoid} County` : (item.name || item.geoid);
  return <div ref={ref} className="chart-peer-strip"><svg role="img" aria-label={`${peers.count} peer values; ${areaName}: ${formatValue(row.value, row)}`} viewBox={`0 0 ${width} 38`} width="100%">
    {peers.values.map((value, index) => <line key={index} x1={px(value)} x2={px(value)} y1="7" y2="27" stroke="#91a2aa" strokeWidth="1" />)}
    {row.value != null && <Marker type="area" x={px(row.value)} y={17} size={6} />}
  </svg><p>{peers.parent_geoid ? `${areaName.split(",").at(-1).trim()} counties` : "States and DC"} ({peers.count}): lowest {formatValue(peers.min.value, row)} {peerName(peers.min)}, highest {formatValue(peers.max.value, row)} {peerName(peers.max)}</p></div>;
}

function overlaps(a, b) {
  const [aLow, aHigh] = interval(a);
  const [bLow, bHigh] = interval(b);
  return aLow != null && bLow != null && aLow <= bHigh && bLow <= aHigh;
}

export function PeerList({ row, areaGeoid, areaName }) {
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const load = () => {
    setOpen(!open);
    if (!open && !data) fetch(`${API_BASE}${row.peers.peers_url}`)
      .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
      .then(setData).catch(() => setError(true));
  };
  if (!row.peers) return null;
  const subset = data ? peerSubset(data.values, areaGeoid) : null;
  const shown = all ? [...(subset?.selected || []), ...(subset?.remaining || [])].sort((a, b) => b.value - a.value || a.geoid.localeCompare(b.geoid)) : subset?.selected;
  return <div className="chart-peer-list"><button type="button" aria-expanded={open} onClick={load}>{row.peers.level === "county" ? "Compare counties" : "Compare states"}</button>
    {open && <div><p className="chart-peer-legend">Interval overlaps {areaName}'s · Other {row.peers.level === "county" ? "counties" : "states"} · {areaName}'s 95% CI</p>
      <p>Overlapping intervals are a display aid, not a test of statistical difference.</p>
      {error && <p>Peer list unavailable.</p>}{!data && !error && <p>Loading comparisons…</p>}
      {shown && <><ul>{shown.map((item) => <li key={item.geoid} className={`${overlaps(item, data.values.find((entry) => entry.geoid === areaGeoid)) ? "overlaps" : ""} ${!all && subset.fringe?.has(item.geoid) ? "is-extreme" : ""}`}>
        <span>{item.name || item.geoid}{item.geoid === areaGeoid ? " (this area)" : ""}</span><strong>{formatValue(item.value, row)}</strong></li>)}</ul>
        {!!subset.remaining.length && <button type="button" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show nearby" : `Show all ${data.values.filter((item) => item.value != null).length}`}</button>}</>}
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
  const domain = extent(values);
  const x = (period) => position(periods.indexOf(period), [0, Math.max(1, periods.length - 1)], 30, width - 30);
  const y = (value) => 120 - position(value, domain, 12, 108);
  const linePath = (points) => points.reduce((path, point, index) => {
    if (point.value == null) return path;
    const previous = points[index - 1];
    const connected = previous?.value != null && previous.boundary_vintage === point.boundary_vintage
      && periods.indexOf(point.period) === periods.indexOf(previous.period) + 1;
    return `${path}${connected ? " L" : " M"}${x(point.period)} ${y(point.value)}`;
  }, "");
  const drawSeries = (points, type) => <g key={type}>
    {trend.style === "line_band" && points.slice(1).map((point, index) => {
      const previous = points[index];
      if (previous.value == null || point.value == null || previous.low == null || point.low == null || previous.high == null || point.high == null || previous.boundary_vintage !== point.boundary_vintage || periods.indexOf(point.period) !== periods.indexOf(previous.period) + 1) return null;
      return <path key={`${previous.period}-${point.period}`} d={`M${x(previous.period)} ${y(previous.low)} L${x(point.period)} ${y(point.low)} L${x(point.period)} ${y(point.high)} L${x(previous.period)} ${y(previous.high)} Z`} fill={COLORS[type]} opacity="0.13" />;
    })}
    {trend.style !== "dots_ci" && trend.style !== "dots" && linePath(points) && <path className="chart-trend-line" d={linePath(points)} fill="none" stroke={COLORS[type]} strokeWidth="2" />}
    {points.filter((point) => point.value != null).map((point) => <g key={point.period}>
      {(trend.style === "line_band" || trend.style === "dots_ci") && point.low != null && point.high != null && <line x1={x(point.period)} x2={x(point.period)} y1={y(point.low)} y2={y(point.high)} stroke={COLORS[type]} strokeWidth="3" />}
      <Marker type={type} x={x(point.period)} y={y(point.value)} size={4} /></g>)}
  </g>;
  return <div ref={ref} className="chart-trend"><svg role="img" aria-label={`${row.label} over time: ${available.map((point) => `${point.period} ${formatValue(point.value, row)}`).join("; ")}`} viewBox={`0 0 ${width} 165`} width="100%">
    {[0, 0.5, 1].map((fraction) => <line key={fraction} x1="24" x2={width - 24} y1={20 + fraction * 100} y2={20 + fraction * 100} stroke="#d7e0e4" />)}
    {drawSeries(available, "area")}{drawSeries([...state.values()], "state")}{drawSeries([...national.values()], "national")}
    {periods.map((period) => <text key={period} x={x(period)} y="152" textAnchor="middle">{period.includes("-") ? period.split("-").at(-1) : period}</text>)}
  </svg>{trend.note && <p>{trend.note}</p>}
    {trend.style === "dots_ci" && <p>{available.map((point) => `${point.period}: ${point.release_label || "source release"}`).join("; ")}</p>}
    {[...new Set(available.filter((point, index) => index && point.boundary_vintage !== available[index - 1].boundary_vintage).map((point) => `${point.period}: ${point.note || "Boundary changed; line breaks here."}`))].map((note) => <p key={note}>{note}</p>)}
    <ChartTable row={row} trend /></div>;
}

export function Sparkline({ row }) {
  const [ref, width] = useWidth();
  const series = row.trend?.series || [];
  const points = series.filter((point) => point.value != null);
  if (points.length < 2) return <span className="chart-missing">{row.status_text || "No comparison available"}</span>;
  const domain = extent(points.map((point) => point.value));
  const line = series.map((point, index) => {
    if (point.value == null) return "";
    const prior = series[index - 1];
    const connected = prior?.value != null && prior.boundary_vintage === point.boundary_vintage;
    return `${connected ? "L" : "M"}${10 + index * (width - 20) / Math.max(1, series.length - 1)} ${40 - position(point.value, domain, 5, 30)}`;
  }).join(" ");
  return <div ref={ref} className="chart-svg-wrap"><svg role="img" aria-label={`${row.label} over time; ${points.length} published periods`} viewBox={`0 0 ${width} 46`} width="100%" className="chart-sparkline"><path d={line} fill="none" stroke={COLORS.area} strokeWidth="2" /></svg></div>;
}

function ChartRow({ row, domain, areaGeoid, areaName }) {
  const [open, setOpen] = useState(false);
  const trendOnly = row.kind === "count" || ["people", "beneficiaries", "physicians", "dentists", "hospitals", "beds", "days"].includes(row.unit) || (!row.peers && !row.comparisons.state && !row.comparisons.national);
  return <div className="chart-row"><div className="chart-row-label"><strong>{row.label}</strong><span>{row.period} · {row.population}</span></div>
    <div className="chart-row-content">{trendOnly ? <Sparkline row={row} /> : <DotIntervalRow row={row} domain={domain} />}
      {row.value == null && trendOnly && <p className="chart-missing">{row.status_text}</p>}
      <PeerStrip row={row} areaName={areaName} /><PeerList row={row} areaGeoid={areaGeoid} areaName={areaName} />
      {row.comparisons.side_note && <p className="chart-side-note">{row.comparisons.side_note.label}: {formatValue(row.comparisons.side_note.value, row)}. {row.comparisons.side_note.text}</p>}
      <ChartTable row={row} />
      {row.trend && <><button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Over time</button>{open && <TrendChart row={row} />}</>}
    </div></div>;
}

export function ChartBand({ section, areaGeoid, areaName, stateName }) {
  const sources = [...new Map(section.groups.flatMap((group) => group.rows).map((row) => [`${row.source.publisher}:${row.source.product_name}:${row.citation}`, row])).values()];
  return <div className="chart-band"><div className="chart-band-head"><h3>At a glance</h3><div className="chart-band-legend" aria-label="Chart symbols"><span><i className="area-shape" />{areaName}</span><span><i className="state-shape" />{stateName}</span><span><i className="national-shape" />United States</span></div></div>
    {section.groups.map((group) => {
      const domain = group.shared_axis ? extent(group.rows.flatMap((row) => [row.value, ...interval(row), ...[row.comparisons.state, row.comparisons.national].flatMap((point) => point ? [point.value, ...interval(point)] : [])])) : null;
      return <div className="chart-group" key={group.key}><h4>{group.title}</h4>{group.rows.map((row) => <ChartRow key={`${row.product}:${row.measure_id}`} row={row} domain={domain} areaGeoid={areaGeoid} areaName={areaName} />)}</div>;
    })}
    <p className="chart-sources">Sources: {sources.map((row) => `${row.source.publisher} · ${row.source.product_name}${row.source.credit ? ` · ${row.source.credit}` : ""}${row.citation ? ` · ${row.citation}` : ""}`).join("; ")}</p>
  </div>;
}
