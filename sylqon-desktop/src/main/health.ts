import * as http from "http";
import * as https from "https";

/**
 * Is the Sylqon backend reachable at `url`? Resolves true on ANY HTTP response
 * (even a 404) — that proves the server is up. Read-only GET with a short
 * timeout. Shared by the window content loader and the backend auto-starter.
 */
export function checkBackend(url: string, timeoutMs = 2500): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (ok: boolean) => {
      if (!settled) {
        settled = true;
        resolve(ok);
      }
    };
    try {
      const lib = url.startsWith("https") ? https : http;
      const req = lib.get(url, (res) => {
        res.resume(); // drain and discard the body
        done(true);
      });
      req.setTimeout(timeoutMs, () => {
        req.destroy();
        done(false);
      });
      req.on("error", () => done(false));
    } catch {
      done(false);
    }
  });
}
