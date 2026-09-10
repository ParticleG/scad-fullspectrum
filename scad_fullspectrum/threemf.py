"""Write a Snapmaker Orca / FullSpectrum project 3MF.

The layout mirrors what the slicer itself produces: a root object in
``3D/3dmodel.model`` whose components reference one object per colour region in
``3D/Objects/<name>_1.model``, plus ``Metadata/model_settings.config`` (one
``<part>`` per region, carrying the ``extruder`` assignment) and
``Metadata/project_settings.config`` (project settings, including
``mixed_filament_definitions``).

Only the settings that describe the loaded spools and the mix list are
rewritten; everything else is inherited from a template ``project_settings``
file so the result opens with the printer/process/filament preset the user
already uses.
"""

from __future__ import annotations

import json
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape as xml_escape

from .color import RGB, rgb_to_hex

__all__ = ["Part", "ProjectWriter", "write_project"]

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'

_MODEL_NS = (
    'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
    'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
    'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
    'requiredextensions="p"'
)

_CONTENT_TYPES = _XML_HEADER + """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

_ROOT_RELS = _XML_HEADER + """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""

_SLICE_INFO = _XML_HEADER + """<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value=""/>
  </header>
</config>
"""


@dataclass
class Part:
    """One printable colour region."""

    id: int
    name: str
    extruder: int
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)

    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        xs = [vertex[0] for vertex in self.vertices]
        ys = [vertex[1] for vertex in self.vertices]
        zs = [vertex[2] for vertex in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.9g}"


def _new_uuid() -> str:
    return str(uuid.uuid4())


