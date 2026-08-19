"""tests.test_sidecar_robustness — L1: proxy/config robustness for the packaged
desktop sidecar (whose CWD is the app-data dir, so config.yaml isn't found and
the SOCKS proxy wouldn't be applied).
"""

from __future__ import annotations

import argparse

import core.config as C


def test_cik_proxy_env_overrides(monkeypatch):
    monkeypatch.setenv("ASTRA_PROXY", "socks5h://127.0.0.1:10808")
    cfg = C.build_config(argparse.Namespace(no_config=True))
    assert cfg.proxy == "socks5h://127.0.0.1:10808"


def test_cik_proxy_empty_disables(monkeypatch):
    monkeypatch.setenv("ASTRA_PROXY", "")
    cfg = C.build_config(argparse.Namespace(no_config=True))
    assert cfg.proxy is None


def test_cli_proxy_beats_env(monkeypatch):
    monkeypatch.setenv("ASTRA_PROXY", "socks5h://127.0.0.1:10808")
    cfg = C.build_config(argparse.Namespace(no_config=True,
                                            proxy="http://1.2.3.4:8080"))
    assert cfg.proxy == "http://1.2.3.4:8080"


def test_find_config_path_searches_frozen_executable_dir(monkeypatch, tmp_path):
    cfgfile = tmp_path / "config.yaml"
    cfgfile.write_text("proxy: socks5h://127.0.0.1:10808\n", encoding="utf-8")
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(C, "_script_dir", lambda: str(empty))
    monkeypatch.setattr(C.sys, "frozen", True, raising=False)
    monkeypatch.setattr(C.sys, "executable", str(tmp_path / "astra-api"))
    assert C._find_config_path("config.yaml") == str(cfgfile)


def test_find_config_path_ignores_executable_dir_when_not_frozen(monkeypatch,
                                                                 tmp_path):
    (tmp_path / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(C, "_script_dir", lambda: str(empty))
    monkeypatch.setattr(C.sys, "frozen", False, raising=False)
    monkeypatch.setattr(C.sys, "executable", str(tmp_path / "python"))
    assert C._find_config_path("config.yaml") is None
