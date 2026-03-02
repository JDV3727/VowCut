import React, { useEffect, useState } from "react";
import { FileDropZone } from "./components/FileDropZone";
import { GpuBadge } from "./components/GpuBadge";
import { PipelineProgress } from "./components/PipelineProgress";
import { SettingsPanel, Settings } from "./components/SettingsPanel";
import { ExportReview } from "./components/ExportReview";
import { useJob } from "./hooks/useJob";
import { useJobStore } from "./store/jobStore";

const DEFAULT_SETTINGS: Settings = {
  targetLengthS: 240,
  exportMode: "fast_gpu",
  musicVolume: 0.6,
};

export const App: React.FC = () => {
  const [sources, setSources] = useState<string[]>([]);
  const [song, setSong] = useState<string[]>([]);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [showRerunSettings, setShowRerunSettings] = useState(false);

  const [crashError, setCrashError] = useState<string | null>(null);

  const { start, rerun, isLoading, error: startError } = useJob();
  const { overallStatus, reset } = useJobStore();

  useEffect(() => {
    return window.vowcut.onBackendCrashed(({ code, signal }) => {
      setCrashError(`Backend process crashed (code=${code} signal=${signal}). Please restart VowCut.`);
    });
  }, []);

  const isRunning = overallStatus === "running" || isLoading;
  const isDone = overallStatus === "done";

  const handleStart = async () => {
    if (sources.length === 0) {
      alert("Please select at least one source video.");
      return;
    }
    await start({
      sourcePaths: sources,
      songPath: song[0] ?? null,
      targetLengthS: settings.targetLengthS,
      exportMode: settings.exportMode,
      musicVolume: settings.musicVolume,
    });
  };

  const handleReset = () => {
    setSources([]);
    setSong([]);
    setSettings(DEFAULT_SETTINGS);
    setShowRerunSettings(false);
    reset();
  };

  const handleRerun = async () => {
    setShowRerunSettings(false);
    await rerun({
      targetLengthS: settings.targetLengthS,
      exportMode: settings.exportMode,
      musicVolume: settings.musicVolume,
    });
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#1c1c1e",
        color: "#fff",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif",
        padding: "32px 40px",
        boxSizing: "border-box",
      }}
    >
      {/* Backend crash banner */}
      {crashError && (
        <div
          style={{
            marginBottom: 20,
            padding: "12px 16px",
            background: "rgba(255,69,58,0.12)",
            border: "1px solid rgba(255,69,58,0.5)",
            borderRadius: 10,
            color: "#ff453a",
            fontSize: 14,
          }}
        >
          {crashError}
        </div>
      )}

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 32 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, letterSpacing: -0.5 }}>VowCut</h1>
          <p style={{ margin: "4px 0 0", color: "#666", fontSize: 14 }}>
            Local wedding highlight generator
          </p>
        </div>
        <GpuBadge />
      </div>

      {!isRunning && !isDone && (
        <>
          {/* File inputs */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
            <FileDropZone
              label="Source videos"
              accept=".mp4,.mov,.mxf,.avi"
              multiple
              files={sources}
              onFiles={setSources}
            />
            <FileDropZone
              label="Music track (optional)"
              accept=".mp3,.wav,.aac,.m4a"
              multiple={false}
              files={song}
              onFiles={setSong}
            />
          </div>

          {/* Settings toggle */}
          <button
            onClick={() => setShowSettings((v) => !v)}
            style={ghostBtn}
          >
            {showSettings ? "Hide settings" : "Settings"}
          </button>

          {showSettings && (
            <div style={{ marginTop: 16, padding: 16, background: "#2c2c2e", borderRadius: 10 }}>
              <SettingsPanel settings={settings} onChange={setSettings} />
            </div>
          )}

          {startError && (
            <p style={{ color: "#ff453a", marginTop: 12, fontSize: 13 }}>
              {startError}
            </p>
          )}

          <button
            onClick={handleStart}
            disabled={isLoading || sources.length === 0}
            style={{ ...primaryBtn, marginTop: 24 }}
          >
            {isLoading ? "Starting…" : "Generate Highlight"}
          </button>
        </>
      )}

      {(isRunning || isDone) && (
        <div style={{ marginBottom: 24 }}>
          <PipelineProgress />
          <ExportReview />

          {(isDone || overallStatus === "error") && (
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 10 }}>
              <button
                onClick={() => setShowRerunSettings((v) => !v)}
                style={ghostBtn}
                disabled={isLoading}
              >
                {showRerunSettings ? "Cancel re-run" : "Re-run with different settings"}
              </button>

              {showRerunSettings && (
                <div style={{ padding: 16, background: "#2c2c2e", borderRadius: 10 }}>
                  <SettingsPanel settings={settings} onChange={setSettings} />
                  {startError && (
                    <p style={{ color: "#ff453a", margin: "10px 0 0", fontSize: 13 }}>
                      {startError}
                    </p>
                  )}
                  <button
                    onClick={handleRerun}
                    disabled={isLoading}
                    style={{ ...primaryBtn, marginTop: 16 }}
                  >
                    {isLoading ? "Starting…" : "Re-generate Highlight"}
                  </button>
                </div>
              )}

              <button onClick={handleReset} style={ghostBtn}>
                New project
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const primaryBtn: React.CSSProperties = {
  background: "#007aff",
  color: "#fff",
  border: "none",
  borderRadius: 10,
  padding: "12px 28px",
  fontSize: 16,
  fontWeight: 600,
  cursor: "pointer",
  width: "100%",
};

const ghostBtn: React.CSSProperties = {
  background: "transparent",
  color: "#007aff",
  border: "1px solid rgba(0,122,255,0.4)",
  borderRadius: 8,
  padding: "7px 14px",
  fontSize: 13,
  cursor: "pointer",
};
