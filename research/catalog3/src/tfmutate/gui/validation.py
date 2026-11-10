"""Read-only scope previews and an intentionally small executable/config surface."""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from ..mutators import CATALOG, generate_mutants
from ..parser import find_test_module_dirs
from ..scope import resolve_scope
from .store import safe_path

MAX_PREVIEW = 200
MAX_SOURCE_BYTES = 1024 * 1024
MAX_TREE_FILES = 30000
LIMITS = {'max_mutants': (20, 5000), 'budget_seconds': (120, 7200),
          'timeout': (30, 300), 'init_timeout': (30, 300), 'init_attempts': (1, 3)}
BASE_FIELDS = {'target_path', 'engine', 'operators', 'test_directory'}


def engine_path(engine: str) -> str | None:
    if engine not in {'terraform', 'tofu'}:
        return None
    # Never search the target working directory, including through a relative PATH entry.
    trusted_path = os.pathsep.join(part for part in os.get_exec_path() if part and Path(part).is_absolute())
    return shutil.which(engine, path=trusted_path)


def test_command(config: dict) -> str:
    return shlex.join([config['engine'], 'test', '-test-directory=' + config['test_directory']])


def _git(root: Path, *args: str) -> str:
    try:
        # Read-only Git commands can otherwise execute a repository-configured fsmonitor hook.
        result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Git inspection failed or timed out') from exc
    if result.returncode:
        raise ValueError('target must be a Git repository with an existing commit')
    return result.stdout.strip()


def _inspect_tree(root: Path) -> None:
    """Refuse symlink aliases before core discovery; never inspect .git/provider caches."""
    count, source_bytes = 0, 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = [name for name in dirs if name not in {'.git', '.terraform'}]
        for name in [*dirs, *files]:
            if name == '.git':
                continue
            path = base / name
            if path.is_symlink():
                raise ValueError(f'unsafe symlink in target repository: {path.relative_to(root)}')
            count += 1
            if count > MAX_TREE_FILES:
                raise ValueError('target repository too large for local GUI inspection; select a smaller repository')
            if name.endswith(('.tf', '.tf.json', '.tftest.hcl')):
                size = path.stat().st_size
                source_bytes += size
                if size > MAX_SOURCE_BYTES or source_bytes > 20 * MAX_SOURCE_BYTES:
                    raise ValueError('Terraform source exceeds GUI inspection size limits')


def _validate(body: dict, data_dir: Path, *, job: bool) -> tuple[dict, Path, list]:
    if not isinstance(body, dict):
        raise ValueError('expected a JSON object')
    allowed = BASE_FIELDS | (set(LIMITS) | {'acknowledge_execution'} if job else set())
    if set(body) - allowed:
        raise ValueError('unknown configuration fields: ' + ', '.join(sorted(set(body) - allowed)))
    engine = body.get('engine')
    if not isinstance(engine, str) or engine not in {'terraform', 'tofu'}:
        raise ValueError('engine must be terraform or tofu; custom executable/command text is not supported')
    operators = body.get('operators', list(CATALOG))
    if (not isinstance(operators, list) or not operators or len(operators) > len(CATALOG)
            or any(not isinstance(op, str) or op not in CATALOG for op in operators)
            or len(set(operators)) != len(operators)):
        raise ValueError('operators must be a nonempty list of unique registered operator IDs')
    directory = body.get('test_directory', 'tests')
    if (not isinstance(directory, str) or not re.fullmatch(r'[A-Za-z0-9_.][A-Za-z0-9_./-]{0,199}', directory)
            or Path(directory).is_absolute() or '..' in Path(directory).parts):
        raise ValueError('test_directory must be a safe repository-relative directory')
    config = {'engine': engine, 'operators': operators, 'test_directory': directory}
    if job:
        if body.get('acknowledge_execution') is not True:
            raise ValueError('acknowledge_execution:true is required: trusted repository code can execute locally, access credentials, contact networks and create cloud resources')
        config['acknowledge_execution'] = True
        for key, (default, maximum) in LIMITS.items():
            value = body.get(key, default)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{key} must be an integer in 1..{maximum}')
            config[key] = value
        if not engine_path(engine):
            raise ValueError(f'{engine} is not available on the executable PATH')
        if any(key.startswith('TF_CLI_ARGS') for key in os.environ):
            raise ValueError('implicit TF_CLI_ARGS are unsupported; unset them before launching a run')
    target = body.get('target_path')
    if not isinstance(target, str) or not target or len(target) > 4096 or '\x00' in target:
        raise ValueError('target_path must name an existing local repository directory')
    path = safe_path(Path(target).expanduser())
    if not path.is_dir():
        raise ValueError('target_path is not an existing directory')
    root = safe_path(Path(_git(path, 'rev-parse', '--show-toplevel'))).resolve()
    path = path.resolve()
    storage = Path(data_dir).resolve()
    if storage.is_relative_to(root) or root.is_relative_to(storage):
        raise ValueError('GUI state directory must be outside and not overlap the source repository')
    _git(root, 'rev-parse', 'HEAD')
    if _git(root, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('dirty tracked/index state: commit/stash changes or use an isolated worktree')
    _inspect_tree(root)
    modules = find_test_module_dirs(path, directory)
    if not modules:
        raise ValueError('no selected .tftest.hcl modules found; add tests beside .tf files or in test_directory')
    config['target_path'] = str(path)
    scopes = []
    for module in modules:
        scope = resolve_scope(module, root, test_command(config))
        if not scope.has_runs:
            raise ValueError(f'no runnable test run blocks in {module.relative_to(root)}')
        scopes.append((module, scope))
    return config, root, scopes


def validate_job(body: dict, data_dir: Path) -> dict:
    return _validate(body, data_dir, job=True)[0]


def preview(body: dict, data_dir: Path) -> dict:
    config, root, scopes = _validate(body, data_dir, job=False)
    warnings = ['Read-only lexical preview: no init, native syntax validation, provider validation or tests have run. This is not execution or coverage evidence.']
    mutants, seen = [], set()
    truncated = False
    for _, scope in scopes:
        warnings.extend(scope.warnings)
        for path in scope.files:
            if path in seen:
                continue
            seen.add(path)
            text = path.read_bytes().decode('utf-8')
            relative = str(path.relative_to(root))
            # One bounded extra mutant distinguishes an exact cap from truncation.
            remaining = MAX_PREVIEW - len(mutants)
            for mutant in generate_mutants(path, text, [CATALOG[op] for op in config['operators']],
                                           limit=remaining + 1):
                if len(mutants) >= MAX_PREVIEW:
                    truncated = True
                    break
                digest = hashlib.sha256(mutant.mutated_text.encode()).hexdigest()[:12]
                mutants.append({'id': f'{mutant.operator_id}@{relative}:{mutant.line}:{digest}',
                                'operator_id': mutant.operator_id, 'file': relative, 'line': mutant.line,
                                'original': mutant.original_snippet, 'mutated': mutant.mutated_snippet,
                                'diff': ''.join(difflib.unified_diff(text.splitlines(keepends=True),
                                              mutant.mutated_text.splitlines(keepends=True),
                                              fromfile=relative, tofile=relative))[:16384]})
            if truncated:
                break
        if truncated:
            break
    if not mutants:
        warnings.append('No eligible literal mutation sites for the selected operators and test scope.')
    return {'modules': [str(module.relative_to(root)) for module, _ in scopes],
            'mutants': mutants, 'warnings': list(dict.fromkeys(warnings)), 'truncated': truncated}
