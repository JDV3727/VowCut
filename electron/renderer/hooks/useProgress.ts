/**
 * SSE subscription hook.
 * Subscribes to backend progress events and updates the job store.
 */
import { useEffect, useRef } from "react";
import { subscribeToEvents } from "../api/backend";
import { useJobStore } from "../store/jobStore";

export function useProgress(jobId: string | null): void {
  const applyProgress = useJobStore((s) => s.applyProgress);
  const unsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!jobId) return;

    unsubRef.current = subscribeToEvents(
      jobId,
      (event) => applyProgress(event),
      (err) => {
        console.error("[SSE] Connection error:", err);
      }
    );

    return () => {
      unsubRef.current?.();
      unsubRef.current = null;
    };
  }, [jobId, applyProgress]);
}
