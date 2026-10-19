"""Minimal dependency-free CDP client (sync WebSocket) for Vitals."""
import base64
import json
import os
import socket
import struct
import urllib.request


class WS:
    def __init__(self, url, timeout=3.0):
        assert url.startswith("ws://")
        rest = url[5:]
        host_port, path = rest.split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("handshake closed")
            buf += chunk
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise OSError("handshake failed: " + buf[:120].decode("latin1"))
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0

    def send(self, obj):
        payload = json.dumps(obj).encode()
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        while True:
            b0, b1 = self._read_exact(2)
            opcode = b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(n)
            if opcode == 0x1:
                return json.loads(payload)
            if opcode == 0x8:
                raise OSError("ws closed by peer")
            if opcode == 0x9:          # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))

    def call(self, method, params=None, session_id=None):
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.send(msg)
        while True:
            resp = self.recv()
            if resp.get("id") == self._id:
                if "error" in resp:
                    raise RuntimeError(resp["error"].get("message"))
                return resp.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def http_json(url, timeout=2.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def targets(port, timeout=2.5):
    return http_json(f"http://127.0.0.1:{port}/json/list", timeout)


def browser_ws(port, timeout=2.5):
    return http_json(f"http://127.0.0.1:{port}/json/version", timeout)["webSocketDebuggerUrl"]

