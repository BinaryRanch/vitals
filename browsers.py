"""
Browser layer for Vitals — per-TAB accounting, not per-PID.

A browser is the top layer of the operating system: it is where the work
actually happens. Chrome-family browsers speak CDP when started with
--remote-debugging-port, and that gives us the two halves of the answer:

  Performance.getMetrics   per-tab TaskDuration / ScriptDuration / heap / nodes
  SystemInfo.getProcessInfo per-process CPU (ids are real PIDs)

Join them and you can say: "this tab is idle, its GPU process is rasterizing
in a loop" — which is the signature of a browser eating a machine while
looking innocent.
"""

import time

import cdp

KNOWN_PORTS = [9222]                    # Brave/Chrome launched with the flag
SCAN_RANGE = range(9500, 9600)          # headless automation instances


class TabConn:
    def __init__(self, port):
        self.port = port
        self.ws = None
        self.sessions = {}               # target_id -> sessionId
        self.prev = {}                   # target_id -> {metric: value}
        self.prev_procs = {}             # pid -> cpuTime
        self.last_ok = 0.0
        self.error = ""

    def close(self):
        if self.ws:
            self.ws.close()
        self.ws = None
        self.sessions.clear()

    def connect(self):
        self.ws = cdp.WS(cdp.browser_ws(self.port), timeout=2.0)
        self.sessions.clear()
        self.prev.clear()
        self.prev_procs.clear()

    def poll(self, dt):
        """Return dict with tabs and per-process cpu for this browser."""
        if not self.ws:
            self.connect()
        targets = [t for t in cdp.targets(self.port) if t.get("type") == "page"]
        live = {t["id"] for t in targets}
        for tid in list(self.sessions):
            if tid not in live:
                self.sessions.pop(tid, None)
                self.prev.pop(tid, None)

        tabs = []
        for t in targets:
            tid = t["id"]
            try:
                if tid not in self.sessions:
                    self.sessions[tid] = self.ws.call(
                        "Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
                    self.ws.call("Performance.enable", {}, self.sessions[tid])
                s = self.sessions[tid]
                m = {x["name"]: x["value"]
                     for x in self.ws.call("Performance.getMetrics", {}, s)["metrics"]}
            except (RuntimeError, OSError, KeyError):
                self.sessions.pop(tid, None)
                continue
            p = self.prev.get(tid)
            self.prev[tid] = m
            delta = {k: (m.get(k, 0) - p.get(k, 0)) if p else 0 for k in
                     ("TaskDuration", "ScriptDuration", "LayoutDuration")}
            tabs.append({
                "id": tid,
                "title": (t.get("title") or "").strip() or "(untitled)",
                "url": t.get("url") or "",
                "task_pct": round(delta["TaskDuration"] / dt * 100, 1) if dt else 0,
                "script_share": round(delta["ScriptDuration"] / delta["TaskDuration"] * 100)
                if delta["TaskDuration"] > 0.0005 else 0,
                "heap_mb": round(m.get("JSHeapUsedSize", 0) / 1048576, 1),
                "nodes": int(m.get("Nodes", 0)),
            })

        procs = {}
        try:
            for p in self.ws.call("SystemInfo.getProcessInfo")["processInfo"]:
                pid, cpu = p.get("id"), p.get("cpuTime", 0.0)
                prev = self.prev_procs.get(pid)
                self.prev_procs[pid] = cpu
                procs[pid] = {
                    "type": p.get("type", ""),
                    "cpu": round((cpu - prev) / dt * 100, 1) if prev is not None and dt else 0.0,
                    "cpu_total_s": round(cpu, 1),
                }
        except (RuntimeError, OSError, KeyError):
            pass

        self.last_ok = time.time()
        return {"port": self.port, "tabs": tabs, "procs": procs}


class BrowserWatcher:
    """Polls every CDP-speaking browser on the box."""

    def __init__(self, extra_ports=()):
        self.conns = {}
        self.last = {}
        self.ports = list(KNOWN_PORTS) + list(extra_ports)
        self._scan = []
        self._scan_ts = 0.0

    def discover(self):
        """Find live CDP endpoints: configured ports + a bounded scan (cached)."""
        if time.time() - self._scan_ts < 20:
            return list(self._scan)
        found = []
        for port in self.ports:
            try:
                cdp.http_json(f"http://127.0.0.1:{port}/json/version", timeout=0.4)
                found.append(port)
            except Exception:
                pass
        for port in SCAN_RANGE:
            try:
                cdp.http_json(f"http://127.0.0.1:{port}/json/version", timeout=0.12)
                found.append(port)
            except Exception:
                pass
        self._scan, self._scan_ts = found, time.time()
        return list(found)

    def poll(self, dt, ports=None):
        ports = ports if ports is not None else self.discover()
        out = {}
        for port in ports:
            conn = self.conns.get(port)
            if not conn:
                conn = self.conns[port] = TabConn(port)
            try:
                out[port] = conn.poll(dt)
                conn.error = ""
            except Exception as exc:
                conn.error = str(exc)[:120]
                conn.close()
                self.conns.pop(port, None)
                out[port] = {"port": port, "tabs": [], "procs": {}, "error": conn.error}
        for port in list(self.conns):
            if port not in ports:
                self.conns[port].close()
                self.conns.pop(port, None)
        self.last = out
        return out
