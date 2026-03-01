import React, { useEffect, useState } from "react";
import { gpuInfo, GpuInfoResponse } from "../api/backend";

export const GpuBadge: React.FC = () => {
  const [info, setInfo] = useState<GpuInfoResponse | null>(null);

  useEffect(() => {
    gpuInfo()
      .then(setInfo)
      .catch(() => setInfo({ detected: false, error: "Backend unavailable" }));
  }, []);

  if (!info) return null;

  const label = info.detected
    ? `GPU: ${info.hevc_encoder} / ${info.h264_encoder}`
    : `CPU only${info.error ? ` (${info.error})` : ""}`;

  const color = info.detected ? "#30d158" : "#ff9f0a";

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        color,
        background: "rgba(255,255,255,0.06)",
        borderRadius: 6,
        padding: "3px 8px",
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
      {label}
    </div>
  );
};
