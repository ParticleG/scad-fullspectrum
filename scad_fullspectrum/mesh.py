"""Binary/ASCII STL reading.

OpenSCAD writes binary STL by default, which is all the pipeline needs; the
ASCII branch exists so hand-made meshes keep working.
"""

from __future__ import annotations

import struct
from pathlib import Path

__all__ = ["read_stl"]

Point = tuple[float, float, float]
Triangle = tuple[int, int, int]


def read_stl(path: str | Path) -> tuple[list[Point], list[Triangle]]:
    """Return ``(vertices, triangles)`` from an STL file."""

    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError(f"{path}: too short to be an STL file")
    if data[:5].lower() == b"solid" and not _looks_binary(data):
        return _read_ascii(data)
    return _read_binary(data)


def _looks_binary(data: bytes) -> bool:
    """Binary STLs may start with ``solid`` too; trust the triangle count."""

    if len(data) < 84:
        return False
    count = struct.unpack_from("<I", data, 80)[0]
    return len(data) == 84 + count * 50


def _read_binary(data: bytes) -> tuple[list[Point], list[Triangle]]:
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + count * 50:
        raise ValueError("binary STL size does not match its triangle count")
    vertices: list[Point] = []
    triangles: list[Triangle] = []
    offset = 84
    index: dict[Point, int] = {}
    for _ in range(count):
        values = struct.unpack_from("<12fH", data, offset)
        offset += 50
        indices: list[int] = []
        for corner in range(3):
            point = (
                float(values[3 + corner * 3]),
                float(values[4 + corner * 3]),
                float(values[5 + corner * 3]),
            )
            existing = index.get(point)
            if existing is None:
                existing = len(vertices)
                index[point] = existing
                vertices.append(point)
            indices.append(existing)
        if len(set(indices)) == 3:
            triangles.append((indices[0], indices[1], indices[2]))
    return vertices, triangles


def _read_ascii(data: bytes) -> tuple[list[Point], list[Triangle]]:
    vertices: list[Point] = []
    triangles: list[Triangle] = []
    index: dict[Point, int] = {}
    pending: list[int] = []
    for line in data.decode("ascii", "replace").splitlines():
        parts = line.split()
        if not parts or parts[0] != "vertex":
            continue
        point = (float(parts[1]), float(parts[2]), float(parts[3]))
        existing = index.get(point)
        if existing is None:
            existing = len(vertices)
            index[point] = existing
            vertices.append(point)
        pending.append(existing)
        if len(pending) == 3:
            if len(set(pending)) == 3:
                triangles.append((pending[0], pending[1], pending[2]))
            pending = []
    return vertices, triangles
