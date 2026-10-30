"""The diagnosis core must never read the true answers."""

from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "cloudsleuth_zeroth" / "core"


def test_core_never_mentions_labels():
    for f in CORE.glob("*.py"):
        text = f.read_text()
        assert "import labels" not in text and "labels." not in text, f.name
        assert "read_label" not in text and "root_causes" not in text, f.name
