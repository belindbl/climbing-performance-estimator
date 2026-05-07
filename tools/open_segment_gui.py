from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
import webbrowser

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the segment GUI server and open it in a browser."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    repo_root = REPO_ROOT
    port = first_available_port(args.host, args.port)
    url = f"http://{args.host}:{port}/tools/segment_gui.html"

    print(f"Serving {repo_root}")
    print(f"Opening {url}")
    print("Press Ctrl+C to stop the server.")
    webbrowser.open(url)
    uvicorn.run(
        "climbing_performance.api:app",
        host=args.host,
        port=port,
        reload=False,
    )


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
