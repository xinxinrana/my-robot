"""Receive TCP JPEGs and present the newest frames to a browser as MJPEG.

The producer's eight-byte header is ``stream_id, jpeg_size`` (big-endian uint32).
Each HTTP client keeps one stream open. Slow clients skip intermediate JPEGs;
the server never builds a backlog of frames waiting to be displayed.
"""

import json
import math
import os
import socket
import struct
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class LatestFrameStore:
    def __init__(self):
        self._condition = threading.Condition()
        self._frames = {0: b"", 1: b""}
        self._counts = {0: 0, 1: 0}
        self._arrivals = {0: 0.0, 1: 0.0}
        self._gaps = {0: deque(maxlen=60), 1: deque(maxlen=60)}

    def publish(self, stream_id, jpeg, now=None):
        if stream_id not in self._frames or not jpeg:
            raise ValueError("unexpected stream or empty JPEG")
        now = time.monotonic() if now is None else float(now)
        with self._condition:
            previous = self._arrivals[stream_id]
            if previous:
                self._gaps[stream_id].append(max(0.0, now - previous) * 1000.0)
            self._arrivals[stream_id] = now
            self._frames[stream_id] = jpeg
            self._counts[stream_id] += 1
            self._condition.notify_all()

    def latest_after(self, stream_id, count, timeout=None):
        with self._condition:
            self._condition.wait_for(lambda: self._counts[stream_id] != count, timeout)
            return self._counts[stream_id], self._frames[stream_id]

    def snapshot(self, stream_id):
        with self._condition:
            return self._counts[stream_id], self._frames[stream_id]

    def status(self):
        now = time.monotonic()
        with self._condition:
            result = {str(key): count for key, count in self._counts.items()}
            result["age_ms"] = {
                str(key): round((now - arrival) * 1000)
                if arrival else None for key, arrival in self._arrivals.items()
            }
            result["gap_p95_ms"] = {}
            for key, gaps in self._gaps.items():
                ordered = sorted(gaps)
                result["gap_p95_ms"][str(key)] = (
                    round(ordered[math.ceil(0.95 * len(ordered)) - 1]) if ordered else None
                )
            return result


def read_exact(conn, size):
    chunks = []
    while size:
        chunk = conn.recv(size)
        if not chunk:
            raise EOFError
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def receive_frames(store, host="0.0.0.0", port=9876):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(2)
        print(f"Receiving frames on {host}:{port}", flush=True)
        while True:
            conn, address = server.accept()
            print(f"Connected: {address}", flush=True)
            with conn:
                try:
                    while True:
                        stream_id, length = struct.unpack(">II", read_exact(conn, 8))
                        if stream_id not in (0, 1) or not 0 < length <= 10_000_000:
                            raise ValueError("unexpected frame header")
                        store.publish(stream_id, read_exact(conn, length))
                except (EOFError, ConnectionError, ValueError, OSError):
                    print("Stream disconnected", flush=True)


