"""Production entry point for the H1Cloud Python runtime."""

import logging
import os

from waitress import serve

from schedule_viz.server import MAX_BODY_BYTES, application


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or "25070")
    serve(application, host="0.0.0.0", port=port, threads=4,
          max_request_body_size=MAX_BODY_BYTES, expose_tracebacks=False)
