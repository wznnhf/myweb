#!/usr/bin/env python3
"""Rebuild missing generated study assets, or validate them with --verify.

Run from any directory with the original repository's Pillow environment:
  app/.venv/bin/python sites/shiti-cloud/scripts/prepare-study-assets.py
  app/.venv/bin/python sites/shiti-cloud/scripts/prepare-study-assets.py --verify

The manifest binds each source and output to exact SHA-256 hashes. Existing
public files are never replaced. JSON, CSS, JavaScript and other text files are
not modified. --verify needs only Python's standard library and the outputs.
"""

import argparse
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys


SITE = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = SITE.parents[1]
MANIFEST_PATH = SITE / "cloud/assets-manifest.json"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify_bytes(data, expected_hash, expected_size, label):
    if len(data) != expected_size or sha256(data) != expected_hash:
        raise ValueError(f"Hash or size mismatch: {label}")


def read_source(entry, source_root):
    source = entry["source"]
    path = source_root / source["path"]
    if source["kind"] == "sqlite_blob":
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT data FROM note_images WHERE id=?", (source["id"],)
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Missing note image: {source['id']}")
            data = bytes(row[0])
        finally:
            connection.close()
    else:
        data = path.read_bytes()
    verify_bytes(data, source["sha256"], source["size"], source["path"])
    return data


def ensure_encoder_versions(expected):
    try:
        import PIL
        from PIL import features
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to regenerate question images; use app/.venv/bin/python"
        ) from error
    actual = {"pillow": PIL.__version__, "libwebp": features.version_module("webp")}
    if actual != expected:
        raise RuntimeError(
            f"Exact encoder versions required: {expected}; found {actual}. "
            "Use the original app/.venv environment."
        )


def process_entry(entry, source_root, public_root, verify_only):
    target = public_root / entry["path"]
    if target.is_file():
        verify_bytes(target.read_bytes(), entry["sha256"], entry["size"], entry["path"])
        return "verified"
    if verify_only:
        raise FileNotFoundError(f"Missing generated asset: {entry['path']}")
    data = read_source(entry, source_root)
    if entry["transform"] == "webp":
        from PIL import Image

        output = io.BytesIO()
        with Image.open(io.BytesIO(data)) as image:
            image.save(output, "WEBP", **entry["parameters"])
        data = output.getvalue()
    elif entry["transform"] != "copy":
        raise ValueError(f"Unknown transform: {entry['transform']}")
    verify_bytes(data, entry["sha256"], entry["size"], entry["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an asset edited during a build being replaced.
    with target.open("xb") as destination:
        destination.write(data)
    return "generated"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Only validate existing generated assets")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT,
                        help="Repository root containing the original app directory")
    parser.add_argument("--public-root", type=Path, default=SITE / "public",
                        help="Generated output directory (defaults to this Site's public)")
    parser.add_argument("--jobs", type=int, default=6, help="Parallel workers (default: 6)")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text())
    entries = manifest["files"]
    if not args.verify and any(
        entry["transform"] == "webp" and not (args.public_root / entry["path"]).is_file()
        for entry in entries
    ):
        ensure_encoder_versions(manifest["webp_encoder"])
    counts = {"verified": 0, "generated": 0, "failed": 0}

    def run(entry):
        try:
            return process_entry(entry, args.source_root, args.public_root, args.verify), None
        except Exception as error:
            return "failed", str(error)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for result, error in pool.map(run, entries):
            counts[result] += 1
            if error:
                print(error, file=sys.stderr)
    print(json.dumps({"files": len(entries), "bytes": sum(e["size"] for e in entries), **counts}))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
