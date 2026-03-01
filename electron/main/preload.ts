import { contextBridge, ipcRenderer } from "electron";

/**
 * Expose a safe subset of Electron APIs to the renderer process.
 * All communication goes through typed IPC channels.
 */
contextBridge.exposeInMainWorld("vowcut", {
  /** Open native file-picker and return selected paths. */
  selectFiles: (options: {
    title?: string;
    filters?: { name: string; extensions: string[] }[];
    multiSelections?: boolean;
  }): Promise<string[]> =>
    ipcRenderer.invoke("dialog:select-files", options),

  /** Open native folder-picker and return selected path. */
  selectFolder: (): Promise<string | null> =>
    ipcRenderer.invoke("dialog:select-folder"),

  /** Show native save dialog and return chosen path. */
  saveFile: (defaultPath?: string): Promise<string | null> =>
    ipcRenderer.invoke("dialog:save-file", defaultPath),

  /** Get the backend port assigned at startup. */
  getBackendPort: (): Promise<number> =>
    ipcRenderer.invoke("backend:get-port"),

  /** Open a path in Finder/Explorer. */
  revealInFinder: (filePath: string): void =>
    ipcRenderer.send("shell:reveal", filePath),
});

// Type declaration for the renderer
declare global {
  interface Window {
    vowcut: {
      selectFiles(options: {
        title?: string;
        filters?: { name: string; extensions: string[] }[];
        multiSelections?: boolean;
      }): Promise<string[]>;
      selectFolder(): Promise<string | null>;
      saveFile(defaultPath?: string): Promise<string | null>;
      getBackendPort(): Promise<number>;
      revealInFinder(filePath: string): void;
    };
    __BACKEND_PORT__: number;
  }
}
