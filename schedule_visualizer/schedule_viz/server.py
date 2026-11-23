"""HTTP API and local development server for the schedule visualizer."""
from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from .parser import parse_schedule

LOG = logging.getLogger("schedule_viz")
STATIC_DIR = Path(__file__).with_name("static")
MAX_BODY_BYTES = 256 * 1024

_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/sample.txt": ("sample.txt", "text/plain; charset=utf-8"),
}
_SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'"),
)


def _json_response(status: HTTPStatus, payload: dict):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def _error(status: HTTPStatus, message: str):
    return _json_response(status, {"error": message})


def _get(path: str):
    if path == "/healthz":
        payload = {"status": "ok"}
        if revision := os.environ.get("SCHEDULE_REVISION"):
            payload["revision"] = revision
        return _json_response(HTTPStatus.OK, payload)
    entry = _STATIC_FILES.get(path)
    if entry is None:
        return _error(HTTPStatus.NOT_FOUND, "Не найдено")
    filename, content_type = entry
    try:
        return HTTPStatus.OK, (STATIC_DIR / filename).read_bytes(), content_type
    except OSError:
        LOG.exception("Не удалось прочитать %s", filename)
        return _error(HTTPStatus.INTERNAL_SERVER_ERROR, "Файл недоступен")


def _parse_request(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "")
        if length < 0:
            raise ValueError
    except ValueError:
        return _error(HTTPStatus.LENGTH_REQUIRED, "Нужен заголовок Content-Length")
    if length > MAX_BODY_BYTES:
        return _error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Текст слишком большой")

    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
        text = payload["text"]
        if not isinstance(text, str):
            raise TypeError
    except (ValueError, KeyError, TypeError, RecursionError):
        return _error(HTTPStatus.BAD_REQUEST, 'Ожидается JSON вида {"text": "..."}')

    if sum(1 for line in text.splitlines() if line.strip()) > 200:
        return _error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Не более 200 непустых строк за один раз")

    try:
        return _json_response(HTTPStatus.OK, parse_schedule(text).to_dict())
    except Exception:
        LOG.exception("Ошибка разбора")
        return _error(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось разобрать текст")


def application(environ, start_response):
    method, path = environ["REQUEST_METHOD"], environ["PATH_INFO"]
    if method in ("GET", "HEAD"):
        status, body, content_type = _get(path)
    elif method == "POST" and path == "/api/parse":
        status, body, content_type = _parse_request(environ)
    else:
        status, body, content_type = _error(HTTPStatus.NOT_FOUND, "Не найдено")

    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        *_SECURITY_HEADERS,
    ]
    start_response(f"{status.value} {status.phrase}", headers)
    return [body] if method != "HEAD" else []


class _DevelopmentServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def create_server(host: str = "127.0.0.1", port: int = 8000) -> WSGIServer:
    return make_server(host, port, application, server_class=_DevelopmentServer)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    with create_server(host, port) as httpd:
        LOG.info("Визуализатор расписания: http://%s:%d", host, httpd.server_address[1])
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            LOG.info("Остановка сервера")
