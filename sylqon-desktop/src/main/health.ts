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

/**
 * GET `url` and parse the JSON body. Resolves `null` on any error (unreachable,
 * non-2xx, timeout, bad JSON) so callers can simply skip when the backend isn't
 * ready. Read-only; same http/https + timeout shape as `checkBackend`.
 */
export function fetchJson<T = any>(url: string, timeoutMs = 2500): Promise<T | null> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v: T | null) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    try {
      const lib = url.startsWith("https") ? https : http;
      const req = lib.get(url, (res) => {
        if (!res.statusCode || res.statusCode >= 400) {
          res.resume();
          return done(null);
        }
        let body = "";
        res.setEncoding("utf-8");
        res.on("data", (chunk) => {
          body += chunk;
        });
        res.on("end", () => {
          try {
            done(JSON.parse(body) as T);
          } catch {
            done(null);
          }
        });
      });
      req.setTimeout(timeoutMs, () => {
        req.destroy();
        done(null);
      });
      req.on("error", () => done(null));
    } catch {
      done(null);
    }
  });
}
