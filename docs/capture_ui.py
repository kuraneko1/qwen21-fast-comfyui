#!/usr/bin/env python3
"""Capture ComfyUI screenshots with headless Chrome over the DevTools protocol.

    python3 capture_ui.py out_dir [--url http://127.0.0.1:8188] [--workflow qwen21_fast_t2i]
                                  [--lang ja|en] [--suffix _ja] [--run] [--eval JS]

Writes <out_dir>/ui_empty<suffix>.png (ComfyUI as it opens), ui_workflow<suffix>.png (that
workflow loaded into the graph) and, with --run, ui_used<suffix>.png after actually generating an
image, so the screenshot shows the node in use (the result is drawn inside the Save Image node).
The screenshots committed in this repository are ui_workflow_<lang>.png (no --run) and
ui_used_<lang>.png (with --run).

Two details make --run work: the job is queued with the frontend's OWN client_id (read from
app.api.clientId, with a recorded websocket URL as fallback), because the UI only paints
results for its own client; and the canvas is asked to repaint once the job finishes.

--eval runs arbitrary JS in the page and prints the value (no screenshot) - handy for probing the
frontend, e.g. --eval '(async () => { const n = LiteGraph.createNode("Qwen21FastGenerate");
app.graph.add(n); return String(n.widgets.find(w => w.name === "control_after_generate").value); })()'

Standard library only: the CDP websocket is hand-rolled so this needs no pip installs. Chrome
comes from $CHROME (default /usr/bin/google-chrome).
"""
import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")
PORT = 9222


class WS:
    """Minimal text-only websocket client (RFC 6455), enough for CDP."""

    def __init__(self, url):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        assert b"101" in buf.split(b"\r\n")[0], buf[:200]
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.msg_id = 0

    def _recv_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send_text(self, text):
        payload = text.encode()
        header = bytearray([0x81])
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self):
        while True:
            b0, b1 = self._recv_exact(2)
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            data = self._recv_exact(length)
            if opcode == 0x9:  # ping
                continue
            if opcode in (0x1, 0x2):
                return data.decode("utf-8", "replace")

    def call(self, method, params=None, timeout=30):
        # The socket timeout has to cover the wait: an evaluate that polls for
        # a minute would otherwise die in _recv_exact at the 30 s default.
        prev = self.sock.gettimeout()
        self.sock.settimeout(max(timeout, 30) + 10)
        try:
            self.msg_id += 1
            mid = self.msg_id
            self.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = json.loads(self.recv_text())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})
            raise TimeoutError(method)
        finally:
            self.sock.settimeout(prev)


