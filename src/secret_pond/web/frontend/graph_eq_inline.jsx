import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  CompositeCurve,
  FilterCurve,
  FrequencyResponseGraph,
  PointerTracker,
} from "dsssp";
import {
  frequencyToX,
  graphEqDisplayConfig,
  toDssspFilters,
  toSecretPondPoints,
  visualFrequencyForPoint,
} from "./graph_eq_dsssp_adapter.mjs";

const mountedEditors = new WeakMap();
const emptyPoints = Object.freeze([]);
const graphWidth = 900;
const graphHeight = 320;
const pointVisualInset = 15;
const maxGraphEqPoints = 6;
const movementThresholdPx = 4;

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

const pointFrequencyToGraphX = (point, frequency) => (
  frequencyToX(
    point?.type === "bell" ? frequency : visualFrequencyForPoint(point, graphEqDisplayConfig),
    graphEqDisplayConfig,
  ) * graphWidth
);

const graphXToFrequency = (x) => {
  const minLog = Math.log10(graphEqDisplayConfig.minFreq);
  const maxLog = Math.log10(graphEqDisplayConfig.maxFreq);
  const ratio = clamp(x, 0, graphWidth) / graphWidth;
  return Math.round(10 ** (minLog + ratio * (maxLog - minLog)));
};

const pointVisualX = (point, x) => {
  if (point?.type === "low_shelf") return pointVisualInset;
  if (point?.type === "high_shelf") return graphWidth - pointVisualInset;
  return clamp(x, pointVisualInset, graphWidth - pointVisualInset);
};
const pointVisualY = (y) => clamp(y, pointVisualInset, graphHeight - pointVisualInset);

const pointerToGraphPosition = (event, svg) => {
  const rect = svg?.getBoundingClientRect();
  if (!rect?.width || !rect?.height) return null;
  return {
    x: ((event.clientX - rect.left) / rect.width) * graphWidth,
    y: ((event.clientY - rect.top) / rect.height) * graphHeight,
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
      radius: 10,
      lineWidth: 2,
      backgroundOpacity: { normal: 0.88, active: 1, drag: 1 },
    },
    curve: {
      width: { normal: 1, active: 2 },
      opacity: { normal: 0.35, active: 0.75 },
    },
    zeroPoint: { color: "rgba(255,255,255,0.35)", background: "#101312" },
  },
};

const normalizePoints = (points) => (Array.isArray(points) ? points : emptyPoints);

const isGraphEqPointDeletable = (point) => point?.type === "bell";

const graphEqWithSortedBells = (points) => {
  const sourcePoints = normalizePoints(points);
  const lowShelf = sourcePoints.find((point) => point?.type === "low_shelf") || null;
  const highShelf = sourcePoints.find((point) => point?.type === "high_shelf") || null;
  const bells = sourcePoints
    .map((point, pointIndex) => ({ point, index: pointIndex }))
    .filter(({ point }) => point?.type === "bell")
    .sort((a, b) => (
      Number(a.point.frequency_hz) - Number(b.point.frequency_hz) ||
        a.index - b.index
    ))
    .map(({ point }) => point);
  return [lowShelf, ...bells, highShelf].filter(Boolean).slice(0, maxGraphEqPoints);
};

const graphEqWithNewestBell = (points, nextPoint) => {
  const sourcePoints = normalizePoints(points);
  const lowShelf = sourcePoints.find((point) => point?.type === "low_shelf") || null;
  const highShelf = sourcePoints.find((point) => point?.type === "high_shelf") || null;
  const bells = sourcePoints.filter((point) => point?.type === "bell");
  return graphEqWithSortedBells([lowShelf, nextPoint, ...bells, highShelf]);
};

