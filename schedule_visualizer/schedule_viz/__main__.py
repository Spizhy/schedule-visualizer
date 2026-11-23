"""Точка входа: ``python -m schedule_viz``."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import webbrowser
from pathlib import Path

from .parser import parse_schedule
from .server import serve


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schedule_viz", description="Визуализатор расписания"
    )
    sub = parser.add_subparsers(dest="command")

    serve_cmd = sub.add_parser("serve", help="запустить веб-приложение (по умолчанию)")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.add_argument("--open", action="store_true", help="открыть браузер")

    parse_cmd = sub.add_parser("parse", help="разобрать файл и вывести JSON")
    parse_cmd.add_argument("file", type=Path, help="текстовый файл с расписанием")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "parse":
        try:
            text = args.file.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Не удалось прочитать файл: {exc}", file=sys.stderr)
            return 1
        json.dump(parse_schedule(text).to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    if getattr(args, "open", False):
        webbrowser.open(f"http://{host}:{port}")
    serve(host, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
