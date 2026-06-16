"""LCU (League Client Update) API client.

Credentials come from the client lockfile or, failing that, from the
LeagueClientUx process command line. The LCU listens on localhost with a
self-signed cert, hence verify=False.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

import requests
import urllib3

from sylqon import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)


@dataclass
class LCUCredentials:
    port: int
    token: str


def _from_lockfile() -> LCUCredentials | None:
    candidates = list(config.LCU_LOCKFILE_CANDIDATES)
    if config.LCU_LOCKFILE_OVERRIDE:
        from pathlib import Path
        candidates.insert(0, Path(config.LCU_LOCKFILE_OVERRIDE))
    for path in candidates:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Format: LeagueClient:PID:port:password:https
        parts = raw.strip().split(":")
        if len(parts) >= 5:
            return LCUCredentials(port=int(parts[2]), token=parts[3])
    return None


def _from_process() -> LCUCredentials | None:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\" "
             "| Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    port = re.search(r"--app-port=(\d+)", out or "")
    token = re.search(r"--remoting-auth-token=([\w-]+)", out or "")
    if port and token:
        return LCUCredentials(port=int(port.group(1)), token=token.group(1))
    return None


class LCUClient:
    def __init__(self, creds: LCUCredentials) -> None:
        self.creds = creds
        self.base = f"https://127.0.0.1:{creds.port}"
        self.session = requests.Session()
        self.session.auth = ("riot", creds.token)
        self.session.verify = False

    @classmethod
    def connect(cls) -> "LCUClient | None":
        creds = _from_lockfile() or _from_process()
        if not creds:
            return None
        client = cls(creds)
        try:
            if client.get("/lol-summoner/v1/current-summoner").status_code == 200:
                log.info("Connected to LCU on port %d", creds.port)
                return client
        except requests.RequestException:
            pass
        return None

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 10)
        if "json" in kwargs:
            # The LCU rejects bodies over ~64KB with 413; requests' default
            # json serialization wastes bytes on separators and \uXXXX
            # escapes, which alone can push a large item-set collection over
            # the limit. Always send compact UTF-8.
            body = kwargs.pop("json")
            kwargs["data"] = json.dumps(
                body, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            kwargs.setdefault("headers", {}).setdefault("Content-Type", "application/json")
        return self.session.request(method, self.base + path, **kwargs)

    def get(self, path: str, **kw) -> requests.Response:
        return self._request("GET", path, **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self._request("POST", path, **kw)

    def put(self, path: str, **kw) -> requests.Response:
        return self._request("PUT", path, **kw)

    def patch(self, path: str, **kw) -> requests.Response:
        return self._request("PATCH", path, **kw)

    def get_json(self, path: str) -> dict | list | None:
        try:
            resp = self.get(path)
            return resp.json() if resp.status_code == 200 else None
        except (requests.RequestException, ValueError):
            return None

    def is_alive(self) -> bool:
        try:
            return self.get("/lol-gameflow/v1/gameflow-phase").status_code == 200
        except requests.RequestException:
            return False

    def current_summoner(self) -> dict | None:
        data = self.get_json("/lol-summoner/v1/current-summoner")
        return data if isinstance(data, dict) else None

    def gameflow_phase(self) -> str:
        try:
            resp = self.get("/lol-gameflow/v1/gameflow-phase")
            if resp.status_code == 200:
                return resp.json()
        except (requests.RequestException, ValueError):
            pass
        return "None"