def http_json(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--workflow", default="qwen21_fast_t2i")
    ap.add_argument("--size", default="1500,950")
    ap.add_argument("--lang", default="en", choices=["en", "ja"],
                    help="UI language: Chrome's --lang decides the frontend locale")
    ap.add_argument("--suffix", default=None, help="output name suffix (default: _<lang>)")
    ap.add_argument("--run", action="store_true",
                    help="also queue the loaded workflow, wait for it, and screenshot the result")
    ap.add_argument("--eval", default=None, metavar="JS",
                    help="evaluate this JS in the page, print the value and exit (no screenshot)")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not http_json(f"{a.url}/system_stats")["system"]:
        sys.exit("ComfyUI is not answering on " + a.url)

    locale = "en_US.UTF-8" if a.lang == "en" else "ja_JP.UTF-8"
    env = {**os.environ, "LANG": locale, "LC_ALL": locale, "LANGUAGE": a.lang}
    profile = f"/tmp/cdp-comfyui-{a.lang}"
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={profile}", f"--lang={'en-US' if a.lang == 'en' else 'ja'}",
         "--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={a.size}",
         "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        for _ in range(30):
            try:
                targets = http_json(f"http://127.0.0.1:{PORT}/json/list")
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("chrome devtools endpoint never came up")

        ws = WS(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        # Keep the websocket URL as a fallback for older frontend versions where the
        # client_id was included in its query string.
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "(() => { const OW = window.WebSocket; window.__wsurls = [];"
            " window.WebSocket = function (u, p) {"
            "   try { window.__wsurls.push(String(u)); } catch (e) {}"
            "   return new OW(u, p); };"
            " window.WebSocket.prototype = OW.prototype; })();")})
        ws.call("Page.navigate", {"url": a.url})

        def wait_app(seconds=60):
            deadline = time.time() + seconds
            while time.time() < deadline:
                res = ws.call("Runtime.evaluate",
                              {"expression": "!!(window.app && window.app.graph)", "returnByValue": True})
                if res.get("result", {}).get("value"):
                    return True
                time.sleep(1)
            return False

        def shot(path):
            res = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=60)
            path.write_bytes(base64.b64decode(res["data"]))
            print("wrote", path, path.stat().st_size, "bytes")

        if not wait_app():
            sys.exit("ComfyUI frontend never finished booting")

        if a.eval:
            res = ws.call("Runtime.evaluate",
                          {"expression": a.eval, "awaitPromise": True, "returnByValue": True},
                          timeout=120)
            print(json.dumps(res.get("result", {}).get("value"), ensure_ascii=False))
            return
        time.sleep(4)
        suffix = a.suffix if a.suffix is not None else f"_{a.lang}"
        shot(out / f"ui_empty{suffix}.png")

        if a.workflow:
            expr = ("(async () => {"
                    f"const r = await fetch('/api/userdata/workflows%2F{a.workflow}.json');"
                    "if (!r.ok) return 'http ' + r.status;"
                    "const j = await r.json();"
                    f"await window.app.loadGraphData(j, true, true, '{a.workflow}');"
                    "return 'ok'; })()")
            res = ws.call("Runtime.evaluate",
                          {"expression": expr, "awaitPromise": True, "returnByValue": True},
                          timeout=60)
            print("loadGraphData ->", res.get("result", {}).get("value"))
            time.sleep(3)
            shot(out / f"ui_workflow{suffix}.png")

            if a.run:
                # Actually generate an image, so the screenshot shows the node in use.
                res = ws.call("Runtime.evaluate",
                              {"expression": "window.app?.api?.clientId || ''",
                               "returnByValue": True})
                cid = res.get("result", {}).get("value") or ""
                if not cid:
                    res = ws.call("Runtime.evaluate",
                                  {"expression": "JSON.stringify(window.__wsurls || [])",
                                   "returnByValue": True})
                    seen = json.loads(res.get("result", {}).get("value") or "[]")
                    cid = next((u.split("clientId=")[1] for u in seen if "clientId=" in u), "")
                print("frontend client_id ->", cid or "(not found)")
                expr = ("(async () => {"
                        "const p = await window.app.graphToPrompt();"
                        "const r = await fetch('/api/prompt', {method: 'POST',"
                        "  headers: {'Content-Type': 'application/json'},"
                        "  body: JSON.stringify({prompt: p.output,"
                        "    client_id: " + json.dumps(cid or "capture-ui") + "})});"
                        "if (!r.ok) return 'queue http ' + r.status;"
                        "const j = await r.json();"
                        "for (let i = 0; i < 600; i++) {"
                        "  const h = await (await fetch('/api/history/' + j.prompt_id)).json();"
                        "  if (h[j.prompt_id]) {"
                        "    const st = h[j.prompt_id].status || {};"
                        "    return 'done ' + (st.status_str || '?');"
                        "  }"
                        "  await new Promise(res => setTimeout(res, 1000));"
                        "}"
                        "return 'timeout'; })()")
                res = ws.call("Runtime.evaluate",
                              {"expression": expr, "awaitPromise": True, "returnByValue": True},
                              timeout=900)
                print("generation ->", res.get("result", {}).get("value"))

                # SaveImage previews are drawn on the canvas, not necessarily as DOM <img> tags.
                # A finished job in /history is not the same as a rendered preview.
                wait_js = ("(async () => {"
                           "for (let i = 0; i < 120; i++) {"
                           "  const save = window.app.graph._nodes.find(n => n.type === 'SaveImage');"
                           "  if (save?.imgs?.length) return 'canvas preview x' + save.imgs.length;"
                           "  const imgs = [...document.querySelectorAll('img')]"
                           "    .filter(el => (el.src || '').includes('/api/view')"
                           "               || (el.src || '').includes('/view?'));"
                           "  if (imgs.length) return 'thumbnail x' + imgs.length;"
                           "  await new Promise(r => setTimeout(r, 1000));"
                           "}"
                           "return 'no thumbnail'; })()")
                res = ws.call("Runtime.evaluate",
                              {"expression": wait_js, "awaitPromise": True, "returnByValue": True},
                              timeout=300)
                print("result visible ->", res.get("result", {}).get("value"))
                # The node preview lives on the canvas; make it repaint before the shot.
                ws.call("Runtime.evaluate", {"expression": (
                    "(() => { const c = window.app.canvas;"
                    " c.setDirty(true, true); c.draw(true, true); return 'repainted'; })()"),
                    "returnByValue": True})
                time.sleep(5)
                shot(out / f"ui_used{suffix}.png")
    finally:
        chrome.terminate()


if __name__ == "__main__":
    main()
