"""Parsers for the macOS memory tools used by the short diagnostic."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any


class MemoryToolParseError(ValueError):
    """Raised when a macOS memory-tool result is incomplete or malformed."""


@dataclass(frozen=True)
class FootprintSnapshot:
    physical_footprint_bytes: int
    category_dirty_bytes: dict[str, int]


@dataclass(frozen=True)
class VMMapSnapshot:
    physical_footprint_bytes: int
    malloc_zone_dirty_bytes: int
    malloc_zone_allocated_bytes: int
    malloc_zone_fragmentation_bytes: int


@dataclass(frozen=True)
class HeapClass:
    name: str
    count: int
    allocated_bytes: int
    type_name: str | None


@dataclass(frozen=True)
class HeapSnapshot:
    node_count: int
    allocated_bytes: int
    classes: tuple[HeapClass, ...]


_SIZE_PATTERN = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>[BKMGTP]?)$")
_SIZE_MULTIPLIERS = {
    "": 1,
    "B": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
    "P": 1024**5,
}
_VM_PHYSICAL_PATTERN = re.compile(
    r"^Physical footprint:\s+(?P<size>[^\s]+)\s*$", re.MULTILINE
)
_VM_ZONE_ROW_PATTERN = re.compile(
    r"^\s*(?P<name>\S+)\s+"
    r"(?P<virtual>\S+)\s+(?P<resident>\S+)\s+"
    r"(?P<dirty>\S+)\s+(?P<swapped>\S+)\s+"
    r"(?P<count>[0-9,]+)\s+(?P<allocated>\S+)\s+"
    r"(?P<fragmentation>\S+)\s+(?P<percent>[0-9.]+%)\s+"
    r"(?P<regions>[0-9,]+)\s*$"
)
_HEAP_SUMMARY_PATTERN = re.compile(
    r"^All zones:\s+(?P<nodes>[0-9,]+)\s+nodes\s+"
    r"\((?P<bytes>[^)]+)\)\s*$",
    re.MULTILINE,
)
_HEAP_ROW_PREFIX_PATTERN = re.compile(
    r"^\s*(?P<count>[0-9,]+)\s+(?P<bytes>\S+)\s+"
    r"(?P<average>\S+)\s+(?P<remainder>.+?)\s*$"
)
_HEAP_TYPED_SUFFIX_PATTERN = re.compile(
    r"^(?P<name>.*?)\s{2,}(?P<type>C\+\+|CFType|ObjC|Swift|C)"
    r"(?:\s{2,}|\s+)(?P<binary>\S+)\s*$"
)


def parse_size_bytes(raw_value: str) -> int:
    value = raw_value.strip().replace(",", "").upper()
    match = _SIZE_PATTERN.fullmatch(value)
    if match is None:
        raise MemoryToolParseError(f"unsupported memory size: {raw_value!r}")
    scaled = float(match.group("value")) * _SIZE_MULTIPLIERS[match.group("unit")]
    return int(round(scaled))


def parse_footprint_json(payload: dict[str, Any], *, pid: int) -> FootprintSnapshot:
    errors = payload.get("errors")
    if not isinstance(errors, list) or errors:
        raise MemoryToolParseError("footprint JSON contains errors or no error list")
    bytes_per_unit = payload.get("bytes per unit")
    if not isinstance(bytes_per_unit, (int, float)) or bytes_per_unit <= 0:
        raise MemoryToolParseError("footprint JSON has no valid byte scale")
    processes = payload.get("processes")
    if not isinstance(processes, list):
        raise MemoryToolParseError("footprint JSON has no process list")
    process = next(
        (item for item in processes if isinstance(item, dict) and item.get("pid") == pid),
        None,
    )
    if process is None:
        raise MemoryToolParseError(f"footprint JSON has no process for pid {pid}")
    auxiliary = process.get("auxiliary")
    categories = process.get("categories")
    if not isinstance(auxiliary, dict) or not isinstance(categories, dict):
        raise MemoryToolParseError("footprint JSON is missing auxiliary/category data")
    physical = auxiliary.get("phys_footprint")
    if not isinstance(physical, (int, float)) or physical < 0:
        raise MemoryToolParseError("footprint JSON has no physical footprint")

    dirty: dict[str, int] = {}
    for name, category in categories.items():
        if not isinstance(name, str) or not isinstance(category, dict):
            continue
        value = category.get("dirty")
        if isinstance(value, (int, float)) and value >= 0:
            dirty[name] = int(round(value * bytes_per_unit))
    if "MALLOC_SMALL" not in dirty:
        raise MemoryToolParseError("footprint JSON has no MALLOC_SMALL dirty value")
    return FootprintSnapshot(
        physical_footprint_bytes=int(round(physical * bytes_per_unit)),
        category_dirty_bytes=dirty,
    )


def parse_footprint_file(path: Path, *, pid: int) -> FootprintSnapshot:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MemoryToolParseError(f"could not read footprint JSON: {error}") from error
    if not isinstance(payload, dict):
        raise MemoryToolParseError("footprint JSON root must be an object")
    return parse_footprint_json(payload, pid=pid)


def parse_vmmap_summary(text: str) -> VMMapSnapshot:
    physical_match = _VM_PHYSICAL_PATTERN.search(text)
    if physical_match is None:
        raise MemoryToolParseError("vmmap summary has no physical footprint")
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith("MALLOC ZONE")
            and "ALLOCATED" in line
            and "FRAG SIZE" in line
        ),
        None,
    )
    if header_index is None:
        raise MemoryToolParseError("vmmap summary has no malloc-zone table")

    rows: list[re.Match[str]] = []
    for line in lines[header_index + 1 :]:
        match = _VM_ZONE_ROW_PATTERN.match(line)
        if match is not None:
            if match.group("name") == "TOTAL" and _is_vmmap_total(match, rows):
                break
            rows.append(match)
            continue
        is_divider = not line.strip() or set(line) <= {"=", "-", " "}
        if not rows and is_divider:
            continue
        if not rows:
            raise MemoryToolParseError(
                "vmmap summary has malformed malloc-zone table"
            )
        break

    if not rows:
        raise MemoryToolParseError("vmmap summary has no parseable malloc zones")
    return VMMapSnapshot(
        physical_footprint_bytes=parse_size_bytes(physical_match.group("size")),
        malloc_zone_dirty_bytes=sum(
            parse_size_bytes(match.group("dirty")) for match in rows
        ),
        malloc_zone_allocated_bytes=sum(
            parse_size_bytes(match.group("allocated")) for match in rows
        ),
        malloc_zone_fragmentation_bytes=sum(
            parse_size_bytes(match.group("fragmentation")) for match in rows
        ),
    )


def _is_vmmap_total(
    candidate: re.Match[str], rows: list[re.Match[str]]
) -> bool:
    if not rows:
        return False
    integer_fields = ("count", "regions")
    integers_match = all(
        int(candidate.group(field).replace(",", ""))
        == sum(int(row.group(field).replace(",", "")) for row in rows)
        for field in integer_fields
    )
    size_fields = (
        "virtual",
        "resident",
        "dirty",
        "swapped",
        "allocated",
        "fragmentation",
    )
    return integers_match and all(
        _size_ranges_overlap(candidate.group(field), rows, field)
        for field in size_fields
    )


def _size_ranges_overlap(
    candidate: str, rows: list[re.Match[str]], field: str
) -> bool:
    candidate_low, candidate_high = _displayed_size_range(candidate)
    row_ranges = [_displayed_size_range(row.group(field)) for row in rows]
    row_low = sum(bounds[0] for bounds in row_ranges)
    row_high = sum(bounds[1] for bounds in row_ranges)
    return candidate_high >= row_low and row_high >= candidate_low


def _displayed_size_range(raw_value: str) -> tuple[float, float]:
    value = raw_value.strip().replace(",", "").upper()
    match = _SIZE_PATTERN.fullmatch(value)
    if match is None:
        raise MemoryToolParseError(f"unsupported memory size: {raw_value!r}")
    digits = match.group("value")
    decimal_places = len(digits.partition(".")[2])
    multiplier = _SIZE_MULTIPLIERS[match.group("unit")]
    center = float(digits) * multiplier
    half_step = multiplier * (10**-decimal_places) / 2
    return max(0.0, center - half_step), center + half_step


def parse_heap_summary(text: str) -> HeapSnapshot:
    summary_matches = list(_HEAP_SUMMARY_PATTERN.finditer(text))
    if not summary_matches:
        raise MemoryToolParseError("heap output has no aggregate summary")
    summary = summary_matches[-1]

    classes: list[HeapClass] = []
    in_table = False
    for line in text[summary.end() :].splitlines():
        if "CLASS_NAME" in line and "COUNT" in line and "BYTES" in line:
            in_table = True
            continue
        if not in_table or not line.strip() or set(line.strip()) <= {"=", "-"}:
            continue
        prefix = _HEAP_ROW_PREFIX_PATTERN.match(line)
        if prefix is None:
            continue
        remainder = prefix.group("remainder")
        typed = _HEAP_TYPED_SUFFIX_PATTERN.match(remainder)
        name = typed.group("name").strip() if typed else remainder.strip()
        type_name = typed.group("type") if typed else None
        if not name:
            continue
        classes.append(
            HeapClass(
                name=name,
                count=int(prefix.group("count").replace(",", "")),
                allocated_bytes=parse_size_bytes(prefix.group("bytes")),
                type_name=type_name,
            )
        )
    if not classes:
        raise MemoryToolParseError("heap output has no parseable class rows")
    return HeapSnapshot(
        node_count=int(summary.group("nodes").replace(",", "")),
        allocated_bytes=parse_size_bytes(summary.group("bytes")),
        classes=tuple(classes),
    )
