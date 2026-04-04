"""Tests for openclaw path resolution in notify.py."""
from __future__ import annotations

from unittest.mock import patch

from factory.notify import _find_openclaw


class TestFindOpenclaw:
    def test_finds_via_shutil_which(self):
        with patch("factory.notify.shutil.which", return_value="/usr/local/bin/openclaw"):
            assert _find_openclaw() == "/usr/local/bin/openclaw"

    def test_falls_back_to_fnm_dirs(self, tmp_path):
        fnm_dir = tmp_path / ".local" / "share" / "fnm" / "node-versions"
        v_dir = fnm_dir / "v22.0.0" / "installation" / "bin"
        v_dir.mkdir(parents=True)
        (v_dir / "openclaw").touch()

        with patch("factory.notify.shutil.which", return_value=None), \
             patch("factory.notify.Path.home", return_value=tmp_path):
            result = _find_openclaw()
        assert result is not None
        assert "openclaw" in result

    def test_picks_latest_fnm_version(self, tmp_path):
        fnm_dir = tmp_path / ".local" / "share" / "fnm" / "node-versions"
        for v in ["v20.0.0", "v24.14.0"]:
            d = fnm_dir / v / "installation" / "bin"
            d.mkdir(parents=True)
            (d / "openclaw").touch()

        with patch("factory.notify.shutil.which", return_value=None), \
             patch("factory.notify.Path.home", return_value=tmp_path):
            result = _find_openclaw()
        assert "v24.14.0" in result

    def test_returns_none_when_not_found(self, tmp_path):
        with patch("factory.notify.shutil.which", return_value=None), \
             patch("factory.notify.Path.home", return_value=tmp_path):
            assert _find_openclaw() is None
