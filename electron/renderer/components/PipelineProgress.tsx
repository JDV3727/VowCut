import React from "react";
import { useJobStore, StageInfo } from "../store/jobStore";

const STAGES = ["ingest", "proxy", "align", "features", "music", "assemble", "export"] as const;
const STAGE_LABELS: Record<string, string> = {
  ingest:   "Ingest",
  proxy:    "Proxies",
  align:    "Alignment",
  features: "Features",
  music:    "Music Analysis",
  assemble: "Assembly",
  export:   "Export",
};

const StatusDot: React.FC<{ status: StageInfo["status"] }> = ({ status }) => {
  const colors: Record<string, string> = {
    idle:    "#444",
    pending: "#444",
    running: "#007aff",
    done:    "#30d158",
    error:   "#ff453a",
    skipped: "#6e6e73",
  };
  const isSpinning = status === "running";
  return (
    <span
      style={{
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: colors[status] ?? "#444",
        flexShrink: 0,
        animation: isSpinning ? "pulse 1s infinite" : "none",
      }}
    />
  );
};

const StageRow: React.FC<{ name: string; info: StageInfo }> = ({ name, info }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
    <StatusDot status={info.status} />
    <div style={{ flex: 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontSize: 13, color: "#fff" }}>{STAGE_LABELS[name] ?? name}</span>
        {info.status === "running" && info.progress >= 0 && (
          <span style={{ fontSize: 12, color: "#aaa" }}>
            {Math.round(info.progress * 100)}%
          </span>
        )}
      </div>
      {info.status === "running" && info.progress >= 0 && (
        <div style={{ height: 3, background: "#333", borderRadius: 2 }}>
          <div
            style={{
              height: "100%",
              width: `${Math.max(0, Math.min(100, info.progress * 100))}%`,
              background: "#007aff",
              borderRadius: 2,
              transition: "width 0.3s ease",
            }}
          />
        </div>
      )}
      {info.detail && (
        <div style={{ fontSize: 11, color: "#888", marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {info.detail}
        </div>
      )}
      {info.warning && (
        <div style={{ fontSize: 11, color: "#ff9f0a", marginTop: 2 }}>
          ⚠ {info.warning}
        </div>
      )}
    </div>
  </div>
);

export const PipelineProgress: React.FC = () => {
  const { stages, overallStatus, error } = useJobStore();

  return (
    <div style={{ padding: "16px 0" }}>
      {STAGES.map((s) => (
        <StageRow key={s} name={s} info={stages[s]} />
      ))}

      {overallStatus === "error" && error && (
        <div style={{ marginTop: 12, padding: 10, background: "rgba(255,69,58,0.12)", borderRadius: 8, color: "#ff453a", fontSize: 13 }}>
          Error: {error}
        </div>
      )}

      {overallStatus === "done" && (
        <div style={{ marginTop: 12, color: "#30d158", fontWeight: 600, fontSize: 14 }}>
          Export complete!
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
};
