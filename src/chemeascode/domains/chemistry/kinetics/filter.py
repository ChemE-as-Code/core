"""Reduce the RMG and NIST kinetics records of one reaction to one Arrhenius record.

The pipeline of :meth:`KineticsFilter.run` (the pandas pipeline of LLM4ChemE, in plain Python
with the same semantics; a row is a dict, a missing key, None and NaN are all "missing"):

0. :meth:`~KineticsFilter.select_reaction`: keep the records of one reaction; records of
   several reactions are never pooled.
1. :meth:`~KineticsFilter.normalize_T_ref`: rescale every A to T_ref = 1 K (NIST writes
   k = A (T/298 K)^n exp(-Ea/RT), RMG k = A T^n exp(-Ea/RT)).
2. :meth:`~KineticsFilter.identify_data_type`: Experiment, Theory, Library, Family, Estimate...
3. :meth:`~KineticsFilter.remove_dupes`: drop exact duplicates (the first is kept).
4. :meth:`~KineticsFilter.filter_completeness`: keep the rows with every parameter their
   kinetics type needs.
5. :meth:`~KineticsFilter.ea_consistency`: HIGH / MEDIUM / LOW confidence from the agreement
   of Ea and A with the neighbouring rows in sorted order.
6. The median Ea of the rows left after step 5.
7. :meth:`~KineticsFilter.data_type_rank`: Experiment > Library > Theory > Estimate > Family.
8. :meth:`~KineticsFilter.most_non_na`: the most complete rows.
9. :meth:`~KineticsFilter.median_ea_comp`: the row whose Ea is closest to the median.

Every sort is stable, so ties keep the order of the previous stage: RMG records before NIST
records as given, then grouped by kinetics type (Arrhenius, ModifiedArrhenius, PDepArrhenius)
by step 4, then ordered by ascending normalised A (ties: ascending Ea) by step 5. When two rows
are equally close to the median Ea, the first in that order wins. (pandas sorts with an unstable
quicksort, so LLM4ChemE leaves these ties to the sort implementation.)
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from chemeascode.integrations.rdkit import canonical_or_raw

from .records import (
    NIST_T_REF,
    RMG_T_REF,
    FilteredKinetics,
    NISTKineticsRecord,
    RMGKineticsRecord,
)

Row = dict[str, Any]
Records = list[RMGKineticsRecord] | list[NISTKineticsRecord] | list[dict] | dict | None

_NA = object()  # the key of a missing value in remove_dupes: NaN and None are equal there


def is_missing(value: Any) -> bool:
    """pandas' ``isna`` for one value: None and NaN are missing, a list or dict never is."""
    return value is None or (isinstance(value, float) and math.isnan(value))


def _get(row: Mapping[str, Any], key: str) -> Any:
    value = row.get(key)
    return None if is_missing(value) else value


