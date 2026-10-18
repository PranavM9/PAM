"""Generated images: deterministic, accessible, small, and committed as generated."""

from __future__ import annotations

import re

import pytest

from tests.helpers import ROOT, load_tool


@pytest.fixture(autouse=True)
def _images_exist():
    if not (ROOT / "images").is_dir():
        pytest.skip("mock/tmobile/images/ has not been generated yet")


def _tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*.svg"))}


def test_two_runs_are_byte_identical(tmp_path):
    make_images = load_tool("make_images")
    make_images.build(tmp_path / "a")
    make_images.build(tmp_path / "b")
    first, second = _tree(tmp_path / "a"), _tree(tmp_path / "b")
    assert first and first == second


def test_committed_images_match_the_generator(tmp_path):
    make_images = load_tool("make_images")
    make_images.build(tmp_path)
    assert _tree(tmp_path) == _tree(ROOT / "images")


def test_every_svg_has_a_title_and_is_small():
    files = sorted((ROOT / "images").rglob("*.svg"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"<title[^>]*>[^<]+</title>", text), path.name
        assert path.stat().st_size < 8 * 1024, path.name
        assert "http://" not in text.replace("http://www.w3.org/2000/svg", ""), path.name


def test_sizes_by_kind():
    def size(rel):
        text = (ROOT / "images" / rel).read_text(encoding="utf-8")
        m = re.search(r'width="(\d+)" height="(\d+)"', text)
        return int(m.group(1)), int(m.group(2))

    assert size("devices/kestrel-5-slate.svg") == (240, 480)
    assert size("devices/aurora-fold-onyx.svg") == (480, 480)
    assert size("plans/max.svg") == (400, 240)
    assert size("addons/protection.svg") == (240, 240)
    assert size("people/chen-maya.svg") == (96, 96)
    assert "9:41" in (ROOT / "images/devices/kestrel-5-slate.svg").read_text(encoding="utf-8")
