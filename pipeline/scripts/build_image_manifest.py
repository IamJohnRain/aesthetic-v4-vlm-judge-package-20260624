#!/usr/bin/env python3
"""Build an aesthetic-v4 manifest from image files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
IGNORED_NAMES = {".DS_Store"}
DEFAULT_CASE_IMAGE_NAME = "card.dsl.png"


def is_ignored(path: Path) -> bool:
    return (
        path.name in IGNORED_NAMES
        or path.name.startswith("._")
        or path.suffix.lower() == ".zip"
        or any(part.startswith("._") for part in path.parts)
    )


def stable_id(rel_path: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9]+", "_", Path(rel_path).stem).strip("_").lower() or "sample"
    digest = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:10]
    return f"{stem}_{digest}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) >= 24 and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", header[16:24])
    return None, None


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    if path.suffix.lower() == ".png":
        return png_dimensions(path)
    return None, None


def iter_images(input_path: Path, case_image_name: str | None = None) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() in SUPPORTED_IMAGES and not is_ignored(input_path):
            return [input_path]
        raise SystemExit(f"input file is not a supported image: {input_path}")
    if not input_path.exists():
        raise SystemExit(f"input path not found: {input_path}")
    if case_image_name:
        if Path(case_image_name).name != case_image_name:
            raise SystemExit("--case-image-name must be a file name, not a path")
        direct_sample = input_path / case_image_name
        samples = [
            child / case_image_name
            for child in sorted(input_path.iterdir())
            if child.is_dir() and not is_ignored(child)
        ]
        existing = [
            path
            for path in ([direct_sample] + samples)
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGES and not is_ignored(path)
        ]
        missing = [path.parent.name for path in samples if not path.exists()]
        if missing:
            preview = ", ".join(missing[:10])
            suffix = "..." if len(missing) > 10 else ""
            print(
                f"warning: {len(missing)} case directories do not contain {case_image_name}: {preview}{suffix}",
                flush=True,
            )
        return existing
    return sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGES and not is_ignored(path)
    )


def build_records(input_path: Path, case_image_name: str | None = None) -> list[dict[str, Any]]:
    created_at = datetime.now(timezone.utc).isoformat()
    root = input_path if input_path.is_dir() else input_path.parent
    records: list[dict[str, Any]] = []
    for sample in iter_images(input_path, case_image_name=case_image_name):
        rel = sample.relative_to(root).as_posix()
        digest = file_sha256(sample)
        width, height = image_dimensions(sample)
        source = rel.split("/", 1)[0] if "/" in rel else input_path.stem or "images"
        sample_metadata = {}
        if case_image_name and "/" in rel:
            sample_metadata = {
                "case_id": rel.split("/", 1)[0],
                "case_image_name": case_image_name,
            }
        records.append(
            {
                "schema_version": 1,
                "id": stable_id(rel),
                "source": source,
                "source_key": rel,
                "input_type": "image",
                "input_path": str(sample.resolve()),
                "sample_relpath": rel,
                "sample_metadata": sample_metadata,
                "render_status": "ok",
                "file_sha256": digest,
                "file_bytes": sample.stat().st_size,
                "created_at": created_at,
                "views": [
                    {
                        "viewport": "image",
                        "status": "ok",
                        "screenshot_path": str(sample.resolve()),
                        "screenshot_sha256": digest,
                        "screenshot_width": width,
                        "screenshot_height": height,
                    }
                ],
            }
        )
    return records


def write_jsonl(records: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="../a2ui_png", help="Image file or directory.")
    parser.add_argument("--out", default="../runs/a2ui-images/manifest.jsonl")
    parser.add_argument("--summary", default="../runs/a2ui-images/manifest.summary.json")
    parser.add_argument(
        "--case-image-name",
        default=DEFAULT_CASE_IMAGE_NAME,
        help="When input is a dataset directory, evaluate only this file inside each direct case subdirectory.",
    )
    parser.add_argument("--all-images", action="store_true", help="Recursively evaluate all supported images.")
    parser.add_argument("--expect-count", type=int, default=None)
    args = parser.parse_args()

    case_image_name = None if args.all_images else args.case_image_name
    records = build_records(Path(args.input), case_image_name=case_image_name)
    if not records:
        raise SystemExit("no supported images found")
    if args.expect_count is not None and len(records) != args.expect_count:
        raise SystemExit(f"expected {args.expect_count} records, got {len(records)}")

    write_jsonl(records, Path(args.out))
    summary = {
        "profile": "aesthetic-v4",
        "input": str(Path(args.input).resolve()),
        "out": args.out,
        "records": len(records),
        "case_image_name": case_image_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
