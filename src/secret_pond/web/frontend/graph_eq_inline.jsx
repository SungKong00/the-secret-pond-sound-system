import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  CompositeCurve,
  FilterPoint,
  FrequencyResponseGraph,
  PointerTracker,
} from "dsssp";
import {
  graphEqDisplayConfig,
  isLockedEndpointPoint,
  toDssspFilters,
  toSecretPondPoints,
} from "./graph_eq_dsssp_adapter.mjs";

const mountedEditors = new WeakMap();
const emptyPoints = Object.freeze([]);

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
    if (!dragging) setLocalPoints(normalizedPoints);
  }, [dragging, normalizedPoints]);

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
      if (event.ended || !draggingRef.current) setLocalPoints(nextPoints);
      onChange?.({
        layerId,
        points: nextPoints,
        selectedPointId: nextPoint?.id || null,
        ended: Boolean(event.ended),
      });
    },
    [disabled, layerId, onChange, onSelect],
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
        width={900}
        height={360}
        scale={graphEqDisplayConfig}
        theme={graphTheme}
        style={{ width: "100%", height: "100%" }}
      >
        <CompositeCurve filters={filters} />
        {filters.map((filter, index) => {
          const point = localPoints[index];
          return (
            <FilterPoint
              key={point?.id || index}
              filter={filter}
              index={index}
              active={index === selectedIndex}
              dragX={!isLockedEndpointPoint(point, index, localPoints)}
              dragY={!disabled}
              wheelQ={!disabled}
              label={String(index + 1)}
              onChange={handleChange}
              onDrag={handleDrag}
              onEnter={() => point && onSelect?.(point.id)}
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
