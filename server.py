#!/usr/bin/env python3
"""
Vitals — a workload map, not a process list.

Most system monitors show you PIDs. Nobody thinks in PIDs. Vitals groups every
process under the thing a human actually named (an app, a container, an agent,
a browser instance), then reports load in both units people need:
percent of machine and percent of one core.

  python3 server.py            # http://127.0.0.1:8791
  python3 server.py --port N
"""

import argparse
import collections
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import browsers

HZ = os.sysconf("SC_CLK_TCK")
CORES = os.cpu_count() or 1
HERE = os.path.dirname(os.path.abspath(__file__))
LABELS_PATH = os.path.join(HERE, "labels.json")

SAMPLE_S = 2.0
HISTORY_N = 150          # 5 minutes at 2s


# ---------------------------------------------------------------- labels ----

DEFAULT_LABELS = {
    "apps": {
        "com.brave.Browser": "Brave",
        "md.obsidian.Obsidian": "Obsidian",
        "com.discordapp.Discord": "Discord",
        "org.localsend.localsend_app": "LocalSend",
        "org.telegram.desktop": "Telegram",
        "us.zoom.Zoom": "Zoom",
        "com.spotify.Client": "Spotify",
        "com.slack.Slack": "Slack",
        "org.mozilla.Thunderbird": "Thunderbird",
    },
    "units": {
        "segundo.service": "Hermes agent · Scribe",
        "headroom-proxy.service": "Headroom proxy",
        "hermes-gateway.service": "Hermes gateway",
    },
    "containers": {
        "jellyfin": "Jellyfin (media server)",
        "mc-server": "Minecraft server",
    },
    "commands": {
        "cinnamon": "Cinnamon desktop",
        "nextcloud": "Nextcloud desktop",
        "thunderbird": "Thunderbird",
        "gnome-system-mo": "GNOME System Monitor",
        "steamwebhelper": "Steam",
        "1password": "1Password",
        "op": "1Password CLI",
        "mullvad-gui": "Mullvad VPN",
        "vibe_typer.app": "Vibe Typer",
        "python3": "Python",
        "java": "Java",
        "node": "Node",
        "ollama": "Ollama",
        "caddy": "Caddy",
        "dockerd": "Docker daemon",
        "containerd": "Docker runtime",
        "localsend": "LocalSend",
        "Discord": "Discord",
        "chromium": "Chromium",
        "brave": "Brave",
        "hermes": "Hermes",
        "Hermes": "Hermes desktop",
    },
}


def load_labels():
    labels = json.loads(json.dumps(DEFAULT_LABELS))
    try:
        with open(LABELS_PATH) as f:
            extra = json.load(f)
        for k, v in extra.items():
            labels.setdefault(k, {}).update(v)
    except (OSError, ValueError):
        pass
    return labels


LABELS = load_labels()


def prettify(s):
    s = re.sub(r"^(com|org|net|io|md|us|app)\.", "", s)
    s = s.replace("._app", "").replace("-", " ")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = s.replace(".", " ").strip()
    return " ".join(w.capitalize() if w.islower() else w for w in s.split())


def name_for_flatpak(app_id):
    if app_id in LABELS["apps"]:
        return LABELS["apps"][app_id]
    return prettify(app_id)


def name_for_unit(unit):
    if unit in LABELS["units"]:
        return LABELS["units"][unit]
    return prettify(re.sub(r"\.(service|scope|socket|timer)$", "", unit))


def name_for_cmd(comm):
    if comm in LABELS["commands"]:
        return LABELS["commands"][comm]
    return prettify(comm) if comm else "unknown"


# ------------------------------------------------------------- /proc read ---

