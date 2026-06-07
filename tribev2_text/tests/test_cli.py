from __future__ import annotations

import json

from tribev2_text.cli import main
from tribev2_text.signature import SCHEMA_VERSION


def test_cli_encode_and_compare_with_fake_backend(tmp_path, capsys) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"

    assert main(["encode", "--backend", "fake", "--text", "same text", "--out", str(left)]) == 0
    assert main(["encode", "--backend", "fake", "--text", "same text", "--out", str(right)]) == 0

    body = json.loads(left.read_text(encoding="utf-8"))
    assert body["schema_version"] == SCHEMA_VERSION

    assert main(["compare", str(left), str(right)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["similarity"] == 1.0

