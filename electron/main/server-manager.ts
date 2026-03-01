/**
 * ServerManager: spawns the Python FastAPI backend as a child process
 * and reads the assigned port from its stdout line "PORT=<n>".
 */
import { BrowserWindow, ipcMain } from "electron";
import { ChildProcess, spawn } from "child_process";
import * as http from "http";
import * as path from "path";
import * as fs from "fs";

const STARTUP_TIMEOUT_MS = 30_000;
const HEALTH_POLL_INTERVAL_MS = 300;
const HEALTH_POLL_MAX_ATTEMPTS = 20;

export class ServerManager {
  private process: ChildProcess | null = null;
  private port: number | null = null;

  /**
   * Start the backend process. Resolves with the port once the backend
   * prints "PORT=<n>" to stdout AND the /health endpoint responds.
   * Rejects on timeout or early exit.
   */
  start(): Promise<number> {
    return new Promise((resolve, reject) => {
      const pythonPath = this._findPython();
      const backendArgs = this._findBackendArgs();
      const resourcesPath = process.resourcesPath ?? "";

      console.log(`[ServerManager] Starting backend: ${pythonPath} ${backendArgs.join(" ")}`);

      this.process = spawn(pythonPath, backendArgs, {
        env: {
          ...process.env,
          PYTHONPATH: resourcesPath,
          VOWCUT_RESOURCES_PATH: resourcesPath,
        },
        stdio: ["ignore", "pipe", "pipe"],
      });

      const timer = setTimeout(() => {
        this.stop();
        reject(new Error(`Backend did not print PORT= within ${STARTUP_TIMEOUT_MS}ms`));
      }, STARTUP_TIMEOUT_MS);

      let stdoutBuf = "";
      this.process.stdout!.on("data", (chunk: Buffer) => {
        stdoutBuf += chunk.toString();
        const match = stdoutBuf.match(/PORT=(\d+)/);
        if (match && this.port === null) {
          const port = parseInt(match[1], 10);
          this.port = port;
          console.log(`[ServerManager] PORT= detected: ${port}. Polling /health…`);
          this._awaitHealth(port)
            .then(() => {
              clearTimeout(timer);
              console.log(`[ServerManager] Backend healthy on port ${port}`);
              resolve(port);
            })
            .catch((err) => {
              clearTimeout(timer);
              this.stop();
              reject(err);
            });
        }
      });

      this.process.stderr!.on("data", (chunk: Buffer) => {
        // Forward backend logs to main process stderr for debugging
        process.stderr.write(`[backend] ${chunk.toString()}`);
      });

      this.process.on("exit", (code, signal) => {
        if (this.port === null) {
          // Exited before printing PORT= — startup failure
          clearTimeout(timer);
          reject(new Error(`Backend exited before PORT= with code ${code} signal ${signal}`));
        } else {
          // Post-startup crash: notify all open windows
          console.error(`[ServerManager] Backend crashed: code=${code} signal=${signal}`);
          BrowserWindow.getAllWindows().forEach((win) => {
            win.webContents.send("backend-crashed", { code, signal });
          });
        }
        console.log(`[ServerManager] Backend process exited: code=${code} signal=${signal}`);
      });

      this.process.on("error", (err) => {
        clearTimeout(timer);
        reject(err);
      });
    });
  }

  stop(): void {
    if (this.process && !this.process.killed) {
      this.process.kill("SIGTERM");
      this.process = null;
    }
  }

  getPort(): number | null {
    return this.port;
  }

  /**
   * Poll GET http://127.0.0.1:{port}/health until it returns 200 or we give up.
   */
  private _awaitHealth(port: number): Promise<void> {
    return new Promise((resolve, reject) => {
      let attempts = 0;

      const attempt = () => {
        attempts++;
        const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else if (attempts < HEALTH_POLL_MAX_ATTEMPTS) {
            setTimeout(attempt, HEALTH_POLL_INTERVAL_MS);
          } else {
            reject(new Error(`/health returned ${res.statusCode} after ${attempts} attempts`));
          }
        });
        req.on("error", () => {
          if (attempts < HEALTH_POLL_MAX_ATTEMPTS) {
            setTimeout(attempt, HEALTH_POLL_INTERVAL_MS);
          } else {
            reject(new Error(`Backend /health unreachable after ${attempts} attempts`));
          }
        });
        req.end();
      };

      attempt();
    });
  }

  private _findPython(): string {
    // Prefer bundled python, fall back to system
    const candidates = [
      path.join(process.resourcesPath ?? "", "python", "bin", "python3"),
      path.join(process.resourcesPath ?? "", "python", "python.exe"),
      "python3",
      "python",
    ];
    for (const p of candidates) {
      if (fs.existsSync(p)) return p;
    }
    return "python3";
  }

  private _findBackendArgs(): string[] {
    // In production: resourcesPath/backend exists → run as module
    const prodPath = path.join(process.resourcesPath ?? "", "backend", "app.py");
    if (fs.existsSync(prodPath)) {
      return ["-m", "backend.app"];
    }
    // Dev mode: run the app.py file directly
    const devRoot = path.join(__dirname, "..", "..", "..");
    return [path.join(devRoot, "backend", "app.py")];
  }
}
