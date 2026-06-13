import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  CompositeCurve,
  FrequencyResponseGraph,
  PointerTracker,
} from "dsssp";
import {
  frequencyToX,
  graphEqDisplayConfig,
  toDssspFilters,
  toSecretPondPoints,
} from "./graph_eq_dsssp_adapter.mjs";

const mountedEditors = new WeakMap();
const emptyPoints = Object.freeze([]);
const graphWidth = 900;
const graphHeight = 320;

const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value)));

const gainToGraphY = (gain) => (
  (graphEqDisplayConfig.maxGain - clamp(gain, graphEqDisplayConfig.minGain, graphEqDisplayConfig.maxGain)) /
  (graphEqDisplayConfig.maxGain - graphEqDisplayConfig.minGain) *
  graphHeight
);

const graphYToGain = (y) => Number((
  graphEqDisplayConfig.maxGain -
    (clamp(y, 0, graphHeight) / graphHeight) *
      (graphEqDisplayConfig.maxGain - graphEqDisplayConfig.minGain)
).toFixed(1));

const frequencyToGraphX = (frequency) => frequencyToX(frequency, graphEqDisplayConfig) * graphWidth;

const graphXToFrequency = (x) => {
  const minLog = Math.log10(graphEqDisplayConfig.minFreq);
  const maxLog = Math.log10(graphEqDisplayConfig.maxFreq);
  const ratio = clamp(x, 0, graphWidth) / graphWidth;
  return Math.round(10 ** (minLog + ratio * (maxLog - minLog)));
};

const pointerToGraphPosition = (event, svg) => {
  const rect = svg?.getBoundingClientRect();
  if (!rect?.width || !rect?.height) return null;
  return {
    x: clamp(((event.clientX - rect.left) / rect.width) * graphWidth, 0, graphWidth),
    y: clamp(((event.clientY - rect.top) / rect.height) * graphHeight, 0, graphHeight),
  };
};

const graphTheme = {
  background: {
    grid: {
      dotted: false,
      lineColor: "rgba(232, 226, 209, 0.14)",
      lineWidth: { minor: 0.55, major: 0.9, center: 1.2, border: 1 },
    },
    gradient: { start: "#171b1d", stop: "#070909", direction: "vertical" },
    label: {
      color: "rgba(232, 226, 209, 0.62)",
      fontSize: 10,
      fontFamily: "Inter, system-ui, sans-serif",
    },
    tracker: {
      lineWidth: 1,
      lineColor: "rgba(226, 184, 79, 0.5)",
      labelColor: "#e8d18a",
      backgroundColor: "#111412",
    },
  },
  curve: { width: 2, color: "#e2b84f", opacity: 1 },
  filters: {
    fill: false,
    gradientOpacity: 0.18,
    defaultColor: "#e2b84f",
    colors: [
      {
        point: "#81c995",
        curve: "#81c995",
        active: "#ffffff",
        drag: "#ffffff",
        background: "#1f3a2a",
        activeBackground: "#34543d",
        dragBackground: "#3f694a",
      },
      {
        point: "#e2b84f",
        curve: "#e2b84f",
        active: "#ffffff",
        drag: "#ffffff",
        background: "#3c3218",
        activeBackground: "#594820",
        dragBackground: "#725c27",
      },
      {
        point: "#8ab4f8",
        curve: "#8ab4f8",
        active: "#ffffff",
        drag: "#ffffff",
        background: "#1d2f4d",
        activeBackground: "#294266",
        dragBackground: "#365786",
      },
    ],
    point: {
      radius: 13,
      lineWidth: 2,
      backgroundOpacity: { normal: 0.88, active: 1, drag: 1 },
      label: {
        color: "#f2f1ea",
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 11,
      },
    },
    curve: {
      width: { normal: 1, active: 2 },
      opacity: { normal: 0.35, active: 0.75 },
    },
    zeroPoint: { color: "rgba(255,255,255,0.35)", background: "#101312" },
  },
};

