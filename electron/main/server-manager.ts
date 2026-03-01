/**
 * ServerManager: spawns the Python FastAPI backend as a child process
 * and reads the assigned port from its stdout line "PORT=<n>".
 */
import { ChildProcess, spawn } from "child_process";
import * as path from "path";
import * as fs from "fs";

const STARTUP_TIMEOUT_MS = 30_000;

export class ServerManager {
  private process: ChildProcess | null = null;
  private port: number | null = null;

  /**
   * Start the backend process. Resolves with the port once the backend
   * prints "PORT=<n>" to stdout. Rejects on timeout or early exit.
   */
  start(): Promise<number> {
    return new Promise((resolve, reject) => {
      const pythonPath = this._findPython();
      const backendEntry = this._findBackendEntry();

      console.log(`[ServerManager] Starting backend: ${pythonPath} ${backendEntry}`);

      this.process = spawn(pythonPath, [backendEntry], {
        env: { ...process.env },
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
        if (match) {
          clearTimeout(timer);
          this.port = parseInt(match[1], 10);
          console.log(`[ServerManager] Backend ready on port ${this.port}`);
          resolve(this.port);
        }
      });

      this.process.stderr!.on("data", (chunk: Buffer) => {
        // Forward backend logs to main process stderr for debugging
        process.stderr.write(`[backend] ${chunk.toString()}`);
      });

      this.process.on("exit", (code, signal) => {
        if (this.port === null) {
          clearTimeout(timer);
          reject(new Error(`Backend exited before PORT= with code ${code} signal ${signal}`));
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

  private _findBackendEntry(): string {
    // In production: resourcesPath/backend; in dev: relative to project root
    const prodPath = path.join(process.resourcesPath ?? "", "backend", "app.py");
    if (fs.existsSync(prodPath)) {
      return ["-m", "backend.app"].join(" "); // run as module
    }
    // Dev mode: run relative to project root
    const devRoot = path.join(__dirname, "..", "..", "..");
    return path.join(devRoot, "backend", "app.py");
  }
}
