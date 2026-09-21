import io
import sys
from unittest.mock import patch

import pytest

from arrow_y2k.__main__ import main, prepare_windowed_streams


def test_all_four_windowed_streams_get_one_utf8_runtime_log(tmp_path):
    with patch.multiple(sys, stdout=None, stderr=None, __stdout__=None, __stderr__=None):
        stream = prepare_windowed_streams(tmp_path)
        assert all(getattr(sys, name) is stream
                   for name in ("stdout", "stderr", "__stdout__", "__stderr__"))
        sys.stderr.write("窗口日志 / test\n")
        stream.flush()
    stream.close()
    assert (tmp_path / "runtime.log").read_text(encoding="utf-8") == "窗口日志 / test\n"


def test_console_streams_are_preserved_and_no_log_created(tmp_path):
    output, errors = io.StringIO(), io.StringIO()
    with patch.multiple(sys, stdout=output, stderr=errors, __stdout__=output, __stderr__=errors):
        assert prepare_windowed_streams(tmp_path) is None
        assert sys.stdout is output and sys.__stderr__ is errors
    assert not (tmp_path / "runtime.log").exists()


def test_only_missing_streams_are_replaced(tmp_path):
    output = io.StringIO()
    with patch.multiple(sys, stdout=output, stderr=None, __stdout__=output, __stderr__=None):
        stream = prepare_windowed_streams(tmp_path)
        assert sys.stdout is output and sys.__stdout__ is output
        assert sys.stderr is stream and sys.__stderr__ is stream
    stream.close()


def test_selftest_branch_never_prepares_real_player_logging(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["game", "--self-test", "--test-report", str(tmp_path / "report.json")])
    with patch("arrow_y2k.selftest.run_self_tests", return_value=0) as runner:
        with patch("arrow_y2k.__main__.prepare_windowed_streams", side_effect=AssertionError("must not touch player data")):
            with pytest.raises(SystemExit) as stopped:
                main()
    assert stopped.value.code == 0
    runner.assert_called_once_with(str(tmp_path / "report.json"))
