export const graphEqDisplayConfig = Object.freeze({
  minFreq: 20,
  maxFreq: 20000,
  minGain: -15,
  maxGain: 15,
  sampleRate: 48000,
});

export const fixedShelfDefaults = Object.freeze({
  low_shelf: Object.freeze({ frequency_hz: 80, gain_db: 0, q: 0.707 }),
  high_shelf: Object.freeze({ frequency_hz: 10000, gain_db: 0, q: 0.707 }),
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

const clamp = (value, min, max) => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return min;
  return Math.min(max, Math.max(min, numericValue));
};

const normalizedSecretPondType = (type) => (
  Object.prototype.hasOwnProperty.call(secretPondToDssspType, type) ? type : "bell"
);

export const isLockedEndpointPoint = (point) => (
  point?.type === "low_shelf" || point?.type === "high_shelf"
);

export const visualFrequencyForPoint = (
  point,
  config = graphEqDisplayConfig,
) => {
  if (point?.type === "low_shelf") return config.minFreq;
  if (point?.type === "high_shelf") return config.maxFreq;
  return displayFrequencyForPoint(point, config);
};

export const displayFrequencyForPoint = (
  point,
  config = graphEqDisplayConfig,
) => clamp(point?.frequency_hz ?? point?.freq ?? 1000, config.minFreq, config.maxFreq);

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
  x: frequencyToX(visualFrequencyForPoint(point, config, index, points), config),
  y: gainToY(point?.gain_db ?? point?.gain ?? 0, config),
});

export const toDssspFilters = (points = [], config = graphEqDisplayConfig) => points.map((point, index) => {
  const type = normalizedSecretPondType(point?.type);
  return {
    id: String(point?.id || `point-${index + 1}`),
    type: secretPondToDssspType[type],
    freq: displayFrequencyForPoint({ ...point, type }, config, index, points),
    gain: clamp(point?.gain_db ?? point?.gain ?? 0, config.minGain, config.maxGain),
    q: clamp(point?.q ?? fixedShelfDefaults[type]?.q ?? 1, 0.1, 18),
  };
});

export const toSecretPondPoints = (filters = [], previousPoints = []) => filters
  .map((filter, index) => {
    const previous = previousPoints[index] || {};
    const fallbackType = normalizedSecretPondType(previous.type);
    const type = dssspToSecretPondType[filter?.type] || fallbackType;
    const shelfDefault = fixedShelfDefaults[type] || {};
    const frequencySource = type === "bell"
      ? filter?.freq ?? previous.frequency_hz ?? 1000
      : previous.frequency_hz ?? shelfDefault.frequency_hz ?? 1000;
    const nextFrequency = Math.round(
      clamp(frequencySource, graphEqDisplayConfig.minFreq, graphEqDisplayConfig.maxFreq),
    );

    return {
      id: String(previous.id || filter?.id || `point-${index + 1}`),
      type,
      frequency_hz: nextFrequency,
      gain_db: Number(clamp(filter?.gain ?? previous.gain_db ?? 0, graphEqDisplayConfig.minGain, graphEqDisplayConfig.maxGain).toFixed(1)),
      q: Number(clamp(previous.q ?? filter?.q ?? shelfDefault.q ?? 1, 0.1, 18).toFixed(3)),
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
