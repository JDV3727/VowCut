/**
 * Zustand store for job state.
 */
import { create } from "zustand";
import { ProgressEvent } from "../api/backend";
import { StageStatus } from "../types/manifest";

export interface StageInfo {
  status: StageStatus | "idle";
  progress: number;
  detail: string;
  warning: string | null;
}

const STAGES = ["ingest", "proxy", "align", "features", "music", "assemble", "export"] as const;
type StageName = (typeof STAGES)[number];

export interface JobState {
  projectId: string | null;
  jobId: string | null;
  projectDir: string | null;
  overallStatus: "idle" | "running" | "done" | "error";
  error: string | null;
  stages: Record<StageName, StageInfo>;
  exportPath: string | null;
  warnings: string[];

  // Actions
  setProject(projectId: string, projectDir: string): void;
  setJobId(jobId: string): void;
  applyProgress(event: ProgressEvent): void;
  setExportPath(path: string): void;
  reset(): void;
}

const defaultStages = (): Record<StageName, StageInfo> =>
  Object.fromEntries(
    STAGES.map((s) => [s, { status: "idle", progress: 0, detail: "", warning: null }])
  ) as Record<StageName, StageInfo>;

export const useJobStore = create<JobState>((set, get) => ({
  projectId: null,
  jobId: null,
  projectDir: null,
  overallStatus: "idle",
  error: null,
  stages: defaultStages(),
  exportPath: null,
  warnings: [],

  setProject: (projectId, projectDir) =>
    set({ projectId, projectDir, overallStatus: "idle", error: null, stages: defaultStages() }),

  setJobId: (jobId) => set({ jobId, overallStatus: "running" }),

  applyProgress: (event) => {
    if (event.step === "pipeline") {
      if (event.status === "done") {
        set({ overallStatus: "done" });
      } else if (event.status === "error") {
        set({ overallStatus: "error", error: event.detail });
      }
      return;
    }

    if (event.step === "heartbeat") return;

    const stage = event.step as StageName;
    if (!STAGES.includes(stage)) return;

    set((state) => {
      const stageInfo: StageInfo = {
        status: event.status === "done"
          ? "done"
          : event.status === "error"
          ? "error"
          : "running",
        progress: event.progress,
        detail: event.detail,
        warning: event.warning,
      };

      const warnings =
        event.warning
          ? [...state.warnings, event.warning]
          : state.warnings;

      return {
        stages: { ...state.stages, [stage]: stageInfo },
        warnings,
      };
    });
  },

  setExportPath: (path) => set({ exportPath: path }),

  reset: () =>
    set({
      projectId: null,
      jobId: null,
      projectDir: null,
      overallStatus: "idle",
      error: null,
      stages: defaultStages(),
      exportPath: null,
      warnings: [],
    }),
}));
