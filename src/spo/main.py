from __future__ import annotations

import argparse

import uvicorn

from spo.app import create_app, create_state
from spo.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    web = subparsers.add_parser("web", help="Run the local web UI.")
    web.add_argument("--host", default=None, help="Bind host override.")
    web.add_argument("--port", default=None, type=int, help="Bind port override.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "web":
        settings = load_settings()
        if args.host:
            settings.bind_host = args.host
        if args.port:
            settings.bind_port = args.port
        app = create_app(create_state(settings))
        uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)


if __name__ == "__main__":
    main()
