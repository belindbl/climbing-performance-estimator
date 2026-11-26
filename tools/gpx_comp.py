from __future__ import annotations

import argparse
import functools
import http.server
import json
from pathlib import Path
import socket
import socketserver
import sys
import threading
import webbrowser

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from climbing_performance.gpx_compare import (  # noqa: E402
    compare_segment_payload,
    comparison_load_payload,
    load_gpx_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the GPX comparison GUI server and open it in a browser."
    )
    parser.add_argument("gpx_files", nargs="*", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    if args.gpx_files:
        for track in [load_gpx_file(path) for path in args.gpx_files]:
            print(
                f"{track.name}: {track.route.distance_m / 1000:.2f} km, "
                f"{track.route.ascent_m:.0f} m ascent"
            )

    port = first_available_port(args.host, args.port)
    handler = functools.partial(GpxCompareHandler, repo_root=REPO_ROOT)

    with socketserver.TCPServer((args.host, port), handler) as server:
        server.allow_reuse_address = True
        url = f"http://{args.host}:{port}/tools/gpx_compare_gui/gpx_compare.html"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        print(f"Serving {REPO_ROOT}")
        print(f"Opening {url}")
        print("Press Ctrl+C to stop the server.")
        webbrowser.open(url)

        try:
            thread.join()
        except KeyboardInterrupt:
            print("\nStopping server.")
            server.shutdown()


def first_available_port(host: str, preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port

    raise RuntimeError(
        f"No available port found from {preferred_port} to {preferred_port + 99}."
    )


class GpxCompareHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, repo_root: Path, **kwargs) -> None:
        self.repo_root = repo_root
        super().__init__(*args, directory=str(repo_root), **kwargs)

    def do_POST(self) -> None:
        if self.path == "/api/compare/load":
            self._handle_json_api(comparison_load_payload)
            return

        if self.path == "/api/compare/segment":
            self._handle_json_api(compare_segment_payload)
            return

        self.send_error(404, "Not Found")

    def _handle_json_api(self, callback) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            request_payload = json.loads(raw_body or "{}")
            response_payload = callback(request_payload)
        except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=502)
            return

        self._send_json(response_payload)

    def _send_json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    main()