const normalizePoints = (points) => (Array.isArray(points) ? points : emptyPoints);

function GraphEqFilterPoint({
  filter,
  index,
  point,
  active,
  disabled,
  label,
  onChange,
  onSelect,
  onDrag,
}) {
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const filterRef = useRef(filter);

  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);

  const x = frequencyToGraphX(filter.freq);
  const y = gainToGraphY(filter.gain);
  const color = graphTheme.filters.colors[index] || {};
  const pointTheme = graphTheme.filters.point;
  const pointColor = color.point || graphTheme.filters.defaultColor;
  const fillColor = dragging
    ? color.dragBackground || pointColor
    : active || hovered
      ? color.activeBackground || pointColor
      : color.background || pointColor;
  const strokeColor = dragging
    ? color.drag || pointColor
    : active || hovered
      ? color.active || pointColor
      : pointColor;

  const emitChange = useCallback(
    (event, ended = false, svgOverride = null, offset = { x: 0, y: 0 }) => {
      const currentTarget = event.currentTarget;
      const target = event.target;
      const svg = svgOverride ||
        currentTarget?.ownerSVGElement ||
        (String(currentTarget?.tagName || "").toLowerCase() === "svg" ? currentTarget : null) ||
        target?.ownerSVGElement ||
        (String(target?.tagName || "").toLowerCase() === "svg" ? target : null);
      const position = pointerToGraphPosition(event, svg);
      if (position === null) return;
      const current = filterRef.current;
      const nextX = position.x - offset.x;
      const nextY = position.y - offset.y;
      onChange?.({
        index,
        ...current,
        freq: graphXToFrequency(nextX),
        gain: graphYToGain(nextY),
        ended,
      });
    },
    [index, onChange],
  );

  const handlePointerDown = useCallback(
    (event) => {
      if (disabled) return;
      event.preventDefault();
      event.stopPropagation();
      onSelect?.(point?.id);
      onDrag?.(true);
      setDragging(true);

      const svg = event.currentTarget.ownerSVGElement;
      const dragWindow = svg?.ownerDocument?.defaultView || window;
      const startPosition = pointerToGraphPosition(event, svg);
      const offset = {
        x: (startPosition?.x ?? x) - x,
        y: (startPosition?.y ?? y) - y,
      };
      emitChange(event, false, svg, offset);
      const handlePointerMove = (moveEvent) => {
        moveEvent.preventDefault();
        emitChange(moveEvent, false, svg, offset);
      };
      const finishDrag = (upEvent) => {
        upEvent.preventDefault();
        dragWindow.removeEventListener("pointermove", handlePointerMove);
        dragWindow.removeEventListener("pointerup", finishDrag);
        dragWindow.removeEventListener("pointercancel", finishDrag);
        emitChange(upEvent, true, svg, offset);
        setDragging(false);
        onDrag?.(false);
      };

      dragWindow.addEventListener("pointermove", handlePointerMove);
      dragWindow.addEventListener("pointerup", finishDrag, { once: true });
      dragWindow.addEventListener("pointercancel", finishDrag, { once: true });
    },
    [disabled, emitChange, onDrag, onSelect, point?.id, x, y],
  );

  return (
    <>
      <circle
        cx={x}
        cy={y}
        r={pointTheme.radius}
        fill={fillColor}
        fillOpacity={dragging || active || hovered ? 1 : pointTheme.backgroundOpacity.normal}
        stroke={strokeColor}
        strokeWidth={pointTheme.lineWidth}
        onPointerDown={handlePointerDown}
        onMouseEnter={() => {
          setHovered(true);
          onSelect?.(point?.id);
        }}
        onMouseLeave={() => setHovered(false)}
        style={{
          cursor: disabled ? "default" : dragging ? "grabbing" : "grab",
          pointerEvents: "auto",
        }}
      />
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="central"
        fill={pointTheme.label.color}
        fontSize={pointTheme.label.fontSize}
        fontFamily={pointTheme.label.fontFamily}
        style={{ pointerEvents: "none", userSelect: "none" }}
      >
        {label}
      </text>
    </>
  );
}

