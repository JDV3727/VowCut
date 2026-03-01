import React from "react";

export interface Settings {
  targetLengthS: number;
  exportMode: "fast_gpu" | "high_quality_cpu";
  musicVolume: number;
}

interface SettingsPanelProps {
  settings: Settings;
  onChange: (settings: Settings) => void;
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({ settings, onChange }) => {
  const update = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    onChange({ ...settings, [key]: value });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 13, color: "#aaa" }}>Target length (seconds)</span>
        <input
          type="number"
          min={30}
          max={900}
          step={10}
          value={settings.targetLengthS}
          onChange={(e) => update("targetLengthS", Number(e.target.value))}
          style={inputStyle}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 13, color: "#aaa" }}>Export mode</span>
        <select
          value={settings.exportMode}
          onChange={(e) => update("exportMode", e.target.value as Settings["exportMode"])}
          style={inputStyle}
        >
          <option value="fast_gpu">Fast (GPU)</option>
          <option value="high_quality_cpu">High quality (CPU)</option>
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 13, color: "#aaa" }}>
          Music volume: {Math.round(settings.musicVolume * 100)}%
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={settings.musicVolume}
          onChange={(e) => update("musicVolume", Number(e.target.value))}
          style={{ accentColor: "#007aff" }}
        />
      </label>
    </div>
  );
};

const inputStyle: React.CSSProperties = {
  background: "#2c2c2e",
  border: "1px solid #3a3a3c",
  borderRadius: 6,
  color: "#fff",
  padding: "6px 10px",
  fontSize: 14,
};
