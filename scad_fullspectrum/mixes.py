"""Mix plannning: pick filament blends for target colours and encode them.

Encoding follows the ``mixed_filament_definitions`` row format used by the
Snapmaker / FullSpectrum Orca builds (verified against the fork's own project
files and its loader):

* two components - ``A,B,1,1,P,0,g,w,m2,z0,xa0,xb0,d0,o0,uN,cm0`` where ``A``
  and ``B`` are 1-based filament slots (ascending), and ``P`` is the percentage
  of ``B`` (``A`` gets ``100 - P``);
* three or four components - ``1,2,1,1,50,0,g<ids>,w<pcts>,m0,z0,xa0,xb0,d0,o0,uN,cm0``
  where ``g`` lists the slots ascending and ``w`` their percentages in the same
  order.

Virtual filament IDs are handed out by the slicer in row order, starting after
the physical filaments: with four physical spools, row *k* is extruder
``4 + k``.  Rows are emitted with ``custom=1`` and ``enabled=1`` so the slicer
keeps them verbatim instead of regenerating its own pair list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .color import RGB, MIX_MODELS, delta_e_2000, grade, mix_model, rgb_to_lab

__all__ = [
    "RecipeKey",
    "Recipe",
    "Suggestion",
    "Assignment",
    "MixPlan",
    "encode_recipe",
    "encode_definitions",
    "solve",
    "plan",
]

RecipeKey = tuple[tuple[int, ...], tuple[int, ...]]

# Tail tokens shared by every serialised row.  ``z``/``xa``/``xb`` are the
# local-Z and per-component surface offsets, ``d``/``o`` the deleted/origin
# flags, ``cm`` the colour-mode flag; all stay at their neutral values.
_TAIL = "z0,xa0,xb0,d0,o0,u{uid},cm0"


@dataclass(frozen=True)
class Recipe:
    """A blend of 2-4 physical filament slots."""

    slots: tuple[int, ...]
    percents: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.slots) != len(self.percents):
            raise ValueError("slots and percents must have the same length")
        if len(self.slots) < 2:
            raise ValueError("a mix recipe needs at least two components")
        if sorted(self.slots) != list(self.slots) or len(set(self.slots)) != len(self.slots):
            raise ValueError("slots must be unique and ascending")
        if sum(self.percents) != 100:
            raise ValueError(f"percents must sum to 100, got {self.percents}")

    @property
    def is_pair(self) -> bool:
        return len(self.slots) == 2

    def label(self) -> str:
        return " + ".join(f"F{slot} {pct}%" for slot, pct in zip(self.slots, self.percents))

    def key(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        return (self.slots, self.percents)

    def encode(self, stable_id: int) -> str:
        tail = _TAIL.format(uid=stable_id)
        if self.is_pair:
            first, second = self.slots
            return f"{first},{second},1,1,{self.percents[1]},0,g,w,m2,{tail}"
        ids = "".join(str(slot) for slot in self.slots)
        weights = "/".join(str(pct) for pct in self.percents)
        return f"1,2,1,1,50,0,g{ids},w{weights},m0,{tail}"


def encode_recipe(recipe: Recipe, stable_id: int) -> str:
    return recipe.encode(stable_id)


def encode_definitions(rows: Sequence[tuple[Recipe, int]]) -> str:
    """Serialise ``(recipe, stable_id)`` pairs into one definitions string."""

    return ";".join(recipe.encode(stable_id) for recipe, stable_id in rows)


@dataclass
class Suggestion:
    """Best recipe found for one target colour."""

    target: RGB
    blend: RGB
    delta_e: float
    recipe: Recipe | None = None
    slot: int | None = None

    @property
    def is_pure(self) -> bool:
        return self.recipe is None

    def label(self) -> str:
        if self.recipe is None:
            return f"F{self.slot} (100%)"
        return self.recipe.label()


@dataclass
class Assignment:
    """How one source colour is printed."""

    target: RGB
    extruder: int
    recipe: Recipe | None
    blend: RGB
    delta_e: float
    parts: list[str] = field(default_factory=list)

    def label(self) -> str:
        if self.recipe is None:
            return f"F{self.extruder}"
        return self.recipe.label()


@dataclass
class MixPlan:
    """Result of planning all source colours of a model."""

    physical_count: int
    assignments: dict[tuple[int, int, int], Assignment]
    rows: list[tuple[Recipe, int]]

    def extruder_of(self, rgb: RGB) -> int:
        return self.assignments[rgb].extruder


class _Candidates:
    """Every recipe the spool set can reach on the grid, with its blend.

    Recipes and blends do not depend on the target colour, so one instance is
    reused for every colour of a model - which matters because the pigment model
    costs far more per evaluation than a plain average.
    """

    def __init__(self, bases: Sequence[RGB], components: int, step: int, model: str = "average") -> None:
        if not bases:
            raise ValueError("at least one base filament is required")
        self.bases = list(bases)
        self.blend = mix_model(model)
        self.singles: list[tuple[int, RGB]] = [(index + 1, rgb) for index, rgb in enumerate(bases)]
        self.mixes: list[tuple[Recipe, RGB]] = []
        self.by_recipe: dict[RecipeKey, RGB] = {}
        self._enumerate(components, step)

    def _add(self, slots: tuple[int, ...], percents: tuple[int, ...]) -> None:
        recipe = Recipe(slots, percents)
        blend = self.blend([(self.bases[slot - 1], float(pct)) for slot, pct in zip(slots, percents)])
        self.mixes.append((recipe, blend))
        self.by_recipe.setdefault(recipe.key(), blend)

    def blend_of(self, recipe: Recipe) -> RGB:
        """The blend of a recipe, reusing the candidate table when possible."""

        cached = self.by_recipe.get(recipe.key())
        if cached is not None:
            return cached
        return self.blend([(self.bases[slot - 1], float(pct)) for slot, pct in zip(recipe.slots, recipe.percents)])

    def _enumerate(self, components: int, step: int) -> None:
        count = len(self.bases)
        for i in range(count):
            for j in range(i + 1, count):
                for pct_b in range(step, 100, step):
                    self._add((i + 1, j + 1), (100 - pct_b, pct_b))
        if components >= 3:
            for i in range(count):
                for j in range(i + 1, count):
                    for k in range(j + 1, count):
                        for pct_a in range(step, 100 - 2 * step + 1, step):
                            for pct_b in range(step, 100 - pct_a - step + 1, step):
                                self._add((i + 1, j + 1, k + 1), (pct_a, pct_b, 100 - pct_a - pct_b))
        if components >= 4 and count >= 4:
            for pct_a in range(step, 100 - 3 * step + 1, step):
                for pct_b in range(step, 100 - pct_a - 2 * step + 1, step):
                    for pct_c in range(step, 100 - pct_a - pct_b - step + 1, step):
                        self._add((1, 2, 3, 4), (pct_a, pct_b, pct_c, 100 - pct_a - pct_b - pct_c))

    def best(self, target: RGB, simplicity_slack: float = 1.0) -> Suggestion:
        """Closest reachable colour, preferring simple recipes among near-ties."""

        target_lab = rgb_to_lab(target)
        ranked: list[Suggestion] = [
            Suggestion(target, rgb, delta_e_2000(target_lab, rgb_to_lab(rgb)), slot=slot)
            for slot, rgb in self.singles
        ]
        ranked.extend(
            Suggestion(target, blend, delta_e_2000(target_lab, rgb_to_lab(blend)), recipe=recipe)
            for recipe, blend in self.mixes
        )
        ranked.sort(key=lambda item: item.delta_e)
        best = ranked[0]
        for candidate in ranked:
            if candidate.delta_e > best.delta_e + simplicity_slack:
                break
            complexity = 1 if candidate.recipe is None else len(candidate.recipe.slots)
            best_complexity = 1 if best.recipe is None else len(best.recipe.slots)
            if complexity < best_complexity:
                best = candidate
        return best


def solve(
    target: RGB,
    bases: Sequence[RGB],
    components: int = 4,
    step: int = 5,
    simplicity_slack: float = 1.0,
    model: str = "average",
) -> Suggestion:
    """Find the recipe whose blend is perceptually closest to ``target``.

    ``components`` caps the number of filaments per recipe (2..4).  ``step`` is
    the percentage grid; 5 % keeps every recipe reachable while limiting the
    candidate count.  When several recipes are within ``simplicity_slack`` ΔE of
    the best one, the simplest (fewest components, then fewest tool changes)
    wins, because fewer components means less flushing and faster printing.
    ``model`` selects the blend model (see :data:`scad_fullspectrum.color.MIX_MODELS`).
    """

    return _Candidates(bases, components, step, model).best(target, simplicity_slack)


def plan(
    targets: Sequence[RGB],
    bases: Sequence[RGB],
    components: int = 4,
    step: int = 5,
    pure_threshold: float = 1.0,
    max_mixes: int | None = None,
    model: str = "average",
) -> MixPlan:
    """Assign every target colour to a physical filament or a mixed row.

    Identical recipes are shared, colours within ``pure_threshold`` ΔE of a
    loaded spool use that spool directly, and ``max_mixes`` caps the number of
    virtual filaments by repeatedly collapsing the pair of rows whose blends are
    perceptually closest.
    """

    candidates = _Candidates(bases, components, step, model)
    blend = candidates.blend

    suggestions: dict[tuple[int, int, int], Suggestion] = {}
    for target in targets:
        suggestion = candidates.best(target)
        if suggestion.recipe is not None:
            # A spool that already matches this colour closely enough wins over a
            # blend: it saves a virtual filament and the tool changes it costs.
            target_lab = rgb_to_lab(target)
            closest = min(
                (
                    (delta_e_2000(target_lab, rgb_to_lab(base)), index + 1, base)
                    for index, base in enumerate(bases)
                ),
                key=lambda item: item[0],
            )
            if closest[0] <= pure_threshold:
                suggestion = Suggestion(target, closest[2], closest[0], slot=closest[1])
        suggestions[target] = suggestion

    recipes: dict[RecipeKey, Recipe] = {}
    for suggestion in suggestions.values():
        if suggestion.recipe is not None:
            recipes.setdefault(suggestion.recipe.key(), suggestion.recipe)

    merges: dict[RecipeKey, RecipeKey] = {}
    if max_mixes is not None and len(recipes) > max_mixes:
        merges = _collapse(recipes, candidates.blend_of, max_mixes)
        recipes = {key: recipe for key, recipe in recipes.items() if key not in merges}

    ordered = sorted(recipes.values(), key=lambda recipe: (len(recipe.slots), recipe.slots, recipe.percents))
    rows = [(recipe, index + 1) for index, recipe in enumerate(ordered)]
    extruder_of_recipe = {recipe.key(): len(bases) + index + 1 for index, (recipe, _) in enumerate(rows)}

    assignments: dict[tuple[int, int, int], Assignment] = {}
    for target, suggestion in suggestions.items():
        if suggestion.recipe is None:
            slot = suggestion.slot or 1
            # The assignment always describes the filament that will actually be
            # printed, so the blend and ΔE are recomputed from the final choice
            # (a merged recipe differs from the suggestion that chose it).
            blend = bases[slot - 1]
            assignments[target] = Assignment(
                target=target,
                extruder=slot,
                recipe=None,
                blend=blend,
                delta_e=delta_e_2000(rgb_to_lab(target), rgb_to_lab(blend)),
            )
            continue
        recipe = recipes[_resolve_key(suggestion.recipe.key(), merges)]
        blend = candidates.blend_of(recipe)
        assignments[target] = Assignment(
            target=target,
            extruder=extruder_of_recipe[recipe.key()],
            recipe=recipe,
            blend=blend,
            delta_e=delta_e_2000(rgb_to_lab(target), rgb_to_lab(blend)),
        )

    return MixPlan(physical_count=len(bases), assignments=assignments, rows=rows)


def _resolve_key(key: RecipeKey, merges: dict[RecipeKey, RecipeKey]) -> RecipeKey:
    """Follow the merge chain of a collapsed recipe down to the surviving row."""

    seen: set[RecipeKey] = set()
    while key in merges and key not in seen:
        seen.add(key)
        key = merges[key]
    return key


def _collapse(
    recipes: dict[RecipeKey, Recipe],
    blend_of,
    max_mixes: int,
) -> dict[RecipeKey, RecipeKey]:
    """Merge the perceptually closest recipes until ``max_mixes`` remain.

    Returns the merge map (dropped recipe -> surviving recipe); the caller keeps
    the surviving rows only.
    """

    working = dict(recipes)
    merges: dict[RecipeKey, RecipeKey] = {}
    while len(working) > max_mixes:
        keys = list(working)
        blends = {key: blend_of(working[key]) for key in keys}
        best_pair: tuple[float, RecipeKey, RecipeKey] | None = None
        for i, key_a in enumerate(keys):
            for key_b in keys[i + 1 :]:
                distance = delta_e_2000(rgb_to_lab(blends[key_a]), rgb_to_lab(blends[key_b]))
                if best_pair is None or distance < best_pair[0]:
                    best_pair = (distance, key_a, key_b)
        if best_pair is None:  # pragma: no cover - defensive
            break
        _, keep, drop = best_pair
        working.pop(drop)
        merges[drop] = keep
    return merges


def describe(plan: MixPlan, bases: Sequence[RGB]) -> list[dict[str, object]]:
    """Report rows for the CLI summary."""

    out: list[dict[str, object]] = []
    for target, assignment in sorted(plan.assignments.items(), key=lambda item: item[1].extruder):
        out.append(
            {
                "source": rgb_to_hex(target),
                "extruder": assignment.extruder,
                "recipe": assignment.label(),
                "blend": rgb_to_hex(assignment.blend),
                "delta_e": round(assignment.delta_e, 2),
                "grade": grade(assignment.delta_e),
                "parts": len(assignment.parts),
            }
        )
    return out
