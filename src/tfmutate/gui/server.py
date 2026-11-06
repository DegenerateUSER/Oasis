"""Loopback HTTP transport for the local workspace and its private API."""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import mimetypes
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .. import __version__
from ..mutators import CATALOG, CATEGORIES
from .jobs import JobConflict, JobManager
from .store import DatasetStore, read_bytes, safe_path
from .validation import LIMITS, engine_path, preview

STATIC_DIR = Path(__file__).parent / "static"
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_STATIC_BYTES = 16 * 1024 * 1024
LOG = logging.getLogger(__name__)
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


FILTER_FIELDS = {"repo": "repo_name", "category": "operator_category", "operator": "operator_id", "status": "test_status"}


def select_dataset(dataset: dict, query: dict) -> dict:
    """Filter evidence and recompute its summary through the canonical scorer."""
    from ..reporter import summary_data

    if set(query) - {*FILTER_FIELDS, "q"}:
        raise ValueError("Unknown dataset filter; use repo, category, operator, status or q.")
    if any(len(values) != 1 or len(values[0]) > 512 for values in query.values()):
        raise ValueError("Each dataset filter must have one value of at most512 characters.")
    all_rows = dataset["rows"]
    rows = all_rows
    for key, field in FILTER_FIELDS.items():
        if key in query:
            rows = [row for row in rows if row.get(field) == query[key][0]]
    if "q" in query:
        needle = query["q"][0].casefold()
        rows = [row for row in rows if any(needle in str(value).casefold() for value in row.values())]
    return {**dataset, "rows": rows, "summary": summary_data(rows),
            "selection": {"total_rows": len(all_rows), "filtered_rows": len(rows)},
            "filter_options": {key: sorted({row.get(field, "") for row in all_rows if row.get(field)})
                               for key, field in FILTER_FIELDS.items()}}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int, data_dir: Path, static_dir: Path):
        self.token = secrets.token_urlsafe(32)
        self.static_dir = safe_path(static_dir)
        self.store = DatasetStore(data_dir)
        self.jobs = None
        self._oasis_closed = False
        super().__init__((host, port), RequestHandler)
        try:
            self.jobs = JobManager(self.store)
        except BaseException:
            super().server_close()
            raise

    def server_close(self):
        if not self._oasis_closed:
            self._oasis_closed = True
            try:
                if self.jobs is not None:
                    self.jobs.close()
            finally:
                super().server_close()


