import * as os from "os";
import * as path from "path";

/** Returns the default VowCut projects directory for the current OS. */
export function defaultProjectsDir(): string {
  return path.join(os.homedir(), "VowCut", "projects");
}

/** Sanitize a project name for use as a directory component. */
export function sanitizeName(name: string): string {
  return name.replace(/[^a-zA-Z0-9_\-]/g, "_").slice(0, 64);
}
