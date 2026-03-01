import { dialog, IpcMain, shell } from "electron";

export function registerIpcHandlers(ipcMain: IpcMain, backendPort: number): void {
  ipcMain.handle(
    "dialog:select-files",
    async (
      _event,
      options: {
        title?: string;
        filters?: { name: string; extensions: string[] }[];
        multiSelections?: boolean;
      }
    ) => {
      const props: ("openFile" | "multiSelections")[] = ["openFile"];
      if (options.multiSelections) props.push("multiSelections");

      const result = await dialog.showOpenDialog({
        title: options.title ?? "Select files",
        filters: options.filters ?? [{ name: "All Files", extensions: ["*"] }],
        properties: props,
      });
      return result.canceled ? [] : result.filePaths;
    }
  );

  ipcMain.handle("dialog:select-folder", async () => {
    const result = await dialog.showOpenDialog({
      properties: ["openDirectory"],
    });
    return result.canceled ? null : result.filePaths[0];
  });

  ipcMain.handle("dialog:save-file", async (_event, defaultPath?: string) => {
    const result = await dialog.showSaveDialog({
      defaultPath: defaultPath ?? "highlight.mp4",
      filters: [{ name: "MP4 Video", extensions: ["mp4"] }],
    });
    return result.canceled ? null : result.filePath;
  });

  ipcMain.handle("backend:get-port", () => backendPort);

  ipcMain.on("shell:reveal", (_event, filePath: string) => {
    shell.showItemInFolder(filePath);
  });
}
