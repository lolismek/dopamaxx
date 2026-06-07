"""Command-line interface for TRIBE v2 text signatures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .backends import DeterministicFakeBackend, TribeV2Backend
from .signature import cosine_similarity, encode_text, load_signature


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "encode":
        return _encode(args)
    if args.command == "compare":
        return _compare(args)
    parser.error("missing command")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tribev2-text",
        description="Encode text into comparable TRIBE-style signatures.",
    )
    subparsers = parser.add_subparsers(dest="command")

    encode = subparsers.add_parser("encode", help="encode text into JSON")
    input_group = encode.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--text", help="raw text to encode")
    input_group.add_argument("--text-file", type=Path, help="UTF-8 text file")
    encode.add_argument("--out", type=Path, help="output JSON path")
    encode.add_argument(
        "--backend",
        choices=("tribev2", "fake"),
        default="tribev2",
        help="prediction backend to use",
    )
    encode.add_argument("--model-id", default="facebook/tribev2")
    encode.add_argument("--cache-folder", default="tribev2_text/.cache")
    encode.add_argument("--device", default="auto")

    compare = subparsers.add_parser("compare", help="compare two signatures")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)

    return parser


def _encode(args: argparse.Namespace) -> int:
    text = args.text
    if args.text_file is not None:
        text = args.text_file.read_text(encoding="utf-8")

    if args.backend == "fake":
        backend = DeterministicFakeBackend()
    else:
        backend = TribeV2Backend(
            model_id=args.model_id,
            cache_folder=args.cache_folder,
            device=args.device,
        )

    signature = encode_text(text or "", backend=backend)
    output = signature.to_json(indent=2)
    if args.out is None:
        print(output)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
    return 0


def _compare(args: argparse.Namespace) -> int:
    left = load_signature(args.left)
    right = load_signature(args.right)
    body = {
        "similarity": cosine_similarity(left, right),
        "left_source_hash": left.source_hash,
        "right_source_hash": right.source_hash,
    }
    print(json.dumps(body, indent=2, sort_keys=True))
    return 0