function GraphEqDssspEditor({
  layerId,
  points = emptyPoints,
  selectedPointId = null,
  disabled = false,
  onChange,
  onSelect,
  onDragState,
}) {
  const normalizedPoints = normalizePoints(points);
  const [localPoints, setLocalPoints] = useState(normalizedPoints);
  const [dragging, setDragging] = useState(false);
  const latestPointsRef = useRef(localPoints);
  const draggingRef = useRef(false);

  useEffect(() => {
    latestPointsRef.current = localPoints;
  }, [localPoints]);

  useEffect(() => {
    if (!draggingRef.current) setLocalPoints(normalizedPoints);
  }, [normalizedPoints]);

  const filters = useMemo(() => toDssspFilters(localPoints), [localPoints]);
  const selectedIndex = Math.max(
    0,
    localPoints.findIndex((point) => point.id === selectedPointId),
  );

  const handleChange = useCallback(
    (event) => {
      if (disabled) return;
      const previousPoints = latestPointsRef.current;
      const nextFilters = toDssspFilters(previousPoints);
      nextFilters[event.index] = {
        ...nextFilters[event.index],
        type: event.type,
        freq: event.freq,
        gain: event.gain,
        q: event.q,
      };
      const nextPoints = toSecretPondPoints(nextFilters, previousPoints);
      const nextPoint = nextPoints[event.index] || null;
      latestPointsRef.current = nextPoints;
      setLocalPoints(nextPoints);
      onChange?.({
        layerId,
        points: nextPoints,
        selectedPointId: nextPoint?.id || null,
        ended: Boolean(event.ended),
      });
    },
    [disabled, layerId, onChange],
  );

  const handleDrag = useCallback(
    (active) => {
      draggingRef.current = active;
      setDragging(active);
      onDragState?.({ layerId, dragging: active });
    },
    [layerId, onDragState],
  );

  return (
    <div
      className="graph-eq-dsssp-surface"
      data-graph-eq-dsssp-root="true"
      data-graph-eq-layer-id={layerId}
    >
      <FrequencyResponseGraph
        width={graphWidth}
        height={graphHeight}
        scale={graphEqDisplayConfig}
        theme={graphTheme}
        style={{ width: "100%", height: "100%" }}
      >
        <CompositeCurve filters={filters} />
        {filters.map((filter, index) => {
          const point = localPoints[index];
          return (
            <GraphEqFilterPoint
              key={point?.id || index}
              filter={filter}
              index={index}
              point={point}
              active={index === selectedIndex}
              disabled={disabled}
              label={String(index + 1)}
              onChange={handleChange}
              onSelect={onSelect}
              onDrag={handleDrag}
            />
          );
        })}
        {!dragging && <PointerTracker />}
      </FrequencyResponseGraph>
    </div>
  );
}

const renderEditor = (mounted) => {
  mounted.root.render(<GraphEqDssspEditor {...mounted.props} />);
};

const mountEditor = (container, props = {}) => {
  if (!container) return null;
  let mounted = mountedEditors.get(container);
  if (!mounted) {
    mounted = { root: createRoot(container), props: {} };
    mountedEditors.set(container, mounted);
  }
  mounted.props = { ...mounted.props, ...props };
  renderEditor(mounted);
  return mounted;
};

const syncEditor = (container, props = {}) => mountEditor(container, props);

const unmountEditor = (container) => {
  const mounted = mountedEditors.get(container);
  if (!mounted) return false;
  mounted.root.unmount();
  mountedEditors.delete(container);
  return true;
};

const api = Object.freeze({
  mountEditor,
  syncEditor,
  unmountEditor,
  toDssspFilters,
  toSecretPondPoints,
});

window.secretPondDssspGraphEq = api;
window.secretPondGraphEq = api;
