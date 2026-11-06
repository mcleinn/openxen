"""Helpers to read and emit KiCad 9 schematic content (format 20250114) on top of ``sexp``.

What it provides
* ``LibSymbols``: collect embedded ``lib_symbols`` definitions from existing schematics and
  from ``.kicad_sym`` libraries, and compute pin connection points of an instance.
* ``Sheet``: an in-memory schematic being built: add symbol instances (optionally cloned
  from a template instance), global labels, wires, no-connects, junctions, text; serialise.
* ``clone_region``: copy every item of an existing schematic inside a rectangle (used to
  reuse HE60's controller block verbatim).

Coordinates are schematic millimetres, y down. Symbol library coordinates are y up, so a pin
at (px, py) of an instance at (x, y, rot) sits at (x + R(px, py).x, y - R(px, py).y).
"""
from __future__ import annotations

import math
import uuid as uuidlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sexp
from sexp import Quoted as Q, at, kid, kids, prop

SCH_VERSION = 20250114


def new_uuid() -> Q:
    return Q(str(uuidlib.uuid4()))


# --- library symbols ---------------------------------------------------------------------
class LibSymbols:
    def __init__(self) -> None:
        self.defs: dict[str, list] = {}

    def add_from_schematic(self, doc: list) -> None:
        ls = kid(doc, "lib_symbols")
        if ls:
            for s in kids(ls, "symbol"):
                self.defs.setdefault(s[1].s, s)

    def add_from_library(self, path: Path, nickname: str, names: list[str]) -> None:
        """Embed symbols from a .kicad_sym library. The top-level name becomes "nick:name";
        sub-units keep their bare "name_U_S" form (that is what KiCad writes into a schematic).
        A derived symbol (extends) is flattened onto its base."""
        doc = sexp.loads(path.read_text(encoding="utf-8"))
        by_name = {s[1].s: s for s in kids(doc, "symbol")}
        wanted = set(names)
        for name in names:
            if name not in by_name:
                continue
            s = by_name[name]
            ext = kid(s, "extends")
            if ext:
                base = by_name[ext[1].s]
                merged = [x for x in base if not (isinstance(x, list) and x and x[0] == "property")]
                props = {p[1].s: p for p in kids(base, "property")}
                props.update({p[1].s: p for p in kids(s, "property")})
                # rename base sub-units "<base>_U_S" -> "<name>_U_S"
                out = []
                for c in merged:
                    if isinstance(c, list) and c and c[0] == "symbol" and isinstance(c[1], Q) and c[1].s.startswith(base[1].s + "_"):
                        cc = [x for x in c]
                        cc[1] = Q(name + c[1].s[len(base[1].s):])
                        out.append(cc)
                    else:
                        out.append(c)
                # properties go after the flags, before sub-units
                head = [c for c in out if not (isinstance(c, list) and c and c[0] == "symbol")]
                units = [c for c in out if isinstance(c, list) and c and c[0] == "symbol"]
                d = head + list(props.values()) + units
            else:
                d = [x for x in s]
            d[1] = Q(f"{nickname}:{name}")
            self.defs.setdefault(f"{nickname}:{name}", d)
            wanted.discard(name)
        if wanted:
            raise KeyError(f"symbols not found in {path}: {sorted(wanted)}")

    def pins(self, lib_id: str) -> list[tuple[str, str, float, float, float]]:
        """(number, name, x, y, rot) in library coordinates (y up), all units."""
        d = self.defs[lib_id]
        out = []
        for unit in kids(d, "symbol"):
            for p in kids(unit, "pin"):
                px, py, prot = at(p)
                out.append((kid(p, "number")[1].s, kid(p, "name")[1].s, px, py, prot))
        return out

    def pin_points(self, inst: list) -> dict[str, tuple[float, float]]:
        """Connection point of every pin of a placed instance, keyed by pin number."""
        lib_id = sexp.q(inst, "lib_id")
        x, y, rot = at(inst)
        m = kid(inst, "mirror")
        m = m[1] if m else None
        a = math.radians(rot)
        res = {}
        for num, _name, px, py, _ in self.pins(lib_id):
            cx, cy = px, py
            if m == "x":
                cy = -cy
            if m == "y":
                cx = -cx
            rx = cx * math.cos(a) - cy * math.sin(a)
            ry = cx * math.sin(a) + cy * math.cos(a)
            res[num] = (round(x + rx, 4), round(y - ry, 4))
        return res

    def lib_symbols_node(self, used: set[str]) -> list:
        return ["lib_symbols"] + [self.defs[k] for k in sorted(used) if k in self.defs]