class ProjectWriter:
    """Assemble the 3MF package for a set of parts."""

    def __init__(
        self,
        parts: Sequence[Part],
        settings: dict,
        *,
        model_name: str,
        application: str = "BambuStudio-2.3.6",
        bed_center: tuple[float, float] = (135.0, 135.0),
    ) -> None:
        if not parts:
            raise ValueError("a project needs at least one part")
        self.parts = list(parts)
        self.settings = settings
        self.model_name = model_name
        self.application = application
        self.bed_center = bed_center

    # -- package members --------------------------------------------------- #

    def object_file_name(self) -> str:
        return f"3D/Objects/{self.model_name}_1.model"

    def root_object_id(self) -> int:
        return max(part.id for part in self.parts) + 1

    def _transform(self) -> tuple[float, float, float]:
        mins = [part.bounds()[0] for part in self.parts]
        maxs = [part.bounds()[1] for part in self.parts]
        low = (min(m[0] for m in mins), min(m[1] for m in mins), min(m[2] for m in mins))
        high = (max(m[0] for m in maxs), max(m[1] for m in maxs), max(m[2] for m in maxs))
        center_x = (low[0] + high[0]) / 2.0
        center_y = (low[1] + high[1]) / 2.0
        return (self.bed_center[0] - center_x, self.bed_center[1] - center_y, -low[2])

    def _model_xml(self) -> str:
        root_id = self.root_object_id()
        components = "\n".join(
            f'    <component p:path="/{self.object_file_name()}" objectid="{part.id}" p:UUID="{_new_uuid()}"/>'
            for part in self.parts
        )
        offset = self._transform()
        transform = "1 0 0 0 1 0 0 0 1 " + " ".join(_number(value) for value in offset)
        return (
            _XML_HEADER
            + f'<model unit="millimeter" xml:lang="en-US" {_MODEL_NS}>\n'
            + f' <metadata name="Application">{xml_escape(self.application)}</metadata>\n'
            + ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
            + ' <metadata name="Copyright"></metadata>\n'
            + ' <metadata name="CreationDate"></metadata>\n'
            + ' <metadata name="Description"></metadata>\n'
            + ' <metadata name="Designer"></metadata>\n'
            + ' <metadata name="DesignerCover"></metadata>\n'
            + ' <metadata name="DesignerUserId"></metadata>\n'
            + ' <metadata name="License"></metadata>\n'
            + ' <metadata name="ModificationDate"></metadata>\n'
            + ' <metadata name="Origin"></metadata>\n'
            + ' <metadata name="Title"></metadata>\n'
            + " <resources>\n"
            + f'  <object id="{root_id}" p:UUID="{_new_uuid()}" type="model">\n'
            + "   <components>\n"
            + components
            + "\n   </components>\n"
            + "  </object>\n"
            + " </resources>\n"
            + f' <build p:UUID="{_new_uuid()}">\n'
            + f'  <item objectid="{root_id}" p:UUID="{_new_uuid()}" transform="{transform}" printable="1"/>\n'
            + " </build>\n"
            + "</model>\n"
        )

    def _objects_xml(self) -> str:
        chunks: list[str] = [
            _XML_HEADER,
            f'<model unit="millimeter" xml:lang="en-US" {_MODEL_NS}>\n',
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n',
            " <resources>\n",
        ]
        for part in self.parts:
            vertices = "\n".join(
                f'     <vertex x="{_number(v[0])}" y="{_number(v[1])}" z="{_number(v[2])}"/>'
                for v in part.vertices
            )
            triangles = "\n".join(
                f'     <triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}"/>' for t in part.triangles
            )
            chunks.append(
                f'  <object id="{part.id}" p:UUID="{_new_uuid()}" type="model">\n'
                f"   <mesh>\n    <vertices>\n{vertices}\n    </vertices>\n"
                f"    <triangles>\n{triangles}\n    </triangles>\n   </mesh>\n  </object>\n"
            )
        chunks.append(" </resources>\n <build/>\n</model>\n")
        return "".join(chunks)

    def _model_settings_xml(self) -> str:
        root_id = self.root_object_id()
        rows: list[str] = [_XML_HEADER, "<config>\n", f'  <object id="{root_id}">\n']
        rows.append(
            f'    <metadata key="name" value="{xml_escape(self.model_name)}"/>\n'
            '    <metadata key="extruder" value="0"/>\n'
        )
        for part in self.parts:
            rows.append(f'    <part id="{part.id}" subtype="normal_part">\n')
            rows.append(f'      <metadata key="name" value="{xml_escape(part.name)}"/>\n')
            rows.append(
                '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
            )
            rows.append(
                f'      <metadata key="source_file" value="{xml_escape(self.model_name)}.scad"/>\n'
            )
            rows.append('      <metadata key="source_object_id" value="0"/>\n')
            rows.append('      <metadata key="source_volume_id" value="0"/>\n')
            rows.append('      <metadata key="source_offset_x" value="0"/>\n')
            rows.append('      <metadata key="source_offset_y" value="0"/>\n')
            rows.append('      <metadata key="source_offset_z" value="0"/>\n')
            rows.append(f'      <metadata key="extruder" value="{part.extruder}"/>\n')
            rows.append(
                '      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0"'
                ' facets_reversed="0" backwards_edges="0"/>\n'
            )
            rows.append("    </part>\n")
        rows.append("  </object>\n")
        maps = " ".join("1" for _ in self._plates())
        rows.append("  <plate>\n")
        rows.append('    <metadata key="plater_id" value="1"/>\n')
        rows.append('    <metadata key="plater_name" value=""/>\n')
        rows.append('    <metadata key="locked" value="false"/>\n')
        rows.append('    <metadata key="filament_map_mode" value="Auto For Flush"/>\n')
        rows.append(f'    <metadata key="filament_maps" value="{maps}"/>\n')
        rows.append("    <model_instance>\n")
        rows.append(f'      <metadata key="object_id" value="{root_id}"/>\n')
        rows.append('      <metadata key="instance_id" value="0"/>\n')
        rows.append(f'      <metadata key="identify_id" value="{zlib.crc32(self.model_name.encode()) % 900 + 100}"/>\n')
        rows.append("    </model_instance>\n")
        rows.append("  </plate>\n")
        rows.append("  <assemble>\n")
        offset = self._transform()
        transform = "1 0 0 0 1 0 0 0 1 " + " ".join(_number(value) for value in offset)
        rows.append(
            f'   <assemble_item object_id="{root_id}" instance_id="0" transform="{transform}" offset="0 0 0" />\n'
        )
        rows.append("  </assemble>\n")
        rows.append("</config>\n")
        return "".join(rows)

    def _plates(self) -> list[int]:
        return [1]

    def _project_settings(self) -> str:
        return json.dumps(self.settings, indent=4, ensure_ascii=False)

    # -- package ----------------------------------------------------------- #

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        objects_name = self.object_file_name()
        model_rels = (
            _XML_HEADER
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            + f' <Relationship Target="/{objects_name}" Id="rel-1"'
            ' Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
            + "</Relationships>\n"
        )
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
            archive.writestr("_rels/.rels", _ROOT_RELS)
            archive.writestr("3D/3dmodel.model", self._model_xml())
            archive.writestr("3D/_rels/3dmodel.model.rels", model_rels)
            archive.writestr(objects_name, self._objects_xml())
            archive.writestr("Metadata/project_settings.config", self._project_settings())
            archive.writestr("Metadata/model_settings.config", self._model_settings_xml())
            archive.writestr("Metadata/slice_info.config", _SLICE_INFO)
        return target


def write_project(
    path: str | Path,
    parts: Sequence[Part],
    settings: dict,
    *,
    model_name: str,
    base_colors: Sequence[RGB],
    definitions: str,
    application: str = "BambuStudio-2.3.6",
    bed_center: tuple[float, float] = (135.0, 135.0),
) -> Path:
    """Patch the spool/mix settings and write the package."""

    patched = dict(settings)
    colors = [rgb_to_hex(color) for color in base_colors]
    patched["filament_colour"] = colors
    if "filament_multi_colors" in patched:
        patched["filament_multi_colors"] = colors
    patched["mixed_filament_definitions"] = definitions
    writer = ProjectWriter(parts, patched, model_name=model_name, application=application, bed_center=bed_center)
    return writer.write(path)
