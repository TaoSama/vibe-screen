#!/usr/bin/env python3
"""Create a deterministic ZIP archive from one file or directory."""

from __future__ import annotations

import argparse
import os
import stat
import zipfile
from pathlib import Path


ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="File or directory to archive.")
    parser.add_argument("--output", type=Path, required=True, help="ZIP file to create.")
    return parser.parse_args()


def archive_entries(source: Path) -> list[Path]:
    return [source, *source.rglob("*")] if source.is_dir() else [source]


def create_deterministic_zip(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if not source.exists():
        raise FileNotFoundError(f"archive input does not exist: {source}")
    if output == source or source in output.parents:
        raise ValueError("archive output must be outside the input tree")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    temporary_output.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary_output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(
                archive_entries(source),
                key=lambda item: item.relative_to(source.parent).as_posix(),
            ):
                relative = path.relative_to(source.parent).as_posix()
                mode = path.lstat().st_mode
                if path.is_dir() and not path.is_symlink():
                    relative += "/"
                info = zipfile.ZipInfo(relative, date_time=ZIP_TIMESTAMP)
                info.create_system = 3
                info.flag_bits |= 0x800
                if path.is_symlink():
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, os.readlink(path).encode("utf-8"))
                elif path.is_dir():
                    info.external_attr = (stat.S_IFDIR | stat.S_IMODE(mode)) << 16 | 0x10
                    archive.writestr(info, b"")
                else:
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IFREG | stat.S_IMODE(mode)) << 16
                    archive.writestr(info, path.read_bytes())
        temporary_output.replace(output)
    finally:
        temporary_output.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    create_deterministic_zip(args.input, args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
