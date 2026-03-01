/**
 * Orchestration hook: create project → run job → subscribe to SSE.
 */
import { useState, useCallback } from "react";
import { createProject, runJob } from "../api/backend";
import { useJobStore } from "../store/jobStore";
import { useProgress } from "./useProgress";

interface UseJobOptions {
  sourcePaths: string[];
  songPath?: string | null;
  targetLengthS?: number;
  exportMode?: string;
  musicVolume?: number;
}

interface UseJobReturn {
  start: (opts: UseJobOptions) => Promise<void>;
  isLoading: boolean;
  error: string | null;
}

export function useJob(): UseJobReturn {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { setProject, setJobId, jobId } = useJobStore();

  // Subscribe to SSE when we have a jobId
  useProgress(jobId);

  const start = useCallback(
    async ({
      sourcePaths,
      songPath = null,
      targetLengthS = 240,
      exportMode = "fast_gpu",
      musicVolume = 0.6,
    }: UseJobOptions) => {
      setIsLoading(true);
      setError(null);

      try {
        // 1. Create project
        const { project_id, project_dir } = await createProject({
          source_paths: sourcePaths,
          song_path: songPath,
        });
        setProject(project_id, project_dir);

        // 2. Start job
        const { job_id } = await runJob({
          project_id,
          export_mode: exportMode,
          target_length_s: targetLengthS,
          music_volume: musicVolume,
        });
        setJobId(job_id);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      } finally {
        setIsLoading(false);
      }
    },
    [setProject, setJobId]
  );

  return { start, isLoading, error };
}