def read_cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def read_stat(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            r = f.read().rsplit(")", 1)[1].split()
        return {
            "ppid": int(r[1]),
            "ticks": int(r[11]) + int(r[12]),
            "start": int(r[19]),
        }
    except (OSError, IndexError, ValueError):
        return None


def read_comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def read_rss_kb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def read_cgroup(pid):
    """Return the cgroup v2 path (the 0:: line), falling back to the longest path."""
    best = ""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                parts = line.strip().split(":", 2)
                if len(parts) != 3:
                    continue
                path = parts[2]
                if parts[0] == "0":
                    return path
                if len(path) > len(best):
                    best = path
    except OSError:
        pass
    return best


def read_threads(pid, top=8):
    out = []
    base = f"/proc/{pid}/task"
    try:
        for t in os.listdir(base):
            try:
                r = open(f"{base}/{t}/stat").read().rsplit(")", 1)[1].split()
                out.append({"tid": t, "name": open(f"{base}/{t}/comm").read().strip(),
                            "ticks": int(r[11]) + int(r[12])})
            except (OSError, IndexError, ValueError):
                pass
    except OSError:
        pass
    out.sort(key=lambda x: -x["ticks"])
    return out[:top]


SCOPED = re.compile(r"chromium-headless/(scoped_dir\w+)")
PORT_RE = re.compile(r"--remote-debugging-port=(\d+)")
FLATPAK_SCOPE = re.compile(r"app-flatpak-([\w.\-]+?)-\d+\.scope$")
DOCKER_SCOPE = re.compile(r"docker-([0-9a-f]{64})\.scope$")
UNIT_SCOPE = re.compile(r"([\w@.\-]+\.(?:service|scope))$")


GENERIC_ROOTS = {"systemd", "init", "lightdm", "gnome-session", "cinnamon-session",
                 "xfce4-session", "bash", "sh", "zsh", "dash", "dbus-daemon",
                 "dbus-broker", "gdm-session-wor", "gnome-shell", "sddm", "startx",
                 "xinit", "user@1000.service", "session-c", "gnome-terminal-"}
INTERPRETERS = {"python3", "python", "node", "java", "bash", "sh", "perl", "ruby", "op"}


def is_generic(comm):
    """comm is truncated to 15 chars by the kernel, so compare on a prefix."""
    if not comm:
        return False
    for g in GENERIC_ROOTS:
        if comm.startswith(g[:15]) or g.startswith(comm[:15]):
            return True
    return False


def st_ppid_is_kernel(ppid):
    """Kernel threads are children of kthreadd (pid 2)."""
    return ppid == 2


def derive_name(comm, cmd):
    """A human name for a loose process, preferring the script/app it runs."""
    if comm in INTERPRETERS and cmd:
        for tok in cmd.split()[1:]:
            if tok.startswith("-"):
                continue
            base = os.path.basename(tok)
            if base and "." in base:
                return prettify(base.rsplit(".", 1)[0].replace("_", " ").replace("-", " "))
            break
    return name_for_cmd(comm)


class Sampler(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="vitals-sampler")
        self.lock = threading.Lock()
        self.prev = {}
        self.pid_cpu = {}
        self.meta = {}           # pid -> (start, comm, cmdline, cgroup) cached
        self.containers = {}     # full cid -> (name, image)
        self.windows = collections.defaultdict(list)   # pid -> [titles]
        self.ports = collections.defaultdict(list)     # pid -> [ports]
        self.history = collections.deque(maxlen=HISTORY_N)
        self.latest = {"workloads": [], "flags": [], "t": 0}
        self.self_pid = os.getpid()
        self.self_cost = 0.0
        self.watcher = browsers.BrowserWatcher()

    # -- external inventories -------------------------------------------
    def refresh_containers(self):
        try:
            out = subprocess.run(
                ["docker", "ps", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"],
                capture_output=True, text=True, timeout=4).stdout
            self.containers = {l.split("\t")[0]: (l.split("\t")[1], l.split("\t")[2])
                               for l in out.splitlines() if l.count("\t") >= 2}
        except (OSError, subprocess.SubprocessError):
            pass

    def refresh_windows(self):
        wins = collections.defaultdict(list)
        try:
            out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=4).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            wid, title = parts[0], parts[3]
            try:
                pr = subprocess.run(["xprop", "-id", wid, "_NET_WM_PID"],
                                    capture_output=True, text=True, timeout=2).stdout
                pid = int(pr.rsplit(" ", 1)[-1].strip())
            except (OSError, subprocess.SubprocessError, ValueError):
                pid = 0
            if pid > 2:
                wins[pid].append(title)
        self.windows = wins

    def refresh_ports(self):
        ports = collections.defaultdict(list)
        try:
            out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True, timeout=4).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines()[1:]:
            m = re.search(r":(\d+)\s.*pid=(\d+)", line)
            if m:
                ports[int(m.group(2))].append(int(m.group(1)))
        self.ports = ports

    # -- classification --------------------------------------------------
    def classify(self, pid, comm, cmd, cgroup, ppid):
        """Return (workload_key, workload_name, role, extra)."""
        if pid == self.self_pid or "vitals/server.py" in cmd:
            return "vitals", "Vitals (this monitor)", "monitor", {}

        if "chromium-headless" in cmd:
            m = SCOPED.search(cmd)
            inst = m.group(1) if m else "instance"
            p = PORT_RE.search(cmd)
            role = "headless browser"
            if "--type=gpu-process" in cmd:
                role = "gpu"
            elif "--type=renderer" in cmd:
                role = "renderer"
            return "headless", "Headless browser automation", role, {"instance": inst, "port": p.group(1) if p else ""}

        m = DOCKER_SCOPE.search(cgroup)
        if m:
            entry = self.containers.get(m.group(1))
            if entry:
                return f"docker:{entry[0]}", f"{entry[0]} · container", "container", {"image": entry[1]}
            return f"docker:{m.group(1)[:12]}", f"container {m.group(1)[:12]}", "container", {}

        m = FLATPAK_SCOPE.search(cgroup)
        if m:
            app = m.group(1)
            name = name_for_flatpak(app)
            role = "app"
            if "--type=gpu-process" in cmd:
                role = "gpu"
            elif "--type=renderer" in cmd:
                role = "tab renderer"
            elif "--type=utility" in cmd:
                u = re.search(r"--utility-sub-type=[\w.]+\.([\w]+)", cmd)
                role = (u.group(1) if u else "utility").lower()
            elif "--type=browser" in cmd or "--type=" not in cmd:
                role = "main"
            extra = {"app_id": app}
            if role in ("tab renderer", "utility", "video_captureservice"):
                th = set(t["name"] for t in read_threads(pid, 30))
                if {"WebRTC_Signalin", "WebRTC_W_and_N"} & th or "VideoFrameCompo" in th:
                    role = "call (WebRTC)"
                    extra["media"] = True
            return f"app:{app}", name, role, extra

        m = UNIT_SCOPE.search(cgroup)
        if m and "app-" not in cgroup and not re.match(r"(session-[\w]+|init)\.scope$", m.group(1)):
            unit = m.group(1)
            if "hermes" in cmd:
                prof = re.search(r"-p[ =](\w+)", cmd)
                sub = "gateway" if "gateway" in cmd else (prof.group(1) if prof else "session")
                return f"agents:{unit}", f"Hermes agent · {sub}", "agent", {"unit": unit}
            return f"unit:{unit}", name_for_unit(unit), "service", {"unit": unit}

        if "hermes" in cmd or comm in ("hermes", "Hermes"):
            prof = re.search(r"-p[ =](\w+)", cmd)
            sub = "gateway" if "gateway" in cmd else (prof.group(1).capitalize() if prof else "session")
            # each chat session is its own thing: key it on its root process
            root, guard = pid, 0
            while guard < 24:
                st = self.meta.get(root)
                if not st or not st.get("ppid") or st["ppid"] in (1, 0):
                    break
                root = st["ppid"]
                guard += 1
            suffix = "" if sub == "gateway" else f":{root}"
            return f"agents:{sub.lower()}{suffix}", f"Hermes agent · {sub}", "agent", {"root": root}

        if st_ppid_is_kernel(ppid) or comm.startswith(("kworker", "ksoftirqd", "migration", "rcu_",
                                                      "kthreadd", "kcompactd", "kswapd", "jbd2/")):
            return "kernel", "Kernel", "kernel", {}

        # fall back to the top-most ancestor below init: that is the "app"
        root, guard = pid, 0
        while guard < 24:
            st = self.meta.get(root)
            if not st or not st.get("ppid") or st["ppid"] in (1, 0):
                break
            if st["ppid"] == 2:
                break
            root = st["ppid"]
            guard += 1
        root_comm = read_comm(root) or comm
        if is_generic(root_comm):
            # a generic parent is not an identity: name the process itself
            return f"cmd:{comm}", derive_name(comm, cmd), "process", {}
        return f"proc:{root}", name_for_cmd(root_comm), "process", {"root": root}

    # -- one sample -------------------------------------------------------
    def sample(self):
        t0 = time.time()
        now = time.time()
        up = float(open("/proc/uptime").read().split()[0])
        cur = {}
        for d in os.scandir("/proc"):
            if not d.name.isdigit():
                continue
            pid = int(d.name)
            st = read_stat(pid)
            if not st:
                continue
            cur[pid] = st
            cached = self.meta.get(pid)
            if not cached or cached["start"] != st["start"]:
                self.meta[pid] = {
                    "start": st["start"], "comm": read_comm(pid),
                    "cmd": read_cmdline(pid), "cgroup": read_cgroup(pid),
                    "ppid": st["ppid"], "rss": read_rss_kb(pid),
                }
            self.meta[pid]["ppid"] = st["ppid"]

        dt = max(0.2, now - (self.latest.get("t") or now))
        workloads = {}
        total_ticks = 0.0
        pid_cpu = {}
        pid_key = {}
        for pid, st in cur.items():
            prev = self.prev.get(pid)
            if not prev:
                continue
            pct = max(0.0, (st["ticks"] - prev) / HZ / dt * 100)
            pid_cpu[pid] = pct
            total_ticks += pct
            m = self.meta[pid]
            key, name, role, extra = self.classify(pid, m["comm"], m["cmd"], m["cgroup"], st["ppid"])
            pid_key[pid] = key
            w = workloads.setdefault(key, {
                "key": key, "name": name, "cpu": 0.0, "rss": 0, "procs": 0,
                "age_h": 9e9, "pids": [], "roles": collections.Counter(),
                "instances": set(), "flags": set(),
                "inst_cpu": collections.Counter(), "inst_port": {},
                "inst_age": {},
            })
            w["cpu"] += pct
            w["rss"] += m["rss"]
            w["procs"] += 1
            w["age_h"] = min(w["age_h"], (up - m["start"] / HZ) / 3600)
            w["roles"][role] += pct
            w["pids"].append(pid)
            if extra.get("instance"):
                w["instances"].add(extra["instance"])
                w["inst_cpu"][extra["instance"]] += pct
                this_age = (up - m["start"] / HZ) / 3600
                w["inst_age"][extra["instance"]] = min(
                    w["inst_age"].get(extra["instance"], 9e9), this_age)
                if extra.get("port"):
                    w["inst_port"][str(extra["port"])] = extra["instance"]
            if "headless" == key and st["ppid"] == 1 and w["age_h"] > 1:
                w["flags"].add("leaked")
            if role == "call (WebRTC)" and pct > 25:
                w["flags"].add("on a call")

        # ---- browser layer: per-tab accounting ---------------------------
        # CDP is the expensive part; poll it every other sample.
        bdt = now - getattr(self, "last_browser_ts", 0)
        if bdt >= 4.0:
            ports = self.watcher.discover()
            browser = self.watcher.poll(bdt, ports) if ports else {}
            self.last_browser_ts = now
        else:
            browser = self.watcher.last

        self.prev = {pid: st["ticks"] for pid, st in cur.items()}
        self.pid_cpu = pid_cpu
        self.meta = {pid: v for pid, v in self.meta.items() if pid in cur}

        total_busy = total_ticks / 100.0
        self.self_cost = next((w["cpu"] for w in workloads.values() if w["key"] == "vitals"), 0.0)
        out = []
        tabs_flat = []
        hist = list(self.history)[-60:]
        for w in workloads.values():
            w["age_h"] = 0 if w["age_h"] > 8e8 else w["age_h"]
            tabs, tab_cpu, verdict = [], 0.0, ""
            for port, res in browser.items():
                owner = [p for p in res.get("procs", {}) if pid_key.get(p) == w["key"]]
                if not owner:
                    continue
                inst = w["inst_port"].get(str(port), "")
                for t in res.get("tabs", []):
                    tab_cpu += t["task_pct"] / 100
                    tabs.append({**t, "port": port, "instance": inst,
                                 "instance_age": round(w["inst_age"].get(inst, 0), 1),
                                 "proc_cores": round(sum(
                                     v["cpu"] for k, v in res.get("procs", {}).items()
                                     if pid_key.get(k) == w["key"]) / 100, 2)})
            tabs.sort(key=lambda t: -t["task_pct"])
            w_cores = w["cpu"] / 100.0
            if tabs:
                if w_cores - tab_cpu > 0.5 and tab_cpu < w_cores * 0.4:
                    verdict = (f"pages are idle ({tab_cpu:.2f} cores of page work) — "
                               f"{w_cores - tab_cpu:.2f} cores burned by browser internals "
                               f"(compositor / raster / media), not by a tab")
                elif tab_cpu > 0.2:
                    verdict = f"page work: {tab_cpu:.2f} cores across {len(tabs)} tab(s)"
            else:
                verdict = ""
            inst_detail = []
            for inst, cpu in w["inst_cpu"].most_common(12):
                inst_detail.append({
                    "instance": inst, "cpu": round(cpu / 100, 2),
                    "port": next((p for p, i in w["inst_port"].items() if i == inst), ""),
                    "tab": next((t["title"] for t in tabs if t.get("instance") == inst), ""),
                    "url": next((t["url"] for t in tabs if t.get("instance") == inst), ""),
                })
            for t in tabs:
                tabs_flat.append({"browser": w["name"], "key": w["key"], **t})
            out.append({
                "key": w["key"], "name": w["name"],
                "cpu": round(w["cpu"] / 100, 2),
                "pct": round(w["cpu"] / (CORES * 100) * 100, 1),
                "rss_mb": round(w["rss"] / 1024),
                "procs": w["procs"],
                "age_h": round(w["age_h"], 1),
                "instances": len(w["instances"]),
                "roles": {k: round(v / 100, 2) for k, v in w["roles"].most_common(6) if v > 0},
                "flags": sorted(w["flags"]),
                "tabs": tabs[:20],
                "verdict": verdict,
                "instances_detail": inst_detail,
                "has_cdp": bool(tabs),
                "series": [round(h.get(w["key"], 0.0), 2) for _, h in hist],
            })
        out.sort(key=lambda x: -x["cpu"])
        tabs_flat.sort(key=lambda t: -t["task_pct"])
        flags = [{"key": w["key"], "name": w["name"], "flag": f, "cpu": w["cpu"]}
                 for w in out for f in w["flags"]]
        browsers_seen = [{"port": p, "tabs": len(r.get("tabs", [])),
                          "error": r.get("error", ""),
                          "name": next((w["name"] for w in out
                                        if any(t.get("port") == p for t in w.get("tabs", []))), "")
                          } for p, r in browser.items()]
        with self.lock:
            self.history.append((now, {w["key"]: w["cpu"] for w in out}))
            self.latest = {
                "t": now, "cores": CORES, "host": socket.gethostname(),
                "total_busy": round(total_busy, 2),
                "total_pct": round(total_busy / CORES * 100),
                "workloads": out, "flags": flags, "tabs": tabs_flat[:40],
                "browsers": sorted(browsers_seen, key=lambda b: b["port"]),
                "brave_cdp": any(b["port"] == 9222 for b in browsers_seen),
                "self_cost": round(self.self_cost / 100, 2),
                "sample_ms": round((time.time() - t0) * 1000),
            }
        return self.latest

    def detail(self, key):
        with self.lock:
            hist = list(self.history)
        up = float(open("/proc/uptime").read().split()[0])
        procs = []
        for pid, m in self.meta.items():
            k, name, role, extra = self.classify(pid, m["comm"], m["cmd"], m["cgroup"], m["ppid"])
            if k != key:
                continue
            procs.append({
                "pid": pid, "role": role, "rss_mb": round(m["rss"] / 1024),
                "cpu": round(getattr(self, "pid_cpu", {}).get(pid, 0.0) / 100, 2),
                "age_h": round((up - m["start"] / HZ) / 3600, 1),
                "cmd": m["cmd"][:400], "cgroup": m["cgroup"],
                "windows": self.windows.get(pid, []),
                "ports": sorted(set(self.ports.get(pid, []))),
                "extra": extra,
                "threads": read_threads(pid, 6),
            })
        procs.sort(key=lambda p: (-p["cpu"], -p["rss_mb"]))
        series = []
        if hist:
            keys = [k for _, h in hist for k in h]
            if key in keys:
                series = [round(h.get(key, 0.0), 2) for _, h in hist]
        return {"key": key, "processes": procs, "series": series[-120:]}

    def run(self):
        self.refresh_containers()
        last_cont = last_win = last_port = 0
        while True:
            try:
                if time.time() - last_cont > 20:
                    self.refresh_containers(); last_cont = time.time()
                if time.time() - last_win > 12:
                    self.refresh_windows(); last_win = time.time()
                if time.time() - last_port > 10:
                    self.refresh_ports(); last_port = time.time()
                self.sample()
            except Exception as exc:                      # never die mid-flight
                print("sample error:", exc, flush=True)
            time.sleep(SAMPLE_S)


