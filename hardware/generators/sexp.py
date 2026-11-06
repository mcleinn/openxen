"""Minimal S-expression reader/writer for KiCad files (schematic, symbol libs, PCB).

Parses into nested Python lists; atoms are ``str`` (bare symbols), ``Quoted`` (quoted
strings) or numbers (``int``/``float``). ``dumps`` re-serialises in KiCad's indentation style
closely enough for KiCad 9 to load the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class Quoted:
    s: str

    def __str__(self) -> str:  # pragma: no cover
        return self.s


def _tokens(text: str) -> Iterator[str]:
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            yield '"' + "".join(buf) + '"'
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            yield text[i:j]
            i = j


def _atom(tok: str) -> Any:
    if tok.startswith('"'):
        return Quoted(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
    try:
        if "." in tok or "e" in tok.lower():
            return float(tok)
        return int(tok)
    except ValueError:
        return tok


def loads(text: str) -> list:
    stack: list[list] = [[]]
    for tok in _tokens(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(_atom(tok))
    if len(stack) != 1 or len(stack[0]) != 1:
        raise ValueError("unbalanced S-expression")
    return stack[0][0]


def _fmt(a: Any) -> str:
    if isinstance(a, Quoted):
        return '"' + a.s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, float):
        s = f"{a:.6f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(a)


def dumps(node: Any, indent: int = 0) -> str:
    if not isinstance(node, list):
        return _fmt(node)
    pad = "\t" * indent
    if all(not isinstance(x, list) for x in node):
        return pad + "(" + " ".join(_fmt(x) for x in node) + ")"
    head = []
    i = 0
    while i < len(node) and not isinstance(node[i], list):
        head.append(_fmt(node[i]))
        i += 1
    out = pad + "(" + " ".join(head)
    for child in node[i:]:
        out += "\n" + dumps(child, indent + 1)
    return out + "\n" + pad + ")"


# --- small query helpers ---------------------------------------------------------------
def kids(node: list, tag: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


def kid(node: list, tag: str) -> list | None:
    for c in node:
        if isinstance(c, list) and c and c[0] == tag:
            return c
    return None


def q(node: list, tag: str, default: str = "") -> str:
    """First quoted value after a tag, e.g. q(sym, 'lib_id')."""
    c = kid(node, tag)
    if c and len(c) > 1 and isinstance(c[1], Quoted):
        return c[1].s
    return default


def prop(sym: list, name: str, default: str = "") -> str:
    for p in kids(sym, "property"):
        if isinstance(p[1], Quoted) and p[1].s == name:
            return p[2].s if isinstance(p[2], Quoted) else str(p[2])
    return default


def at(node: list) -> tuple[float, float, float]:
    c = kid(node, "at")
    if not c:
        return (0.0, 0.0, 0.0)
    vals = [float(v) for v in c[1:4] if isinstance(v, (int, float))]
    while len(vals) < 3:
        vals.append(0.0)
    return (vals[0], vals[1], vals[2])
