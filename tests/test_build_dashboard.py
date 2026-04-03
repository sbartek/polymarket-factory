from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_dashboard.py"
SPEC = importlib.util.spec_from_file_location("build_dashboard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
build_dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_dashboard)


def test_build_wiki_json_emits_expected_pages(tmp_path, monkeypatch):
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "meta").mkdir(parents=True)
    (wiki_dir / "strategies").mkdir(parents=True)
    (wiki_dir / "meta" / "overview.md").write_text("# Overview\n\nStatus line\n")
    (wiki_dir / "strategies" / "alpha.md").write_text("# Alpha\n\n- first\n- second\n")

    dest = tmp_path / "dist" / "data" / "wiki.json"
    monkeypatch.setattr(build_dashboard, "WIKI_DIR", wiki_dir)

    page_count = build_dashboard.build_wiki_json(dest)

    assert page_count == 2
    pages = json.loads(dest.read_text())
    assert [page["slug"] for page in pages] == ["overview", "alpha"]
    assert pages[0]["section"] == "meta"
    assert pages[0]["title"] == "Overview"
    assert "<h1>Overview</h1>" in pages[0]["html"]
    assert "<ul>" in pages[1]["html"]


def test_dashboard_js_exports_load_json_for_wiki_page():
    dashboard_js = (Path(__file__).resolve().parents[1] / "dashboard" / "dashboard.js").read_text()
    wiki_html = (Path(__file__).resolve().parents[1] / "dashboard" / "wiki.html").read_text()

    assert "Dashboard.loadJson" in wiki_html
    assert "window.Dashboard = {" in dashboard_js
    assert "loadJson, loadSnapshot" in dashboard_js
    assert "loadJson(dataPath('storage')).catch(() => null)" in dashboard_js


def test_md_to_html_does_not_italicize_strategy_names_with_underscores():
    html = build_dashboard._md_to_html("Strategies: ev_news stale_market and _actual emphasis_.")

    assert "ev_news" in html
    assert "stale_market" in html
    assert "<em>actual emphasis</em>" in html
    assert "ev<em>news" not in html
