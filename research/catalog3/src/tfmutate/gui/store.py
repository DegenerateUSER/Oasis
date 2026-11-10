"""Private CSV storage, registered historical sources, and shared score accounting."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..reporter import _atomic_stream, summary_data

ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_CSV_BYTES = 8 * 1024 * 1024
MAX_ROWS = 50000
MAX_LOG_BYTES = 64 * 1024
REQUIRED_COLUMNS = {'repo_name', 'mutant_id', 'operator_id', 'operator_category', 'test_status', 'validate_status'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def safe_path(path: Path, root: Path | None = None) -> Path:
    """Reject symlinks in every component, including intermediate directories."""
    path = Path(path).absolute()
    if '..' in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('unsafe symlink/path')
    if root is not None and not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('unsafe path outside owned storage')
    return path


def private_dir(path: Path) -> Path:
    path = safe_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def read_bytes(path: Path, limit: int, *, tail: bool = False) -> bytes:
    path = safe_path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('unsafe non-regular artifact')
        if tail:
            stream.seek(max(0, info.st_size - limit))
        elif info.st_size > limit:
            raise ValueError(f'artifact exceeds {limit} bytes')
        return stream.read(limit)


def write_json(path: Path, value: dict) -> None:
    safe_path(path)
    with _atomic_stream(path) as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)


def parse_csv(text: str, *, allow_empty: bool = False) -> list[dict]:
    if not isinstance(text, str) or '\x00' in text:
        raise ValueError('CSV must be UTF-8 text without NUL characters')
    try:
        size = len(text.encode('utf-8'))
    except UnicodeError as exc:
        raise ValueError('CSV must be valid UTF-8') from exc
    if size > MAX_CSV_BYTES:
        raise ValueError(f'CSV exceeds {MAX_CSV_BYTES} bytes')
    try:
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        fields = reader.fieldnames or []
        if (not REQUIRED_COLUMNS.issubset(fields) or len(fields) != len(set(fields))
                or any(not field or len(field) > 128 for field in fields) or len(fields) > 100):
            raise ValueError('CSV requires unique named columns: ' + ', '.join(sorted(REQUIRED_COLUMNS)))
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('malformed CSV: row column count does not match header')
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ValueError(f'CSV exceeds {MAX_ROWS} rows')
    except csv.Error as exc:
        raise ValueError(f'malformed CSV: {exc}') from exc
    if not rows and not allow_empty:
        raise ValueError('CSV contains no data rows')
    return rows


class DatasetStore:
    def __init__(self, data_dir: Path, *, sources=None):
        self.root = private_dir(Path(data_dir))
        self.datasets = private_dir(self.root / 'datasets')
        historical = Path(__file__).resolve().parents[3] / 'benchmarks' / 'batch_results' / 'master.csv'
        self.sources = ({'historical-master': historical} if historical.is_file() else {}) if sources is None else dict(sources)

    def source_catalog(self) -> list[dict]:
        return [{'id': identifier, 'name': 'Historical ' + identifier,
                 'description': 'Original historical CSV; not revalidated with this version.',
                 'kind': 'historical'} for identifier in sorted(self.sources)]

    def _path(self, identifier: str, suffix: str) -> Path:
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise KeyError('unknown dataset')
        return safe_path(self.datasets / (identifier + suffix), self.root)

    def import_dataset(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ValueError('expected a JSON object')
        if set(body) == {'source_id'}:
            source = body['source_id']
            if not isinstance(source, str) or source not in self.sources:
                raise ValueError('unknown registered historical source')
            try:
                text = read_bytes(Path(self.sources[source]), MAX_CSV_BYTES).decode('utf-8')
            except (OSError, UnicodeError) as exc:
                raise ValueError('historical CSV is unavailable or not UTF-8') from exc
            name, kind = 'Historical ' + source, 'historical'
        else:
            if not set(body).issubset({'name', 'csv'}) or 'csv' not in body:
                raise ValueError('supply either name/csv or registered source_id')
            text, name, kind = body['csv'], body.get('name', 'Imported CSV'), 'imported'
            if (not isinstance(name, str) or not name.strip() or len(name) > 160
                    or any(ord(char) < 32 for char in name)):
                raise ValueError('name must be 1..160 printable characters')
        parse_csv(text)
        identifier = uuid.uuid4().hex
        metadata = {'id': identifier, 'name': name, 'created_at': utc_now(),
                    'provenance': {'kind': kind, 'message': 'Historical CSV; not revalidated.' if kind == 'historical'
                                   else 'Uploaded CSV; not revalidated or independently verified.'},
                    'metadata': {}}
        with _atomic_stream(self._path(identifier, '.csv'), newline='') as stream:
            stream.write(text)
        write_json(self._path(identifier, '.json'), metadata)
        return self.get(identifier)

    def get(self, identifier: str) -> dict:
        try:
            value = json.loads(read_bytes(self._path(identifier, '.json'), 256 * 1024))
            rows = parse_csv(self.csv_bytes(identifier).decode('utf-8'), allow_empty=True)
        except FileNotFoundError as exc:
            raise KeyError('unknown dataset') from exc
        if value.get('provenance', {}).get('kind') == 'verified' and not self._verified(identifier):
            value['provenance'] = {'kind': 'unverified', 'message': 'Owned run artifacts are missing or checksums changed; raw evidence access is disabled.'}
        return {**value, 'rows': rows, 'summary': summary_data(rows)}

    def list(self) -> list[dict]:
        return [{key: value for key, value in self.get(path.stem).items() if key != 'rows'}
                for path in sorted(self.datasets.glob('*.json')) if ID.fullmatch(path.stem)]

    def csv_bytes(self, identifier: str) -> bytes:
        try:
            return read_bytes(self._path(identifier, '.csv'), MAX_CSV_BYTES)
        except FileNotFoundError as exc:
            raise KeyError('unknown dataset') from exc

    def _job_bundle(self, identifier: str) -> tuple[Path, Path, dict]:
        self._path(identifier, '.json')  # Validate the opaque identifier, never a path.
        artifacts = safe_path(self.root / 'jobs' / identifier / 'artifacts', self.root)
        manifest_path = safe_path(artifacts / 'results.manifest.json', self.root)
        manifest = json.loads(read_bytes(manifest_path, 8 * 1024 * 1024))
        for relative in manifest.get('artifacts_sha256', {}):
            safe_path(artifacts / relative, artifacts)
        return artifacts, manifest_path, manifest

    def _verified(self, identifier: str) -> bool:
        from ..provenance import can_resume
        try:
            artifacts, manifest_path, manifest = self._job_bundle(identifier)
            csv_path = safe_path(artifacts / 'results.csv', self.root)
            return (can_resume(manifest_path, csv_path, manifest['signature'], require_resumable=False)
                    and read_bytes(csv_path, MAX_CSV_BYTES) == self.csv_bytes(identifier))
        except (KeyError, OSError, ValueError, TypeError):
            return False

    def publish_job(self, identifier: str, name: str) -> dict:
        from ..provenance import can_resume
        artifacts, manifest_path, manifest = self._job_bundle(identifier)
        csv_path = safe_path(artifacts / 'results.csv', self.root)
        if not can_resume(manifest_path, csv_path, manifest.get('signature'), require_resumable=False):
            raise ValueError('job evidence failed completion/checksum verification')
        text = read_bytes(csv_path, MAX_CSV_BYTES).decode('utf-8')
        parse_csv(text, allow_empty=True)
        with _atomic_stream(self._path(identifier, '.csv'), newline='') as stream:
            stream.write(text)
        write_json(self._path(identifier, '.json'), {
            'id': identifier, 'name': name, 'created_at': utc_now(),
            'provenance': {'kind': 'verified', 'message': 'Executed locally; completed manifest and raw evidence checksums verified. Excluded outcomes are not scored.'},
            'metadata': {'job_id': identifier, 'source_commit': manifest.get('source_commit'),
                         'duration_seconds': manifest.get('duration_seconds'),
                         'modules': manifest.get('modules', [])}})
        return self.get(identifier)

    def log(self, identifier: str, path: str) -> dict:
        dataset = self.get(identifier)
        if dataset['provenance']['kind'] != 'verified' or not self._verified(identifier):
            raise ValueError('Only verified job-owned raw evidence is readable; imported paths are never trusted.')
        members = {member for row in dataset['rows'] for member in row.get('log_paths', '').split(';') if member}
        if path not in members:
            raise ValueError('path is not an exact member of this dataset row.log_paths')
        artifacts, _, manifest = self._job_bundle(identifier)
        raw = safe_path(artifacts / 'results.raw', artifacts)
        selected = safe_path(Path(path), raw)
        relative = str(selected.relative_to(artifacts))
        if selected.suffix != '.log' or relative not in manifest.get('artifacts_sha256', {}):
            raise ValueError('path is not owned raw log evidence')
        content = read_bytes(selected, MAX_LOG_BYTES, tail=True)
        return {'text': content.decode('utf-8', errors='replace'),
                'truncated': selected.stat().st_size > MAX_LOG_BYTES}
