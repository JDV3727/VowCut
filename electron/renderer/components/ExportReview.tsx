import React from "react";
import { useJobStore } from "../store/jobStore";

export const ExportReview: React.FC = () => {
  const { exportPath, warnings, overallStatus } = useJobStore();

  if (overallStatus !== "done") return null;

  const handleReveal = () => {
    if (exportPath) window.vowcut.revealInFinder(exportPath);
  };

  return (
    <div
      style={{
        marginTop: 24,
        padding: 16,
        background: "rgba(48,209,88,0.08)",
        border: "1px solid rgba(48,209,88,0.3)",
        borderRadius: 10,
      }}
    >
      <h3 style={{ margin: "0 0 8px", color: "#30d158", fontSize: 16 }}>
        Export ready
      </h3>

      {exportPath && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <span style={{ fontSize: 13, color: "#ccc", flex: 1, wordBreak: "break-all" }}>
            {exportPath}
          </span>
          <button onClick={handleReveal} style={btnStyle}>
            Show in Finder
          </button>
        </div>
      )}

      {warnings.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ fontSize: 13, color: "#ff9f0a", cursor: "pointer" }}>
            {warnings.length} warning{warnings.length !== 1 ? "s" : ""}
          </summary>
          <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: "#ccc" }}>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
};

const btnStyle: React.CSSProperties = {
  background: "#30d158",
  color: "#000",
  border: "none",
  borderRadius: 6,
  padding: "6px 12px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  flexShrink: 0,
};
