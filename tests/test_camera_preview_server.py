import http.client
import json
import threading
import unittest

from scripts.camera_preview_server import LatestFrameStore, make_http_server


def read_part(response):
    assert response.readline() == b"--frame\r\n"
    assert response.readline() == b"Content-Type: image/jpeg\r\n"
    length = int(response.readline().split(b": ", 1)[1])
    assert response.readline() == b"\r\n"
    image = response.read(length)
    assert response.read(2) == b"\r\n"
    return image


class LatestFrameStoreTests(unittest.TestCase):
    def test_slow_consumer_gets_newest_frame_without_backlog(self):
        store = LatestFrameStore()
        store.publish(1, b"first", now=10.0)
        store.publish(1, b"second", now=10.01)
        store.publish(1, b"latest", now=10.02)
        self.assertEqual(store.latest_after(1, 0, timeout=0), (3, b"latest"))
        self.assertEqual(store.snapshot(1), (3, b"latest"))

    def test_http_stream_coalesces_burst_and_status_shows_arrival_gap(self):
        store = LatestFrameStore()
        store.publish(1, b"frame-a")
        server = make_http_server(store, port=0, max_fps=5)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            conn.request("GET", "/stream/1")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(read_part(response), b"frame-a")

            store.publish(1, b"frame-b")
            store.publish(1, b"frame-c")
            self.assertEqual(read_part(response), b"frame-c")

            status_conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                status_conn.request("GET", "/status")
                status = json.loads(status_conn.getresponse().read())
            finally:
                status_conn.close()
            self.assertEqual(status["1"], 3)
            self.assertIsNotNone(status["gap_p95_ms"]["1"])
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
