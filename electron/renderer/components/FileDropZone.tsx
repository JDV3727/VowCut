import React, { useCallback, useState } from "react";

interface FileDropZoneProps {
  label: string;
  accept?: string;
  multiple?: boolean;
  files: string[];
  onFiles: (paths: string[]) => void;
}

export const FileDropZone: React.FC<FileDropZoneProps> = ({
  label,
  accept,
  multiple = false,
  files,
  onFiles,
}) => {
  const [dragging, setDragging] = useState(false);

  const handleBrowse = useCallback(async () => {
    const selected = await window.vowcut.selectFiles({
      title: label,
      filters: accept
        ? [{ name: label, extensions: accept.split(",").map((e) => e.trim().replace(".", "")) }]
        : undefined,
      multiSelections: multiple,
    });
    if (selected.length > 0) onFiles(selected);
  }, [label, accept, multiple, onFiles]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const paths = Array.from(e.dataTransfer.files).map((f) => f.path);
      if (paths.length > 0) onFiles(multiple ? paths : [paths[0]]);
    },
    [multiple, onFiles]
  );

  return (
    <div
      onClick={handleBrowse}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      style={{
        border: `2px dashed ${dragging ? "#007aff" : "#555"}`,
        borderRadius: 8,
        padding: "24px 16px",
        textAlign: "center",
        cursor: "pointer",
        background: dragging ? "rgba(0,122,255,0.08)" : "transparent",
        transition: "all 0.15s",
      }}
    >
      {files.length === 0 ? (
        <p style={{ margin: 0, color: "#aaa" }}>
          {label} — drop here or click to browse
        </p>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
          {files.map((f) => (
            <li key={f} style={{ fontSize: 13, color: "#ddd", wordBreak: "break-all" }}>
              {f.split("/").pop()}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
