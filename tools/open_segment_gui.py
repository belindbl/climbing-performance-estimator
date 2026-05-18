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

from climbing_performance.route_hydration import hydrate_route_payload


ACTIVE_SCENARIO_PATH = REPO_ROOT / "data" / "cache" / "active_segment_scenario.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the segment GUI server and open it in a browser."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    repo_root = REPO_ROOT
    port = first_available_port(args.host, args.port)
    handler = functools.partial(SegmentGuiHandler, repo_root=repo_root)

    with socketserver.TCPServer((args.host, port), handler) as server:
        server.allow_reuse_address = True
        url = f"http://{args.host}:{port}/tools/segment_gui/segment_gui.html"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        print(f"Serving {repo_root}")
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


class SegmentGuiHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, repo_root: Path, **kwargs) -> None:
        self.repo_root = repo_root
        super().__init__(*args, directory=str(repo_root), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/scenarios/active":
            if not ACTIVE_SCENARIO_PATH.exists():
                self._send_json({"error": "No active scenario saved yet."}, status=404)
                return

            try:
                payload = json.loads(ACTIVE_SCENARIO_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=502)
                return

            self._send_json(payload)
            return

        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/routes/hydrate":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8")
                request_payload = json.loads(raw_body or "{}")
                response_payload = hydrate_route_payload(request_payload, self.repo_root)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=502)
                return

            self._send_json(response_payload)
            return

        if self.path == "/api/scenarios/active":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8")
                request_payload = json.loads(raw_body or "{}")
                ACTIVE_SCENARIO_PATH.parent.mkdir(parents=True, exist_ok=True)
                ACTIVE_SCENARIO_PATH.write_text(
                    json.dumps(request_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return

            self._send_json({"status": "saved", "path": str(ACTIVE_SCENARIO_PATH)})
            return

        if self.path != "/api/routes/hydrate":
            self.send_error(404, "Not Found")
            return

    def _send_json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    main()