function GraphEqFilterPoint({
  filter,
  index,
  point,
  active,
  disabled,
  onChange,
  onSelect,
  onDelete,
  onDrag,
}) {
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const filterRef = useRef(filter);

  useEffect(() => {
    filterRef.current = filter;
  }, [filter]);

  const x = pointFrequencyToGraphX(point, filter.freq);
  const y = gainToGraphY(filter.gain);
  const visualX = pointVisualX(point, x);
  const visualY = pointVisualY(y);
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
      const nextX = point?.type === "bell" ? position.x - offset.x : visualX;
      const nextY = position.y - offset.y;
      onChange?.({
        index,
        ...current,
        freq: graphXToFrequency(nextX),
        gain: graphYToGain(nextY),
        ended,
      });
    },
    [index, onChange, point?.type, visualX],
  );

  const handlePointerDown = useCallback(
    (event) => {
      if (disabled) return;
      event.preventDefault();
      event.stopPropagation();

      const svg = event.currentTarget.ownerSVGElement;
      const dragWindow = svg?.ownerDocument?.defaultView || window;
      const startPosition = pointerToGraphPosition(event, svg);
      const startClient = { x: event.clientX, y: event.clientY };
      let hasDragged = false;
      const offset = {
        x: (startPosition?.x ?? visualX) - visualX,
        y: (startPosition?.y ?? visualY) - visualY,
      };
      const startDrag = (dragEvent) => {
        if (hasDragged) return;
        hasDragged = true;
        onSelect?.(point?.id);
        onDrag?.(true);
        setDragging(true);
        emitChange(dragEvent, false, svg, offset);
      };
      const handlePointerMove = (moveEvent) => {
        moveEvent.preventDefault();
        const movement = Math.hypot(
          moveEvent.clientX - startClient.x,
          moveEvent.clientY - startClient.y,
        );
        if (!hasDragged && movement <= movementThresholdPx) return;
        if (!hasDragged) {
          startDrag(moveEvent);
          return;
        }
        emitChange(moveEvent, false, svg, offset);
      };
      const finishDrag = (upEvent) => {
        upEvent.preventDefault();
        dragWindow.removeEventListener("pointermove", handlePointerMove);
        dragWindow.removeEventListener("pointerup", finishDrag);
        dragWindow.removeEventListener("pointercancel", finishDrag);
        if (hasDragged) {
          emitChange(upEvent, true, svg, offset);
          setDragging(false);
          onDrag?.(false);
          return;
        }
        onSelect?.(point?.id);
      };

      dragWindow.addEventListener("pointermove", handlePointerMove);
      dragWindow.addEventListener("pointerup", finishDrag, { once: true });
      dragWindow.addEventListener("pointercancel", finishDrag, { once: true });
    },
    [disabled, emitChange, onDrag, onSelect, point?.id, visualX, visualY],
  );

  const handleClick = useCallback(
    (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.detail >= 2 && isGraphEqPointDeletable(point)) {
        onDelete?.(point?.id);
        return;
      }
      onSelect?.(point?.id);
    },
    [onDelete, onSelect, point],
  );

  const handleDoubleClick = useCallback(
    (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!isGraphEqPointDeletable(point)) return;
      onDelete?.(point?.id);
    },
    [onDelete, point],
  );

  return (
    <>
      <circle
        data-graph-eq-filter-point="true"
        cx={visualX}
        cy={visualY}
        r={pointTheme.radius}
        fill={fillColor}
        fillOpacity={dragging || active || hovered ? 1 : pointTheme.backgroundOpacity.normal}
        stroke={strokeColor}
        strokeWidth={pointTheme.lineWidth}
        onPointerDown={handlePointerDown}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          cursor: disabled ? "default" : dragging ? "grabbing" : "grab",
          pointerEvents: "auto",
        }}
      />
    </>
  );
}

function GraphEqDssspEditor({
  layerId,
  points = emptyPoints,
  selectedPointId = null,
  disabled = false,
  onChange,
  onChangeCommitted,
  onSelect,
  onDelete,
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
  const selectedFilter = filters[selectedIndex] || null;
  const selectedFilterColor = graphTheme.filters.colors[selectedIndex]?.point ||
    graphTheme.filters.defaultColor;

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
      const payload = {
        layerId,
        points: nextPoints,
        selectedPointId: nextPoint?.id || null,
        ended: Boolean(event.ended),
      };
      onChange?.(payload);
      if (payload.ended) onChangeCommitted?.(payload);
    },
    [disabled, layerId, onChange, onChangeCommitted],
  );

  const handleDrag = useCallback(
    (active) => {
      draggingRef.current = active;
      setDragging(active);
      onDragState?.({ layerId, dragging: active });
    },
    [layerId, onDragState],
  );

  const handleSurfaceClick = useCallback(
    (event) => {
      if (disabled || draggingRef.current) return;
      if (latestPointsRef.current.length >= maxGraphEqPoints) return;
      if (event.target?.closest?.("[data-graph-eq-filter-point]")) return;
      event.preventDefault();
      event.stopPropagation();
      const svg = event.target?.ownerSVGElement || event.currentTarget.querySelector?.("svg");
      const position = pointerToGraphPosition(event, svg);
      if (position === null) return;
      const previousPoints = latestPointsRef.current;
      const id = `point-${Date.now().toString(36)}`;
      const nextPoint = {
        id,
        type: "bell",
        frequency_hz: graphXToFrequency(position.x),
        gain_db: graphYToGain(position.y),
        q: 1,
      };
      const nextPoints = graphEqWithNewestBell(previousPoints, nextPoint);
      latestPointsRef.current = nextPoints;
      setLocalPoints(nextPoints);
      const payload = {
        layerId,
        points: nextPoints,
        selectedPointId: id,
        ended: true,
      };
      onChange?.(payload);
      onChangeCommitted?.(payload);
    },
    [disabled, layerId, onChange, onChangeCommitted],
  );

  const handleDelete = useCallback(
    (pointId) => {
      if (disabled) return;
      const previousPoints = latestPointsRef.current;
      const selected = previousPoints.find((point) => point.id === pointId);
      if (!isGraphEqPointDeletable(selected)) return;
      const nextPoints = previousPoints.filter((point) => point.id !== pointId);
      const nextSelectedPointId = nextPoints.find((point) => point.type === "bell")?.id || null;
      latestPointsRef.current = nextPoints;
      setLocalPoints(nextPoints);
      onDelete?.({
        layerId,
        pointId,
        points: nextPoints,
        selectedPointId: nextSelectedPointId,
      });
    },
    [disabled, layerId, onDelete],
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
        {selectedFilter && (
          <FilterCurve
            filter={selectedFilter}
            index={selectedIndex}
            color={selectedFilterColor}
            opacity={0.72}
            lineWidth={1.15}
            dotted
            className="graph-eq-selected-band-curve"
          />
        )}
        <CompositeCurve filters={filters} />
        {!dragging && <PointerTracker />}
        <rect
          data-graph-eq-surface-hit-area="true"
          x={0}
          y={0}
          width={graphWidth}
          height={graphHeight}
          fill="transparent"
          style={{ pointerEvents: "all" }}
          onClick={handleSurfaceClick}
        />
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
              onChange={handleChange}
              onSelect={onSelect}
              onDelete={handleDelete}
              onDrag={handleDrag}
            />
          );
        })}
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
