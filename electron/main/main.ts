import { app, BrowserWindow, ipcMain, shell } from "electron";
import * as path from "path";
import { ServerManager } from "./server-manager";
import { registerIpcHandlers } from "./ipc-handlers";

let mainWindow: BrowserWindow | null = null;
let serverManager: ServerManager | null = null;

async function createWindow(backendPort: number): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: "VowCut",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Expose backend port to renderer via env
  mainWindow.webContents.executeJavaScript(
    `window.__BACKEND_PORT__ = ${backendPort};`
  );

  if (process.env.VOWCUT_DEV === "1") {
    await mainWindow.loadURL("http://localhost:3000");
    mainWindow.webContents.openDevTools();
  } else {
    await mainWindow.loadFile(
      path.join(__dirname, "../renderer/index.html")
    );
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  // Open external links in default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(async () => {
  serverManager = new ServerManager();

  try {
    const port = await serverManager.start();
    await createWindow(port);
    registerIpcHandlers(ipcMain, port);
  } catch (err) {
    console.error("Failed to start backend:", err);
    app.quit();
  }

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0 && serverManager) {
      const port = serverManager.getPort();
      if (port) {
        await createWindow(port);
        registerIpcHandlers(ipcMain, port);
      }
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  serverManager?.stop();
});