SAMPLER = Sampler()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self._send(f.read(), "text/html; charset=utf-8")
            except OSError:
                return self._send("index.html missing", "text/plain", 500)
        if u.path == "/api/snapshot":
            with SAMPLER.lock:
                return self._send(json.dumps(SAMPLER.latest))
        if u.path == "/api/detail":
            key = parse_qs(u.query).get("key", [""])[0]
            if not key:
                return self._send('{"error":"key required"}', code=400)
            return self._send(json.dumps(SAMPLER.detail(key)))
        return self._send("not found", "text/plain", 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("VITALS_PORT", 8791)))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    SAMPLER.start()
    time.sleep(1.2)
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno == 98:
            print(f"Vitals: port {args.port} is already taken. Probing it…", flush=True)
            try:
                with urllib.request.urlopen(
                        f"http://{args.host}:{args.port}/api/snapshot", timeout=3) as r:
                    if r.status == 200 and "workloads" in r.read(400).decode("utf-8", "replace"):
                        print(f"Vitals is already running on http://{args.host}:{args.port} "
                              f"— nothing to do.", flush=True)
                        return
            except Exception:
                pass
            print(f"Vitals: something else owns port {args.port}. Try --port N.", flush=True)
            return
        raise
    print(f"Vitals on http://{args.host}:{args.port}  ({CORES} cores)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
