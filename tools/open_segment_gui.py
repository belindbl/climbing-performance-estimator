from __future__ import annotations

import argparse
import functools
import http.server
from pathlib import Path
import socket
import socketserver
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the segment GUI server and open it in a browser."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    port = first_available_port(args.host, args.port)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(repo_root),
    )

    with socketserver.TCPServer((args.host, port), handler) as server:
        server.allow_reuse_address = True
        url = f"http://{args.host}:{port}/tools/segment_gui.html"
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


if __name__ == "__main__":
    main()