def _columns(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """The union of the keys of *rows*, in order of first appearance (a frame's columns)."""
    return list(dict.fromkeys(key for row in rows for key in row))


def _stable_sorted(rows: list[Row], col: str) -> list[Row]:
    """*rows* sorted by ascending *col*, missing values last, ties in their current order."""
    return sorted(rows, key=lambda row: (1, 0.0) if is_missing(row.get(col)) else (0, row[col]))


def _relative_difference_pct(value: Any, neighbour: Any) -> float:
    """``|value - neighbour| / ((value + neighbour) / 2) * 100`` as pandas computes it: NaN
    when either is missing or both are 0, +inf when only the mean is 0."""
    if is_missing(value) or is_missing(neighbour):
        return math.nan
    numerator = abs(value - neighbour)
    mean = (value + neighbour) / 2
    if mean == 0:
        return math.nan if numerator == 0 else math.inf
    return numerator / mean * 100


class KineticsFilter:
    """Consolidates RMG + NIST kinetics records into one Arrhenius record.

    ``KineticsFilter(rmg_records, nist_records, reactant_smiles, product_smiles).run()``. The
    records may be models, dicts, or a dict wrapping the list under ``"rmg_records"`` /
    ``"nist_records"``. Each stage takes and returns a list of row dicts and never changes its
    input.
    """

    REQUIRED_PARAMS: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "Arrhenius": ("A", "Ea"),
        "ModifiedArrhenius": ("A", "Ea", "n"),
        "PDepArrhenius": ("A", "n", "Ea", "P_range"),
    }
    DATA_TYPE_PRIORITY = ("Experiment", "Library", "Theory", "Estimate", "Family")

    def __init__(
        self,
        rmg_records: Records,
        nist_records: Records,
        reactant_smiles: list[str] | str | None = None,
        product_smiles: list[str] | str | None = None,
    ) -> None:
        self.rmg_records = self._unwrap(rmg_records, "rmg_records")
        self.nist_records = self._unwrap(nist_records, "nist_records")
        self.reactant_smiles = reactant_smiles
        self.product_smiles = product_smiles

    def run(self) -> FilteredKinetics:
        """The winning record.

        Raises ``ValueError`` when both record lists are empty, when the records cover more
        than one reaction and the requested one is not given (or not among them), or when no
        record is complete for a supported kinetics type.
        """
        if not self.rmg_records and not self.nist_records:
            raise ValueError("No kinetics records provided to filter (both RMG and NIST are empty)")
        rows = self._to_rows(self.rmg_records, RMG_T_REF) + self._to_rows(
            self.nist_records, NIST_T_REF
        )
        rows = self.select_reaction(rows, self.reactant_smiles, self.product_smiles)
        rows = self.normalize_T_ref(rows)
        rows = self.identify_data_type(rows)
        rows = self.remove_dupes(rows)
        rows = self.filter_completeness(rows)
        rows = self.ea_consistency(rows)
        median_ea = self.median([row.get("Ea") for row in rows])
        rows = self.data_type_rank(rows)
        rows = self.most_non_na(rows)
        rows = self.median_ea_comp(rows, median_ea)
        rows = _stable_sorted(rows, "MedianEaComp")
        return self._to_filtered_kinetics(rows[0])

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    @classmethod
    def select_reaction(
        cls,
        rows: list[Row],
        reactant_smiles: list[str] | str | None = None,
        product_smiles: list[str] | str | None = None,
    ) -> list[Row]:
        """The rows of a single reaction.

        A reaction is identified by its sets of canonical reactant and product SMILES (order
        and stoichiometry ignored). A row without products (a NIST search without products
        copies the empty product list) has an unknown product channel: it is identified by its
        ``reaction`` string, so it never pools with another channel. With *reactant_smiles*,
        only the rows of that reaction are kept (with *product_smiles* too, only those with
        exactly these products, so rows without products are dropped).

        Raises ``ValueError`` when no row matches the requested reaction, or the rows left
        cover more than one reaction.
        """
        keys = [
            (cls._species_key(row.get("reactants")), cls._species_key(row.get("products")))
            for row in rows
        ]
        channels = [
            products or _get(row, "reaction") for (_, products), row in zip(keys, rows, strict=True)
        ]
        retrieved = ", ".join(
            sorted(
                {
                    cls._reaction_label(*key, reaction=channel)
                    for key, channel in zip(keys, channels, strict=True)
                }
            )
        )
        if reactant_smiles:
            wanted_reactants = cls._species_key(reactant_smiles)
            wanted_products = cls._species_key(product_smiles)
            mask = [
                reactants == wanted_reactants
                and (not wanted_products or products == wanted_products)
                for reactants, products in keys
            ]
            if not any(mask):
                hint = (
                    " Records retrieved without products can't be matched to products: "
                    "retrieve kinetics with the product_smiles first."
                    if wanted_products
                    and any(
                        reactants == wanted_reactants and not products
                        for reactants, products in keys
                    )
                    else ""
                )
                raise ValueError(
                    "None of the retrieved kinetics records are for the requested "
                    f"reaction {cls._reaction_label(wanted_reactants, wanted_products)}"
                    f" (retrieved: {retrieved or 'none'}). If the requested reaction is "
                    "listed, pass its SMILES as listed; otherwise retrieve kinetics for that "
                    "reaction first." + hint
                )
            rows = [row for row, keep in zip(rows, mask, strict=True) if keep]
            keys = [key for key, keep in zip(keys, mask, strict=True) if keep]
            channels = [c for c, keep in zip(channels, mask, strict=True) if keep]
        if len({reactants for reactants, _ in keys}) > 1 or len(set(channels)) > 1:
            raise ValueError(
                f"The kinetics records cover more than one reaction ({retrieved}). "
                "Filter again with the reactant_smiles and product_smiles (as listed) of the "
                "one reaction to filter."
            )
        return [dict(row) for row in rows]

    @staticmethod
    def normalize_T_ref(rows: list[Row], T_ref: float = RMG_T_REF) -> list[Row]:
        """Each row's A rescaled to the reference temperature *T_ref* (K).

        k = A (T/T_old)^n exp(-Ea/RT) = A (T_ref/T_old)^n (T/T_ref)^n exp(-Ea/RT), so
        A_new = A (T_ref/T_old)^n; a missing n counts as 0 and a missing T_ref as *T_ref*. The
        default, 1 K, leaves RMG rows unchanged and divides NIST A by 298^n. Units are not
        changed (both sources give SI units).
        """
        rows = [dict(row) for row in rows]
        if not rows or not any("A" in row for row in rows):
            return rows
        for row in rows:
            A, n, old = _get(row, "A"), _get(row, "n"), _get(row, "T_ref")
            n = 0.0 if n is None else float(n)
            old = T_ref if old is None else float(old)
            row["A"] = None if A is None else float(A) * (T_ref / old) ** n
            row["T_ref"] = T_ref
        return rows

    @staticmethod
    def classify_row(row: Mapping[str, Any]) -> str:
        """The row's ``data_type`` if it has a non-blank one, else "Library" for an RMG
        kinetics library match, "Family" for an exact RMG rate rule, else "Estimate"."""
        data_type = _get(row, "data_type")
        if data_type is not None and str(data_type).strip():
            return str(data_type)
        if str(_get(row, "source_library")).startswith("Kinetics Library"):
            return "Library"
        if row.get("family_exact_match") is True:
            return "Family"
        return "Estimate"

    @classmethod
    def identify_data_type(cls, rows: list[Row]) -> list[Row]:
        """The rows with ``data_type`` set by :meth:`classify_row`."""
        return [{**row, "data_type": cls.classify_row(row)} for row in rows]

    @staticmethod
    def remove_dupes(rows: list[Row]) -> list[Row]:
        """The rows without exact duplicates (all columns equal; the first is kept). Lists
        compare as tuples, dicts by their sorted items, and every missing value equals every
        other."""

        def hashable(value: Any) -> Any:
            if is_missing(value):
                return _NA
            if isinstance(value, list):
                return tuple(value)
            if isinstance(value, dict):
                return tuple(sorted(value.items()))
            return value

        columns = _columns(rows)
        seen: set[tuple] = set()
        kept = []
        for row in rows:
            key = tuple(hashable(row.get(col)) for col in columns)
            if key not in seen:
                seen.add(key)
                kept.append(dict(row))
        return kept

    @classmethod
    def filter_completeness(cls, rows: list[Row]) -> list[Row]:
        """The rows with every parameter of their ``kinetics_type`` (:data:`REQUIRED_PARAMS`),
        grouped by kinetics type in that order; rows of another type are dropped. A missing
        kinetics type (NIST) is "ModifiedArrhenius" when n is given, else "Arrhenius".

        Raises ``ValueError`` when no row is complete.
        """
        typed = []
        for row in rows:
            row = dict(row)
            if _get(row, "kinetics_type") is None:
                row["kinetics_type"] = (
                    "ModifiedArrhenius" if _get(row, "n") is not None else "Arrhenius"
                )
            typed.append(row)
        results = [
            row
            for kinetics_type, required in cls.REQUIRED_PARAMS.items()
            for row in typed
            if row["kinetics_type"] == kinetics_type
            and all(_get(row, col) is not None for col in required)
        ]
        if not results:
            raise ValueError("No complete kinetics found for any supported kinetics type")
        return results

    @staticmethod
    def neighbor_consistency(rows: list[Row], col: str, pct: float = 10) -> list[Row]:
        """The rows sorted by *col* (stable, missing last), each with ``f"{col}_{pct}_pct"``:
        whether its value is within *pct* % of the previous or the next row's value (relative
        to their mean; a missing value or neighbour never agrees)."""
        rows = [dict(row) for row in _stable_sorted(rows, col)]
        values = [row.get(col) for row in rows]
        for i, row in enumerate(rows):
            below = _relative_difference_pct(values[i], values[i - 1]) if i > 0 else math.nan
            above = (
                _relative_difference_pct(values[i], values[i + 1])
                if i + 1 < len(rows)
                else math.nan
            )
            row[f"{col}_{pct}_pct"] = below <= pct or above <= pct
        return rows

    @classmethod
    def ea_consistency(cls, rows: list[Row]) -> list[Row]:
        """HIGH: the rows agreeing with a neighbour within 10 % on both Ea and A, if any; else
        MEDIUM: those agreeing within 30 %; else LOW: all rows."""
        rows = cls.neighbor_consistency(rows, "Ea", 10)
        rows = cls.neighbor_consistency(rows, "A", 10)
        consistent_10 = [row for row in rows if row["Ea_10_pct"] and row["A_10_pct"]]
        rows = cls.neighbor_consistency(rows, "Ea", 30)
        rows = cls.neighbor_consistency(rows, "A", 30)
        consistent_30 = [row for row in rows if row["Ea_30_pct"] and row["A_30_pct"]]
        if consistent_10:
            return [{**row, "confidence": "HIGH"} for row in consistent_10]
        if consistent_30:
            return [{**row, "confidence": "MEDIUM"} for row in consistent_30]
        return [{**row, "confidence": "LOW"} for row in rows]

    @classmethod
    def data_type_rank(cls, rows: list[Row]) -> list[Row]:
        """The rows of the highest-priority data type present (:data:`DATA_TYPE_PRIORITY`), or
        all rows when none of those types is present."""
        for data_type in cls.DATA_TYPE_PRIORITY:
            best = [dict(row) for row in rows if row.get("data_type") == data_type]
            if best:
                return best
        return [dict(row) for row in rows]

    @staticmethod
    def most_non_na(rows: list[Row]) -> list[Row]:
        """The rows with the most non-missing fields (``k_298K``, rarely given, not counted)."""
        columns = [col for col in _columns(rows) if col != "k_298K"]
        counted = [
            {**row, "non_na_amount": sum(not is_missing(row.get(col)) for col in columns)}
            for row in rows
        ]
        if not counted:
            return []
        most = max(row["non_na_amount"] for row in counted)
        return [row for row in counted if row["non_na_amount"] == most]

    @staticmethod
    def median_ea_comp(rows: list[Row], median: float) -> list[Row]:
        """The rows with ``MedianEaComp``: the absolute distance of Ea from *median*, J/mol."""
        return [
            {
                **row,
                "MedianEaComp": math.nan
                if is_missing(row.get("Ea")) or is_missing(median)
                else abs(row["Ea"] - median),
            }
            for row in rows
        ]

    @staticmethod
    def median(values: Iterable[Any]) -> float:
        """The median of the non-missing *values* (mean of the middle two for an even count);
        NaN when there is none."""
        present = [float(v) for v in values if not is_missing(v)]
        return statistics.median(present) if present else math.nan

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _unwrap(records: Records, key: str) -> list:
        """Accept ``{"rmg_records": [...]}`` as well as the plain list."""
        if isinstance(records, dict) and key in records:
            return records[key] or []
        return records or []

    @staticmethod
    def _species_key(smiles: Any) -> frozenset[str]:
        """The canonical, de-duplicated set of species of *smiles* (a SMILES or a list).

        Dot-separated SMILES ("C.[OH]") are split into their species; an unparseable SMILES
        stays as written (stripped); a missing value gives the empty set.
        """
        if is_missing(smiles) or isinstance(smiles, float):
            return frozenset()
        if isinstance(smiles, str):
            smiles = [smiles]
        fragments = [
            fragment.strip()
            for item in smiles
            for fragment in str(item).split(".")
            if fragment.strip()
        ]
        return frozenset(canonical_or_raw(fragment) for fragment in fragments)

    @staticmethod
    def _reaction_label(
        reactants: frozenset[str], products: frozenset[str], reaction: Any = None
    ) -> str:
        """``"A + B -> C + D"``; the record's *reaction* string is appended when the products
        are unknown."""
        label = f"{' + '.join(sorted(reactants))} -> {' + '.join(sorted(products)) or '?'}"
        if not products and isinstance(reaction, str) and reaction:
            label += f" [{reaction}]"
        return label

    @staticmethod
    def _to_rows(items: list, default_T_ref: float) -> list[Row]:
        """Records as row dicts, a missing ``T_ref`` set to the source's convention (records
        serialised before the field existed lack it)."""
        rows = [dict(item) if isinstance(item, Mapping) else item.model_dump() for item in items]
        for row in rows:
            if is_missing(row.get("T_ref")):
                row["T_ref"] = default_T_ref
        return rows

    @staticmethod
    def _to_filtered_kinetics(row: Row) -> FilteredKinetics:
        fields = {
            key: None if is_missing(value) else value
            for key, value in row.items()
            if key in FilteredKinetics.model_fields
        }
        for key in ("reactant_stoichiometry", "product_stoichiometry"):
            if fields.get(key) is None:
                fields[key] = {}
        return FilteredKinetics(**fields)


def filter_kinetics(
    rmg_records: Records,
    nist_records: Records,
    reactant_smiles: list[str] | str,
    product_smiles: list[str] | str | None = None,
) -> FilteredKinetics:
    """The one Arrhenius record (A at T_ref = 1 K, SI units) of the reaction *reactant_smiles*
    (-> *product_smiles*, recommended) among *rmg_records* and *nist_records*, with its
    confidence. Records of any other reaction are never used.

    Raises ``ValueError`` when *reactant_smiles* names no species, and as
    :meth:`KineticsFilter.run`.
    """
    if not KineticsFilter._species_key(reactant_smiles):
        raise ValueError(
            "reactant_smiles must name the reaction to filter: pass the SMILES of its "
            "reactants (e.g. ['C', '[OH]'])."
        )
    return KineticsFilter(
        rmg_records or [],
        nist_records or [],
        reactant_smiles=reactant_smiles,
        product_smiles=product_smiles,
    ).run()
