import { useEffect, useRef, useState } from "react";
import {
  COLORS,
  DASH_ARRAYS,
  DOT_RADIUS,
  computeYAxis,
  formatCardValue,
  formatShortTick,
  hasBarChart,
  hasTrendChart,
  isPercentRow,
  position,
  sectionChartInfo,
  shortPeriod,
  toDisplayValue,
  visibleXIndices,
} from "./scale";
import "./charts.css";

const LINE_CHART_HEIGHT = 120;
const NOTE_MAX_LENGTH = 140;

function useWidth(fallback = 280) {
  const ref = useRef(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      const measured = element.clientWidth || element.getBoundingClientRect?.().width || fallback;
      setWidth(Math.max(180, Math.floor(measured)));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [fallback]);
  return [ref, width];
}

function latestPublished(points) {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    if (points[index]?.value != null) return points[index];
  }
  return null;
}

function clipText(text, maxWidthPx, charWidth = 6.2) {
  const limit = Math.max(6, Math.floor((maxWidthPx - 4) / charWidth));
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function LegendGlyph({ seriesKey, barsOnly }) {
  const color = COLORS[seriesKey];
  if (barsOnly) {
    return (
      <svg width="16" height="10" viewBox="0 0 16 10" aria-hidden="true">
        <rect x="0" y="0" width="16" height="10" rx="1.5" fill={color} />
      </svg>
    );
  }
  return (
    <svg width="24" height="10" viewBox="0 0 24 10" aria-hidden="true">
      <line
        x1="1"
        x2="23"
        y1="5"
        y2="5"
        stroke={color}
        strokeWidth="2"
        strokeDasharray={DASH_ARRAYS[seriesKey]}
      />
      <circle cx="12" cy="5" r={seriesKey === "area" ? 3 : 2.5} fill={color} />
    </svg>
  );
}

export function SectionChartLegend({ rows, areaLabel, stateLabel }) {
  const info = sectionChartInfo(rows);
  if (!info.hasCharts) return null;

  const items = [];
  if (info.hasArea) {
    items.push({ key: "area", label: areaLabel || "This area" });
  }
  if (info.hasState) {
    items.push({ key: "state", label: stateLabel || "State" });
  }
  if (info.hasNational) {
    items.push({ key: "national", label: "United States" });
  }
  if (!items.length) return null;

  return (
    <div className="section-chart-legend" role="list" aria-label="Chart series">
      {items.map((item) => (
        <span className="section-chart-legend-item" role="listitem" key={item.key}>
          <LegendGlyph seriesKey={item.key} barsOnly={info.barsOnly} />
          <span>{item.label}</span>
        </span>
      ))}
    </div>
  );
}

function TrendLineChart({ row, areaLabel, stateLabel }) {
  const [wrapRef, width] = useWidth(280);
  const svgRef = useRef(null);
  const [activeIndex, setActiveIndex] = useState(null);

  const trend = row.trend;
  const isPlaces = row.product === "places" || trend.style === "dots_ci";
  const drawLine = trend.style !== "dots_ci" && trend.style !== "dots";
  const drawWhiskers = trend.style === "dots_ci";

  const areaPoints = trend.series || [];
  const statePoints = isPlaces ? [] : (trend.state_series || []);
  const nationalPoints = isPlaces ? [] : (trend.national_series || []);
  const hasState = statePoints.some((point) => point.value != null);
  const hasNational = nationalPoints.some((point) => point.value != null);

  const resolvedAreaLabel = areaLabel || "This area";
  const resolvedStateLabel = stateLabel || row.comparisons?.state?.name || "State";

  const unavailableMap = new Map(
    (trend.unavailable_periods || []).map((item) => [item.period, item.reason || "Not published"])
  );
  const periods = [
    ...new Set([
      ...areaPoints.map((point) => point.period),
      ...statePoints.map((point) => point.period),
      ...nationalPoints.map((point) => point.period),
      ...unavailableMap.keys(),
    ]),
  ].sort();

  const areaByPeriod = new Map(areaPoints.map((point) => [point.period, point]));
  const stateByPeriod = new Map(statePoints.map((point) => [point.period, point]));
  const nationalByPeriod = new Map(nationalPoints.map((point) => [point.period, point]));

  const displayValues = [
    ...areaPoints.flatMap((point) =>
      drawWhiskers
        ? [
            toDisplayValue(point.value, row),
            toDisplayValue(point.low, row),
            toDisplayValue(point.high, row),
          ]
        : [toDisplayValue(point.value, row)]
    ),
    ...statePoints.map((point) => toDisplayValue(point.value, row)),
    ...nationalPoints.map((point) => toDisplayValue(point.value, row)),
  ];

  const { domain, ticks: yTicks } = computeYAxis(displayValues, row);
  const yTickLabels = yTicks.map((tick) => formatShortTick(tick, row));
  const maxTickChars = Math.max(...yTickLabels.map((label) => label.length), 3);

  const padLeft = Math.max(34, Math.min(54, Math.ceil(maxTickChars * 6.5 + 8)));
  const padRight = 10;
  const padTop = 10;
  const padBottom = 22;
  const plotLeft = padLeft;
  const plotRight = Math.max(padLeft + 60, width - padRight);
  const plotTop = padTop;
  const plotBottom = LINE_CHART_HEIGHT - padBottom;

  const xAt = (index) =>
    periods.length <= 1
      ? (plotLeft + plotRight) / 2
      : position(index, [0, periods.length - 1], plotLeft, plotRight);
  const yAt = (displayVal) => position(displayVal, domain, plotBottom, plotTop);

  const buildPath = (byPeriod) => {
    const segments = [];
    let penDown = false;
    for (let index = 0; index < periods.length; index += 1) {
      const period = periods[index];
      const point = byPeriod.get(period);
      if (!point || point.value == null || unavailableMap.has(period)) {
        penDown = false;
        continue;
      }
      const x = xAt(index).toFixed(1);
      const y = yAt(toDisplayValue(point.value, row)).toFixed(1);
      segments.push(`${penDown ? "L" : "M"}${x} ${y}`);
      penDown = true;
    }
    return segments.join(" ");
  };

  const areaPath = drawLine ? buildPath(areaByPeriod) : "";
  const statePath = drawLine && hasState ? buildPath(stateByPeriod) : "";
  const nationalPath = drawLine && hasNational ? buildPath(nationalByPeriod) : "";
  const xIndices = visibleXIndices(periods.length, plotRight - plotLeft);

  const nearestIndexFromEvent = (event) => {
    const svg = svgRef.current;
    if (!svg || !periods.length) return null;
    const rect = svg.getBoundingClientRect();
    const svgX = rect.width
      ? ((event.clientX - rect.left) / rect.width) * width
      : plotLeft;
    let bestIndex = 0;
    let bestDist = Infinity;
    for (let index = 0; index < periods.length; index += 1) {
      const dist = Math.abs(xAt(index) - svgX);
      if (dist < bestDist) {
        bestDist = dist;
        bestIndex = index;
      }
    }
    return bestIndex;
  };

  const handlePointerMove = (event) => {
    if (event.pointerType === "touch") return;
    setActiveIndex(nearestIndexFromEvent(event));
  };

  const handleClick = (event) => {
    const index = nearestIndexFromEvent(event);
    setActiveIndex(index);
  };

  const handleKeyDown = (event) => {
    if (!periods.length) return;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      setActiveIndex((current) =>
        current == null ? 0 : Math.min(periods.length - 1, current + 1)
      );
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      setActiveIndex((current) =>
        current == null ? periods.length - 1 : Math.max(0, current - 1)
      );
    } else if (event.key === "Escape") {
      setActiveIndex(null);
    }
  };

  const latestArea = latestPublished(areaPoints);
  const latestState = latestPublished(statePoints);
  const latestNational = latestPublished(nationalPoints);
  const summaryParts = [];
  if (latestArea) {
    summaryParts.push(
      `${resolvedAreaLabel} ${formatCardValue(latestArea.value, row)} (${latestArea.period})`
    );
  }
  if (latestState) {
    summaryParts.push(`${resolvedStateLabel} ${formatCardValue(latestState.value, row)}`);
  }
  if (latestNational) {
    summaryParts.push(`United States ${formatCardValue(latestNational.value, row)}`);
  }
  const ariaLabel = `${row.label} over time: ${summaryParts.join("; ")}`;

  const rawNote = trend.note || "";
  const shortNote =
    rawNote.length > NOTE_MAX_LENGTH
      ? `${rawNote.slice(0, NOTE_MAX_LENGTH).trimEnd()}…`
      : rawNote;

  const activePeriod = activeIndex != null ? periods[activeIndex] : null;
  const activeUnavailable = activePeriod != null ? unavailableMap.get(activePeriod) : null;
  const activeArea = activePeriod != null ? areaByPeriod.get(activePeriod) : null;
  const activeState = activePeriod != null ? stateByPeriod.get(activePeriod) : null;
  const activeNational = activePeriod != null ? nationalByPeriod.get(activePeriod) : null;

  const renderDots = (byPeriod, seriesKey) =>
    periods.map((period, index) => {
      const point = byPeriod.get(period);
      if (!point || point.value == null || unavailableMap.has(period)) return null;
      const cx = xAt(index);
      const cy = yAt(toDisplayValue(point.value, row));
      return (
        <circle
          key={`${seriesKey}-${period}`}
          className="indicator-chart-dot"
          data-series={seriesKey}
          cx={cx}
          cy={cy}
          r={DOT_RADIUS[seriesKey]}
          fill={COLORS[seriesKey]}
          stroke="#ffffff"
          strokeWidth="0.75"
        />
      );
    });

  return (
    <div ref={wrapRef} className="indicator-chart">
      <div
        className="indicator-chart-stage"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onBlur={() => setActiveIndex(null)}
      >
        <svg
          ref={svgRef}
          role="img"
          aria-label={ariaLabel}
          viewBox={`0 0 ${width} ${LINE_CHART_HEIGHT}`}
          width="100%"
          height={LINE_CHART_HEIGHT}
          onPointerMove={handlePointerMove}
          onMouseMove={handlePointerMove}
          onMouseLeave={() => setActiveIndex(null)}
          onClick={handleClick}
        >
          {yTicks.map((tick, index) => {
            const y = yAt(tick);
            return (
              <g key={tick}>
                <line
                  x1={plotLeft}
                  x2={plotRight}
                  y1={y}
                  y2={y}
                  stroke="#e3eaee"
                  strokeWidth="1"
                />
                <text
                  className="indicator-chart-axis-label"
                  x={padLeft - 6}
                  y={y + 3.5}
                  textAnchor="end"
                >
                  {yTickLabels[index]}
                </text>
              </g>
            );
          })}

          {xIndices.map((index) => (
            <text
              key={periods[index]}
              className="indicator-chart-axis-label"
              x={xAt(index)}
              y={LINE_CHART_HEIGHT - 6}
              textAnchor={
                index === 0
                  ? "start"
                  : index === periods.length - 1
                  ? "end"
                  : "middle"
              }
            >
              {shortPeriod(periods[index])}
            </text>
          ))}

          {activeIndex != null && (
            <line
              className="indicator-chart-guide"
              x1={xAt(activeIndex)}
              x2={xAt(activeIndex)}
              y1={plotTop}
              y2={plotBottom}
              stroke="#90a4ae"
              strokeWidth="1"
              strokeDasharray="2 2"
            />
          )}

          {hasNational && (
            <g data-series-group="national">
              {nationalPath && (
                <path
                  className="indicator-chart-line"
                  data-series="national"
                  d={nationalPath}
                  fill="none"
                  stroke={COLORS.national}
                  strokeWidth="2"
                  strokeDasharray={DASH_ARRAYS.national}
                />
              )}
              {renderDots(nationalByPeriod, "national")}
            </g>
          )}

          {hasState && (
            <g data-series-group="state">
              {statePath && (
                <path
                  className="indicator-chart-line"
                  data-series="state"
                  d={statePath}
                  fill="none"
                  stroke={COLORS.state}
                  strokeWidth="2"
                  strokeDasharray={DASH_ARRAYS.state}
                />
              )}
              {renderDots(stateByPeriod, "state")}
            </g>
          )}

          <g data-series-group="area">
            {areaPath && (
              <path
                className="indicator-chart-line"
                data-series="area"
                d={areaPath}
                fill="none"
                stroke={COLORS.area}
                strokeWidth="2"
              />
            )}
            {drawWhiskers &&
              periods.map((period, index) => {
                const point = areaByPeriod.get(period);
                if (
                  !point ||
                  point.value == null ||
                  point.low == null ||
                  point.high == null ||
                  unavailableMap.has(period)
                ) {
                  return null;
                }
                const x = xAt(index);
                const yLow = yAt(Math.max(domain[0], toDisplayValue(point.low, row)));
                const yHigh = yAt(Math.min(domain[1], toDisplayValue(point.high, row)));
                return (
                  <line
                    key={`whisker-${period}`}
                    className="indicator-chart-whisker"
                    x1={x}
                    x2={x}
                    y1={yLow}
                    y2={yHigh}
                    stroke={COLORS.area}
                    strokeWidth="1.5"
                  />
                );
              })}
            {renderDots(areaByPeriod, "area")}
          </g>
        </svg>

        {activePeriod != null && (
          <div
            className={`indicator-chart-tooltip ${
              activeIndex >= periods.length / 2 ? "is-left" : "is-right"
            }`}
            role="status"
          >
            <strong>{activePeriod}</strong>
            {activeUnavailable ? (
              <div className="indicator-chart-tooltip-row">{activeUnavailable}</div>
            ) : (
              <>
                <div className="indicator-chart-tooltip-row">
                  <span
                    className="indicator-chart-tooltip-dot"
                    style={{ backgroundColor: COLORS.area }}
                  />
                  <span>
                    {resolvedAreaLabel}:{" "}
                    {formatCardValue(activeArea?.value, row, activeArea?.status_text)}
                  </span>
                </div>
                {hasState && (
                  <div className="indicator-chart-tooltip-row">
                    <span
                      className="indicator-chart-tooltip-dot"
                      style={{ backgroundColor: COLORS.state }}
                    />
                    <span>
                      {resolvedStateLabel}:{" "}
                      {formatCardValue(activeState?.value, row, activeState?.status_text)}
                    </span>
                  </div>
                )}
                {hasNational && (
                  <div className="indicator-chart-tooltip-row">
                    <span
                      className="indicator-chart-tooltip-dot"
                      style={{ backgroundColor: COLORS.national }}
                    />
                    <span>
                      United States:{" "}
                      {formatCardValue(
                        activeNational?.value,
                        row,
                        activeNational?.status_text
                      )}
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {rawNote && (
        <p className="indicator-chart-caption" title={rawNote}>
          {shortNote}
        </p>
      )}

      <table className="sr-only">
        <caption>
          {row.label}
          {rawNote ? ` — ${rawNote}` : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">Period</th>
            <th scope="col">{resolvedAreaLabel}</th>
            {hasState && <th scope="col">{resolvedStateLabel}</th>}
            {hasNational && <th scope="col">United States</th>}
          </tr>
        </thead>
        <tbody>
          {periods.map((period) => {
            const unavailable = unavailableMap.get(period);
            const areaPoint = areaByPeriod.get(period);
            const statePoint = stateByPeriod.get(period);
            const nationalPoint = nationalByPeriod.get(period);
            return (
              <tr key={period}>
                <th scope="row">{period}</th>
                <td>
                  {unavailable ||
                    formatCardValue(areaPoint?.value, row, areaPoint?.status_text)}
                </td>
                {hasState && (
                  <td>
                    {unavailable ||
                      (statePoint
                        ? formatCardValue(statePoint.value, row, statePoint.status_text)
                        : "—")}
                  </td>
                )}
                {hasNational && (
                  <td>
                    {unavailable ||
                      (nationalPoint
                        ? formatCardValue(
                            nationalPoint.value,
                            row,
                            nationalPoint.status_text
                          )
                        : "—")}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ComparisonBarsChart({ row, areaLabel, stateLabel }) {
  const [wrapRef, width] = useWidth(280);

  const bars = [];
  if (row.value != null) {
    bars.push({
      key: "area",
      label: areaLabel || "This district",
      rawValue: row.value,
      displayValue: Math.max(0, toDisplayValue(row.value, row)),
      color: COLORS.area,
    });
  }
  if (row.comparisons?.state?.value != null) {
    bars.push({
      key: "state",
      label: stateLabel || row.comparisons.state.name || "State",
      rawValue: row.comparisons.state.value,
      displayValue: Math.max(0, toDisplayValue(row.comparisons.state.value, row)),
      color: COLORS.state,
    });
  }
  if (row.comparisons?.national?.value != null) {
    bars.push({
      key: "national",
      label: "United States",
      rawValue: row.comparisons.national.value,
      displayValue: Math.max(0, toDisplayValue(row.comparisons.national.value, row)),
      color: COLORS.national,
    });
  }
  if (!bars.length) return null;

  const maxVal = Math.max(...bars.map((bar) => bar.displayValue), 0);
  const maxDomain =
    maxVal <= 0
      ? 1
      : isPercentRow(row) && maxVal <= 100
      ? Math.min(100, Math.max(maxVal * 1.15, 1))
      : maxVal * 1.1;

  const rowHeight = 22;
  const barHeight = 10;
  const svgHeight = bars.length * rowHeight + 6;
  const labelWidth = Math.min(108, Math.round(width * 0.36));
  const valueWidth = 54;
  const barX = labelWidth + 6;
  const barMaxWidth = Math.max(36, width - barX - valueWidth - 4);

  const ariaLabel = `${row.label} (${row.period || "current"}): ${bars
    .map((bar) => `${bar.label} ${formatCardValue(bar.rawValue, row)}`)
    .join("; ")}`;

  return (
    <div ref={wrapRef} className="indicator-chart indicator-chart-bars">
      <svg
        role="img"
        aria-label={ariaLabel}
        viewBox={`0 0 ${width} ${svgHeight}`}
        width="100%"
        height={svgHeight}
      >
        {bars.map((bar, index) => {
          const rowTop = 3 + index * rowHeight;
          const barY = rowTop + (rowHeight - barHeight) / 2;
          const textY = rowTop + rowHeight / 2 + 4;
          const barW =
            bar.displayValue > 0
              ? Math.max(2, (bar.displayValue / maxDomain) * barMaxWidth)
              : 0;
          return (
            <g key={bar.key} data-bar-row={bar.key}>
              <text className="indicator-chart-bar-label" x="0" y={textY}>
                {clipText(bar.label, labelWidth)}
                <title>{bar.label}</title>
              </text>
              <rect
                className="indicator-chart-bar"
                data-series={bar.key}
                x={barX}
                y={barY}
                width={barW.toFixed(1)}
                height={barHeight}
                rx="1.5"
                fill={bar.color}
              />
              <text
                className="indicator-chart-bar-value"
                x={width}
                y={textY}
                textAnchor="end"
              >
                {formatCardValue(bar.rawValue, row)}
              </text>
            </g>
          );
        })}
      </svg>

      <table className="sr-only">
        <caption>
          {row.label}
          {row.period ? ` (${row.period})` : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">Area</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {bars.map((bar) => (
            <tr key={bar.key}>
              <th scope="row">{bar.label}</th>
              <td>{formatCardValue(bar.rawValue, row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function IndicatorChart({ row, areaLabel, stateLabel }) {
  if (!row) return null;
  if (hasTrendChart(row)) {
    return <TrendLineChart row={row} areaLabel={areaLabel} stateLabel={stateLabel} />;
  }
  if (hasBarChart(row)) {
    return (
      <ComparisonBarsChart row={row} areaLabel={areaLabel} stateLabel={stateLabel} />
    );
  }
  return null;
}
