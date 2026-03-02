/**
 * SSE subscription hook.
 * Subscribes to backend progress events and updates the job store.
 * When the pipeline finishes successfully, fetches artifacts to resolve
 * the export file path.
 */
import { useEffect, useRef } from "react";
import { getArtifacts, subscribeToEvents } from "../api/backend";
import { useJobStore } from "../store/jobStore";

export function useProgress(jobId: string | null): void {
  const applyProgress = useJobStore((s) => s.applyProgress);
  const setExportPath = useJobStore((s) => s.setExportPath);
  const projectId = useJobStore((s) => s.projectId);
  const unsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!jobId) return;

    unsubRef.current = subscribeToEvents(
      jobId,
      (event) => {
        applyProgress(event);
        if (event.step === "pipeline" && event.status === "done" && projectId) {
          getArtifacts(projectId)
            .then((artifacts) => {
              if (artifacts.export) setExportPath(artifacts.export);
            })
            .catch((err) => console.error("[artifacts] Failed to fetch:", err));
        }
      },
      (err) => {
        console.error("[SSE] Connection error:", err);
      }
    );

    return () => {
      unsubRef.current?.();
      unsubRef.current = null;
    };
  }, [jobId, applyProgress, setExportPath, projectId]);
}