class RequestHandler(BaseHTTPRequestHandler):
    server: LocalServer
    server_version = "OasisLocal"
    sys_version = ""

    def log_message(self, fmt, *args):
        LOG.info(fmt, *args)

    def _send(self, status: int, content: bytes, content_type: str, **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Frame-Options", "DENY")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def _json(self, status: int, value):
        self._send(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")

    def _authorize(self, *, api: bool) -> bool:
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host_headers = self.headers.get_all("Host", [])
        host = self.headers.get("Host", "").lower()
        origins = self.headers.get_all("Origin", [])
        if (len(host_headers) != 1 or host not in hosts or len(origins) > 1
                or (origins and origins[0] != f"http://{host}")
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self._json(403, {"error": "Only same-origin loopback access is allowed."})
            return False
        token = self.headers.get("X-Oasis-Token", "")
        if api and not secrets.compare_digest(token, self.server.token):
            self._json(403, {"error": "Missing or invalid local session token; reload the workspace."})
            return False
        return True

    def _body(self):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ValueError("A single Content-Length is required; streaming request bodies are not supported.")
        try:
            size = int(self.headers["Content-Length"])
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if not 0 <= size <= MAX_REQUEST_BYTES:
            self._json(413, {"error": "Request exceeds the 16 MiB local API limit."})
            return None
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "Use an application/json request body."})
            return None
        # Bound incomplete/slow clients as well as complete oversized requests.
        self.connection.settimeout(10)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete request body.")

        def reject_constant(value):
            raise ValueError(f"Non-finite JSON value {value} is not supported.")

        body = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object.")
        return body

    def _bootstrap(self):
        return {
            "version": __version__,
            "operators": [{"id": op.id, "category": op.category, "description": op.description} for op in CATALOG.values()],
            "categories": list(CATEGORIES),
            "sources": self.server.store.source_catalog(),
            "limits": {key: maximum for key, (_, maximum) in LIMITS.items()},
            "capabilities": {engine: engine_path(engine) is not None for engine in ("terraform", "tofu")},
        }

    def _get(self, path: str, query: dict):
        store, jobs = self.server.store, self.server.jobs
        if path == "/api/bootstrap":
            return self._json(200, self._bootstrap())
        if path == "/api/datasets":
            return self._json(200, {"datasets": store.list()})
        if path == "/api/jobs":
            return self._json(200, {"jobs": jobs.list()})
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
            return self._json(200, jobs.get(parts[2]))
        if len(parts) in {3, 4} and parts[:2] == ["api", "datasets"]:
            identifier = parts[2]
            if len(parts) == 3:
                return self._json(200, select_dataset(store.get(identifier), query))
            if parts[3] == "csv":
                content = store.csv_bytes(identifier)
                if query:
                    selected = select_dataset(store.get(identifier), query)
                    columns = csv.DictReader(io.StringIO(content.decode("utf-8"), newline="")).fieldnames
                    stream = io.StringIO(newline="")
                    writer = csv.DictWriter(stream, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(selected["rows"])
                    content = stream.getvalue().encode("utf-8")
                return self._send(200, content, "text/csv; charset=utf-8",
                                  Content_Disposition=f'attachment; filename="oasis-{identifier}.csv"')
            if parts[3] == "logs":
                paths = query.get("path", [])
                if len(paths) != 1:
                    raise ValueError("Supply exactly one job-owned log path.")
                return self._json(200, store.log(identifier, paths[0]))
        if path.startswith("/api/"):
            return self._json(404, {"error": "Unknown local API endpoint."})
        return self._static(path)

    def _post(self, path: str, body: dict):
        if path == "/api/import":
            return self._json(201, self.server.store.import_dataset(body))
        if path == "/api/preview":
            return self._json(200, preview(body, self.server.store.root))
        if path == "/api/jobs":
            return self._json(202, self.server.jobs.submit(body))
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
            if body:
                raise ValueError("Cancellation accepts an empty JSON object.")
            return self._json(200, self.server.jobs.cancel(parts[2]))
        self._json(404, {"error": "Unknown local API endpoint."})

    def _static(self, path: str):
        if path == "/":
            index = self.server.static_dir / "index.html"
            if not index.is_file():
                return self._json(503, {"error": "The compiled frontend is not available yet."})
            content = read_bytes(index, MAX_STATIC_BYTES).decode("utf-8")
            if "__OASIS_TOKEN__" not in content:
                raise ValueError("Compiled frontend is missing its local-session token placeholder.")
            return self._send(200, content.replace("__OASIS_TOKEN__", html.escape(self.server.token)).encode(), "text/html; charset=utf-8")
        if not path.startswith("/assets/") or len(path) > 512:
            return self._json(404, {"error": "Unknown local resource."})
        selected = safe_path(self.server.static_dir / path.lstrip("/"), self.server.static_dir)
        if not selected.is_file():
            return self._json(404, {"error": "Unknown local resource."})
        content_type = mimetypes.guess_type(selected.name)[0] or "application/octet-stream"
        self._send(200, read_bytes(selected, MAX_STATIC_BYTES), content_type)

    def _handle(self):
        try:
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if parsed.scheme or parsed.netloc or "\x00" in path:
                raise ValueError("Invalid local request target.")
            api = path.startswith("/api/")
            if not self._authorize(api=api):
                return
            if self.command == "GET":
                return self._get(path, parse_qs(parsed.query, max_num_fields=20))
            if not api:
                return self._json(404, {"error": "Unknown local API endpoint."})
            body = self._body()
            if body is not None:
                self._post(path, body)
        except JobConflict as exc:
            self._json(409, {"error": str(exc)})
        except (KeyError, FileNotFoundError):
            self._json(404, {"error": "The requested local record does not exist."})
        except (ValueError, TypeError, UnicodeError) as exc:
            self._json(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            LOG.exception("Local API operation failed")
            self._json(500, {"error": "The local operation failed; inspect the Oasis server log."})

    do_GET = _handle
    do_POST = _handle


def create_server(*, host="127.0.0.1", port=8765, data_dir=None, static_dir=None):
    """Create a real loopback server; port zero is available to integration tests."""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Oasis GUI supports loopback hosts only.")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Port must be an integer in 0..65535.")
    directory = Path(data_dir or Path.home() / ".local" / "share" / "oasis" / "gui").expanduser()
    return LocalServer("127.0.0.1", port, directory, Path(static_dir) if static_dir is not None else STATIC_DIR)


def serve(*, host="127.0.0.1", port=8765, data_dir=None, open_browser=False):
    """Run the packaged GUI until interrupted, then request safe job cancellation."""
    if not (STATIC_DIR / "index.html").is_file():
        raise RuntimeError("The compiled GUI frontend is not available. The frontend must be built before `oasis gui` can launch.")
    with create_server(host=host, port=port, data_dir=data_dir) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Oasis local workspace: {url}", flush=True)
        print("Local access only. Ctrl-C closes the server and requests safe worker cancellation.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Closing Oasis; any active worker is being asked to restore source files.", flush=True)
    return 0
