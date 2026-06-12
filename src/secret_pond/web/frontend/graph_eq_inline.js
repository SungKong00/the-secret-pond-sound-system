import { WEQ8Runtime } from "weq8c";
import "weq8c/ui";

const MAX_SECRET_POND_EQ_POINTS = 6;
const SUPPORTED_SECRET_POND_TYPES = Object.freeze({
  low_shelf: "lowshelf12",
  bell: "peaking12",
  high_shelf: "highshelf12",
});
const WEQ8C_TO_SECRET_POND_TYPES = Object.freeze({
  lowshelf12: "low_shelf",
  lowshelf24: "low_shelf",
  peaking12: "bell",
  peaking24: "bell",
  highshelf12: "high_shelf",
  highshelf24: "high_shelf",
});
const NOOP_FILTER = Object.freeze({
  type: "noop",
  frequency: 350,
  gain: 0,
  Q: 1,
  bypass: false,
});

const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value)));

const normalizeSecretPondPoint = (point, index = 0) => {
  const type = WEQ8C_TO_SECRET_POND_TYPES[point?.type] || point?.type || "bell";
  return {
    id: String(point?.id || `point-${index + 1}`),
    type,
    frequency_hz: Math.round(clamp(point?.frequency_hz ?? point?.frequency ?? 1000, 20, 20000)),
    gain_db: Number(clamp(point?.gain_db ?? point?.gain ?? 0, -18, 18).toFixed(1)),
    q: Number(clamp(point?.q ?? point?.Q ?? 1, 0.1, 18).toFixed(2)),
  };
};

const toSecretPondEqPoints = (filters = []) => filters
  .map((filter, index) => normalizeSecretPondPoint(filter, index))
  .filter((point) => Object.hasOwn(SUPPORTED_SECRET_POND_TYPES, point.type))
  .slice(0, MAX_SECRET_POND_EQ_POINTS);

const fromSecretPondEqPoints = (points = []) => points
  .map((point, index) => normalizeSecretPondPoint(point, index))
  .filter((point) => Object.hasOwn(SUPPORTED_SECRET_POND_TYPES, point.type))
  .slice(0, MAX_SECRET_POND_EQ_POINTS)
  .map((point) => ({
    id: point.id,
    type: SUPPORTED_SECRET_POND_TYPES[point.type],
    frequency: point.frequency_hz,
    gain: point.gain_db,
    Q: point.q,
    bypass: false,
  }));

const toWeq8cSpec = (points = []) => {
  const filters = fromSecretPondEqPoints(points);
  while (filters.length < 8) filters.push({ ...NOOP_FILTER });
  return filters.slice(0, 8);
};

const createAudioContext = () => {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  return AudioContextClass ? new AudioContextClass() : null;
};

const createRuntime = (points = [], audioContext = createAudioContext()) => {
  if (!audioContext) return null;
  return new WEQ8Runtime(audioContext, toWeq8cSpec(points));
};

const syncRuntime = (runtime, points = []) => {
  if (!runtime?.spec) return null;
  const nextSpec = toWeq8cSpec(points);
  nextSpec.forEach((filter, index) => {
    if (runtime.spec[index]?.type !== filter.type) runtime.setFilterType(index, filter.type);
    if (runtime.spec[index]?.frequency !== filter.frequency) runtime.setFilterFrequency(index, filter.frequency);
    if (runtime.spec[index]?.gain !== filter.gain) runtime.setFilterGain(index, filter.gain);
    if (runtime.spec[index]?.Q !== filter.Q) runtime.setFilterQ(index, filter.Q);
    if (runtime.spec[index]?.bypass !== filter.bypass) runtime.toggleBypass(index, filter.bypass);
  });
  return runtime;
};

window.secretPondGraphEq = Object.freeze({
  MAX_SECRET_POND_EQ_POINTS,
  SUPPORTED_SECRET_POND_TYPES,
  createRuntime,
  syncRuntime,
  toWeq8cSpec,
  toSecretPondEqPoints,
  fromSecretPondEqPoints,
});
