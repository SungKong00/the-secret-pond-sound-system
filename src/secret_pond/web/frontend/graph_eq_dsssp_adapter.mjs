export const graphEqDisplayConfig = Object.freeze({
  minFreq: 20,
  maxFreq: 20000,
  minGain: -15,
  maxGain: 15,
  sampleRate: 48000,
});

export const supportedDssspTypes = Object.freeze(["LOWSHELF2", "PEAK", "HIGHSHELF2"]);

export const secretPondToDssspType = Object.freeze({
  low_shelf: "LOWSHELF2",
  bell: "PEAK",
  high_shelf: "HIGHSHELF2",
});

export const dssspToSecretPondType = Object.freeze({
  LOWSHELF1: "low_shelf",
  LOWSHELF2: "low_shelf",
  PEAK: "bell",
  HIGHSHELF1: "high_shelf",
  HIGHSHELF2: "high_shelf",
});

const lockedLowIds = new Set(["low", "legacy-low"]);
const lockedHighIds = new Set(["high", "legacy-high"]);

const clamp = (value, min, max) => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return min;
  return Math.min(max, Math.max(min, numericValue));
};

const normalizedSecretPondType = (type) => (
  Object.prototype.hasOwnProperty.call(secretPondToDssspType, type) ? type : "bell"
);

const isFirstPoint = (index) => Number(index) === 0;

const isLastPoint = (index, points) => (
  Array.isArray(points) &&
  points.length > 0 &&
  Number(index) === points.length - 1
);

export const isLockedEndpointPoint = (point, index = null, points = []) => (
  point?.type === "low_shelf" &&
    (lockedLowIds.has(point?.id) || isFirstPoint(index)) ||
  point?.type === "high_shelf" &&
    (lockedHighIds.has(point?.id) || isLastPoint(index, points))
);

export const displayFrequencyForPoint = (
  point,
  config = graphEqDisplayConfig,
  index = null,
  points = [],
) => {
  if (
    point?.type === "low_shelf" &&
    (lockedLowIds.has(point?.id) || isFirstPoint(index))
  ) {
    return config.minFreq;
  }
  if (
    point?.type === "high_shelf" &&
    (lockedHighIds.has(point?.id) || isLastPoint(index, points))
  ) {
    return config.maxFreq;
  }
  return clamp(point?.frequency_hz ?? point?.freq ?? 1000, config.minFreq, config.maxFreq);
};

export const frequencyToX = (frequencyHz, config = graphEqDisplayConfig) => {
  const minLog = Math.log10(config.minFreq);
  const maxLog = Math.log10(config.maxFreq);
  const clampedFrequency = clamp(frequencyHz, config.minFreq, config.maxFreq);
  return (Math.log10(clampedFrequency) - minLog) / (maxLog - minLog);
};

export const gainToY = (gainDb, config = graphEqDisplayConfig) => (
  (config.maxGain - clamp(gainDb, config.minGain, config.maxGain)) /
  (config.maxGain - config.minGain)
);

export const displayPositionForPoint = (
  point,
  config = graphEqDisplayConfig,
  index = null,
  points = [],
) => ({
  x: frequencyToX(displayFrequencyForPoint(point, config, index, points), config),
  y: gainToY(point?.gain_db ?? point?.gain ?? 0, config),
});

export const toDssspFilters = (points = [], config = graphEqDisplayConfig) => points.map((point, index) => {
  const type = normalizedSecretPondType(point?.type);
  return {
    id: String(point?.id || `point-${index + 1}`),
    type: secretPondToDssspType[type],
    freq: displayFrequencyForPoint(point, config, index, points),
    gain: clamp(point?.gain_db ?? point?.gain ?? 0, config.minGain, config.maxGain),
    q: clamp(point?.q ?? 1, 0.1, 18),
  };
});

export const toSecretPondPoints = (filters = [], previousPoints = []) => filters
  .map((filter, index) => {
    const previous = previousPoints[index] || {};
    const fallbackType = normalizedSecretPondType(previous.type);
    const type = dssspToSecretPondType[filter?.type] || fallbackType;
    const locked = isLockedEndpointPoint(previous, index, previousPoints);
    const previousFrequency = Number(previous.frequency_hz);
    const nextFrequency = locked && Number.isFinite(previousFrequency)
      ? previousFrequency
      : Math.round(clamp(filter?.freq ?? previous.frequency_hz ?? 1000, graphEqDisplayConfig.minFreq, graphEqDisplayConfig.maxFreq));

    return {
      id: String(previous.id || filter?.id || `point-${index + 1}`),
      type,
      frequency_hz: nextFrequency,
      gain_db: Number(clamp(filter?.gain ?? previous.gain_db ?? 0, graphEqDisplayConfig.minGain, graphEqDisplayConfig.maxGain).toFixed(1)),
      q: Number(clamp(filter?.q ?? previous.q ?? 1, 0.1, 18).toFixed(2)),
    };
  })
  .filter((point) => Object.prototype.hasOwnProperty.call(secretPondToDssspType, point.type));

export const fromDssspChangeEvent = (event = {}) => ({
  index: Number(event.index),
  ended: Boolean(event.ended),
  point: {
    type: dssspToSecretPondType[event.type] || "bell",
    frequency_hz: Math.round(clamp(event.freq ?? 1000, graphEqDisplayConfig.minFreq, graphEqDisplayConfig.maxFreq)),
    gain_db: Number(clamp(event.gain ?? 0, graphEqDisplayConfig.minGain, graphEqDisplayConfig.maxGain).toFixed(1)),
    q: Number(clamp(event.q ?? 1, 0.1, 18).toFixed(2)),
  },
});