# --- building a sheet --------------------------------------------------------------------
@dataclass
class Sheet:
    project: str
    libs: LibSymbols
    items: list = field(default_factory=list)
    used_libs: set = field(default_factory=set)
    root_uuid: Q = field(default_factory=new_uuid)
    ref_counter: dict = field(default_factory=dict)

    # symbol instances -------------------------------------------------------------
    def symbol(self, lib_id: str, x: float, y: float, rot: float, ref: str, value: str,
               footprint: str = "", extra: dict[str, str] | None = None, mirror: str | None = None,
               hide_value: bool = False) -> list:
        self.used_libs.add(lib_id)
        inst = ["symbol", ["lib_id", Q(lib_id)], ["at", x, y, rot]]
        if mirror:
            inst.append(["mirror", mirror])
        inst += [["unit", 1], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                 ["uuid", new_uuid()]]
        props = [("Reference", ref, (x + 2.54, y - 1.27), False), ("Value", value, (x + 2.54, y + 1.27), hide_value),
                 ("Footprint", footprint, (x, y), True), ("Datasheet", "", (x, y), True), ("Description", "", (x, y), True)]
        for k, v in (extra or {}).items():
            props.append((k, v, (x, y), True))
        for name, val, (px, py), hide in props:
            p = ["property", Q(name), Q(val), ["at", px, py, 0], ["effects", ["font", ["size", 1.27, 1.27]]]]
            if hide:
                p[-1].append(["hide", "yes"])
            inst.append(p)
        for num, *_ in self.libs.pins(lib_id):
            inst.append(["pin", Q(num), ["uuid", new_uuid()]])
        inst.append(["instances", ["project", Q(self.project), ["path", Q("/" + self.root_uuid.s), ["reference", Q(ref)], ["unit", 1]]]])
        self.items.append(inst)
        return inst

    def power(self, lib_id: str, x: float, y: float, rot: float = 0, value: str = "") -> list:
        n = self.ref_counter.get("#PWR", 0) + 1
        self.ref_counter["#PWR"] = n
        inst = self.symbol(lib_id, x, y, rot, f"#PWR{n:03d}", value or lib_id.split(":")[1], hide_value=False)
        return inst

    def clone(self, template: list, dx: float, dy: float, ref: str, renames: dict[str, str] | None = None) -> list:
        """Copy a template instance shifted by (dx, dy) with a new reference and uuid."""
        inst = _deepcopy(template)
        a = kid(inst, "at")
        a[1], a[2] = round(float(a[1]) + dx, 4), round(float(a[2]) + dy, 4)
        for p in kids(inst, "property"):
            pa = kid(p, "at")
            if pa:
                pa[1], pa[2] = round(float(pa[1]) + dx, 4), round(float(pa[2]) + dy, 4)
            if p[1].s == "Reference":
                p[2] = Q(ref)
            elif renames and p[1].s in renames:
                p[2] = Q(renames[p[1].s])
        kid(inst, "uuid")[1] = new_uuid()
        for p in kids(inst, "pin"):
            u = kid(p, "uuid")
            if u:
                u[1] = new_uuid()
        inst_node = kid(inst, "instances")
        if inst_node:
            inst[inst.index(inst_node)] = ["instances", ["project", Q(self.project), ["path", Q("/" + self.root_uuid.s), ["reference", Q(ref)], ["unit", 1]]]]
        self.used_libs.add(sexp.q(inst, "lib_id"))
        self.items.append(inst)
        return inst

    # wiring ------------------------------------------------------------------------
    def wire(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.items.append(["wire", ["pts", ["xy", x1, y1], ["xy", x2, y2]], ["stroke", ["width", 0], ["type", "default"]], ["uuid", new_uuid()]])

    def glabel(self, name: str, x: float, y: float, rot: float = 0, shape: str = "input") -> None:
        just = {0: "left", 90: "left", 180: "right", 270: "left"}[int(rot) % 360]
        self.items.append(["global_label", Q(name), ["shape", shape], ["at", x, y, rot],
                           ["effects", ["font", ["size", 1.27, 1.27]], ["justify", just]], ["uuid", new_uuid()],
                           ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", x, y, 0], ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]]])

    def no_connect(self, x: float, y: float) -> None:
        self.items.append(["no_connect", ["at", x, y], ["uuid", new_uuid()]])

    def junction(self, x: float, y: float) -> None:
        self.items.append(["junction", ["at", x, y], ["diameter", 0], ["color", 0, 0, 0, 0], ["uuid", new_uuid()]])

    def text(self, s: str, x: float, y: float, size: float = 2.0) -> None:
        self.items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", x, y, 0], ["effects", ["font", ["size", size, size]], ["justify", "left", "bottom"]], ["uuid", new_uuid()]])

    def add_raw(self, node: list) -> None:
        if node and node[0] == "symbol":
            self.used_libs.add(sexp.q(node, "lib_id"))
        self.items.append(node)

    # output ---------------------------------------------------------------------------
    def document(self, paper: str = "A2") -> list:
        doc = ["kicad_sch", ["version", SCH_VERSION], ["generator", Q("openxen")], ["generator_version", Q("0.1")],
               ["uuid", self.root_uuid], ["paper", Q(paper)], self.libs.lib_symbols_node(self.used_libs)]
        doc += self.items
        doc.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
        doc.append(["embedded_fonts", "no"])
        return doc

    def write(self, path: Path, paper: str = "A2") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sexp.dumps(self.document(paper)) + "\n", encoding="utf-8")


def _deepcopy(node: Any) -> Any:
    if isinstance(node, list):
        return [_deepcopy(c) for c in node]
    return node


# --- cloning regions of an existing schematic --------------------------------------------
ITEM_TAGS = ("symbol", "wire", "global_label", "label", "no_connect", "junction", "text", "bus", "bus_entry", "polyline", "rectangle")


def _item_points(item: list) -> list[tuple[float, float]]:
    if item[0] in ("wire", "bus", "polyline"):
        return [(float(p[1]), float(p[2])) for p in kids(kid(item, "pts"), "xy")]
    a = kid(item, "at")
    return [(float(a[1]), float(a[2]))] if a else []


def clone_region(doc: list, x0: float, y0: float, x1: float, y1: float, dx: float, dy: float,
                 sheet: Sheet, skip_lib_ids: tuple[str, ...] = ()) -> list[list]:
    """Copy all items whose every point lies inside the rectangle, shifted by (dx, dy)."""
    copied = []
    for item in doc:
        if not isinstance(item, list) or not item or item[0] not in ITEM_TAGS:
            continue
        pts = _item_points(item)
        if not pts or not all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
            continue
        if item[0] == "symbol" and any(sexp.q(item, "lib_id").startswith(s) for s in skip_lib_ids):
            continue
        new = _deepcopy(item)
        if new[0] in ("wire", "bus", "polyline"):
            for p in kids(kid(new, "pts"), "xy"):
                p[1], p[2] = round(float(p[1]) + dx, 4), round(float(p[2]) + dy, 4)
        else:
            a = kid(new, "at")
            a[1], a[2] = round(float(a[1]) + dx, 4), round(float(a[2]) + dy, 4)
        for p in kids(new, "property"):
            pa = kid(p, "at")
            if pa:
                pa[1], pa[2] = round(float(pa[1]) + dx, 4), round(float(pa[2]) + dy, 4)
        u = kid(new, "uuid")
        if u:
            u[1] = new_uuid()
        for p in kids(new, "pin"):
            pu = kid(p, "uuid")
            if pu:
                pu[1] = new_uuid()
        if new[0] == "symbol":
            ref = prop(new, "Reference")
            inst_node = kid(new, "instances")
            if inst_node:
                new[new.index(inst_node)] = ["instances", ["project", Q(sheet.project), ["path", Q("/" + sheet.root_uuid.s), ["reference", Q(ref)], ["unit", 1]]]]
        sheet.add_raw(new)
        copied.append(new)
    return copied
