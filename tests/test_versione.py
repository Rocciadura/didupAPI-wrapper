"""``__version__`` deve restare allineato a pyproject.toml."""

from __future__ import annotations

import re
from pathlib import Path

import didupwrapper


def test_versione_allineata_a_pyproject():
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert match is not None
    assert didupwrapper.__version__ == match.group(1)
