"""Molecular formulas: atoms per element and molar masses."""

from __future__ import annotations

import re

#: Standard atomic weights (IUPAC 2021, abridged to four decimals), kg/kmol.
ATOMIC_MASS = {
    "H": 1.008,
    "He": 4.0026,
    "Li": 6.94,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "Ne": 20.180,
    "Na": 22.990,
    "Mg": 24.305,
    "Al": 26.982,
    "Si": 28.085,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "Ar": 39.948,
    "K": 39.098,
    "Ca": 40.078,
    "Ti": 47.867,
    "V": 50.942,
    "Cr": 51.996,
    "Mn": 54.938,
    "Fe": 55.845,
    "Co": 58.933,
    "Ni": 58.693,
    "Cu": 63.546,
    "Zn": 65.38,
    "Br": 79.904,
    "Kr": 83.798,
    "Mo": 95.95,
    "Ru": 101.07,
    "Rh": 102.91,
    "Pd": 106.42,
    "Ag": 107.87,
    "I": 126.90,
    "Xe": 131.29,
    "Pt": 195.08,
}

_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)|(\()|(\))(\d*)")


def parse_formula(formula: str) -> dict[str, int] | None:
    """Atoms per element of a molecular formula (``C2H6O``, ``Ca(OH)2``); None when the text is
    no formula this parser reads (charges, hydrates, isotopes, an unknown element)."""
    text = formula.replace(" ", "")
    if not text:
        return None
    stack: list[dict[str, int]] = [{}]
    at = 0
    while at < len(text):
        match = _TOKEN.match(text, at)
        if match is None:
            return None
        element, count, opening, closing, multiplier = match.groups()
        if element:
            if element not in ATOMIC_MASS:
                return None
            top = stack[-1]
            top[element] = top.get(element, 0) + int(count or 1)
        elif opening:
            stack.append({})
        elif closing:
            if len(stack) < 2:
                return None
            group = stack.pop()
            for name, n in group.items():
                stack[-1][name] = stack[-1].get(name, 0) + n * int(multiplier or 1)
        at = match.end()
    if len(stack) != 1 or not stack[0]:
        return None
    return stack[0]


def molar_mass(formula: str) -> float | None:
    """kg/kmol from the formula; None when :func:`parse_formula` cannot read it."""
    atoms = parse_formula(formula)
    return sum(ATOMIC_MASS[e] * n for e, n in atoms.items()) if atoms else None
