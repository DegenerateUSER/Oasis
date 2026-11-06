"""Launcher contract: the existing CLI starts the packaged local GUI lazily."""
from pathlib import Path

from tfmutate import cli


def test_gui_command_has_safe_defaults():
    args = cli.build_parser().parse_args(["gui"])
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.open_browser is True
    assert isinstance(args.data_dir, str)


def test_gui_can_print_help_without_importing_server(capsys):
    import pytest
    with pytest.raises(SystemExit) as exc:
        cli.main(["gui", "--help"])
    assert exc.value.code == 0
    assert "--no-open" in capsys.readouterr().out


def test_gui_launcher_passes_explicit_options(monkeypatch, tmp_path):
    import types
    import sys
    calls = []
    monkeypatch.setitem(sys.modules, "tfmutate.gui", types.SimpleNamespace(serve=lambda **kw: calls.append(kw)))
    assert cli.main(["gui", "--port", "8766", "--no-open", "--data-dir", str(tmp_path)]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8766, "data_dir": Path(tmp_path), "open_browser": False}]


def test_gui_rejects_public_binding():
    import pytest
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["gui", "--host", "0.0.0.0"])


def test_bad_gui_port_has_a_short_actionable_error(capsys):
    import pytest
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["gui", "--port", "0"])
    assert exc.value.code == 2
    message = capsys.readouterr().err
    assert len(message) < 700
    assert "1..65535" in message
