from __future__ import annotations

import argparse
import sys

import uvicorn

from spo.app import create_app, create_state
from spo.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spo", description="Run the local web UI.")
    parser.add_argument("--host", default=None, help="Bind host override.")
    parser.add_argument("--port", default=None, type=int, help="Bind port override.")
    return parser


def main() -> None:
    argv = sys.argv[1:]
    if argv[:1] == ["web"]:
        argv = argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.host:
        settings.bind_host = args.host
    if args.port:
        settings.bind_port = args.port
    app = create_app(create_state(settings))
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)


if __name__ == "__main__":
    main()