PAGE = b"""<!doctype html><html lang=zh><meta charset=utf-8>
<title>WHAM GMR Live Preview</title>
<style>body{font:16px system-ui;background:#15191e;color:#eee;margin:24px}
.grid{display:flex;gap:20px;flex-wrap:wrap}.panel{flex:1;min-width:320px}
img{width:100%;max-height:78vh;object-fit:contain;background:#222;border-radius:8px}
small{color:#aaa}</style><h1>WHAM GMR live preview</h1>
<small id=status>Waiting for frames...</small><div class=grid>
<div class=panel><h2>Camera / WHAM</h2><img id=frame0></div>
<div class=panel><h2>Robot / GMR</h2><img id=frame1></div></div>
<script>
async function showLatest(id) {
  const image = document.getElementById('frame'+id);
  let count = 0;
  for (;;) {
    try {
      const response = await fetch('/frame/'+id+'?after='+count, {cache:'no-store'});
      if (response.status === 204) continue;
      if (!response.ok) throw new Error('preview HTTP '+response.status);
      count = Number(response.headers.get('X-Frame-Count'));
      const next = URL.createObjectURL(await response.blob());
      const previous = image.src.startsWith('blob:') ? image.src : null;
      image.src = next;
      if (previous) setTimeout(() => URL.revokeObjectURL(previous), 1000);
      await new Promise(resolve => setTimeout(resolve, __FRAME_WAIT_MS__));
    } catch (_) {
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
}
showLatest(0); showLatest(1);
setInterval(()=>fetch('/status').then(r=>r.json()).then(x=>{
document.getElementById('status').textContent=
'Camera: '+x['0']+' frames, age '+x.age_ms['0']+' ms, gap p95 '+x.gap_p95_ms['0']+' ms | '+
'Robot: '+x['1']+' frames, age '+x.age_ms['1']+' ms, gap p95 '+x.gap_p95_ms['1']+' ms';
}),1000)</script></html>"""


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        if path.startswith("/stream/"):
            self._stream(path)
            return
        if path.startswith("/frame/"):
            self._frame(path, url.query)
            return
        if path == "/status":
            body = json.dumps(self.server.frame_store.status()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/":
            page = PAGE.replace(b"__FRAME_WAIT_MS__", str(round(1000 / self.server.max_fps)).encode("ascii"))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        self.send_error(404)

    def _frame(self, path, query):
        try:
            stream_id = int(path.removeprefix("/frame/"))
            after = int(parse_qs(query).get("after", ["0"])[0])
            if stream_id not in (0, 1) or after < 0:
                raise ValueError
        except ValueError:
            self.send_error(404)
            return
        count, image = self.server.frame_store.latest_after(stream_id, after, timeout=5.0)
        if count == after or not image:
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(image)))
        self.send_header("X-Frame-Count", str(count))
        self.end_headers()
        self.wfile.write(image)

    def _stream(self, path):
        try:
            stream_id = int(path.removeprefix("/stream/"))
            if stream_id not in (0, 1):
                raise ValueError
        except ValueError:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store, no-transform")
        self.end_headers()
        store = self.server.frame_store
        period = 1.0 / self.server.max_fps
        last_count = 0
        next_send = 0.0
        try:
            while True:
                count, _ = store.latest_after(stream_id, last_count, timeout=15.0)
                if count == last_count:
                    continue
                wait_s = next_send - time.monotonic()
                if wait_s > 0:
                    time.sleep(wait_s)
                # Use the latest JPEG after the pacing wait. This coalesces a
                # producer burst into one displayed frame rather than replaying it.
                count, image = store.snapshot(stream_id)
                part = (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(image)).encode("ascii") + b"\r\n\r\n" + image + b"\r\n"
                )
                self.wfile.write(part)
                self.wfile.flush()
                last_count = count
                next_send = time.monotonic() + period
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def make_http_server(store, host="127.0.0.1", port=8098, max_fps=15.0):
    server = ThreadingHTTPServer((host, port), PreviewHandler)
    server.frame_store = store
    server.max_fps = max(1.0, float(max_fps))
    server.daemon_threads = True
    return server


def main():
    store = LatestFrameStore()
    tcp_host = os.environ.get("PREVIEW_TCP_HOST", "0.0.0.0")
    tcp_port = int(os.environ.get("PREVIEW_TCP_PORT", "9876"))
    http_host = os.environ.get("PREVIEW_HTTP_HOST", "127.0.0.1")
    http_port = int(os.environ.get("PREVIEW_HTTP_PORT", "8098"))
    max_fps = float(os.environ.get("PREVIEW_MAX_FPS", "15"))
    threading.Thread(target=receive_frames, args=(store, tcp_host, tcp_port), daemon=True).start()
    with make_http_server(store, http_host, http_port, max_fps) as server:
        print(f"Preview: http://{http_host}:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
