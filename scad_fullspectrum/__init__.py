"""Convert coloured OpenSCAD designs into FullSpectrum (mixed filament) 3MF projects.

The package turns ``color()`` scopes in a SCAD file into per-colour meshes and
writes a Snapmaker Orca project 3MF in which each colour is printed as a blend of
the filaments loaded in the four toolheads.
"""

from .pipeline import BuildOptions, BuildReport, build

__all__ = ["BuildOptions", "BuildReport", "build"]
__version__ = "0.1.0"
