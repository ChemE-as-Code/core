"""Whether an LCI dataset may stand in for a background.

When a flow's background is another LCI dataset (``dataset:``, e.g. an Atlas process instead of
a market activity), the dataset's product must be the thing the plant takes, counted the same
way and drawn with a compatible boundary, or the study counts burdens twice or not at all. The
unit kind is already checked when the dataset is characterised (an error); this module checks
the rest and reports one warning per link (``cheme.lca-link-compat``):

- **reference product**: the substance (the CAS number of the plant's main component against
  the product's ``cas``), the phase and the grade (``state.purity`` of the same basis) the plant
  takes, where both sides say;
- **boundary**: a product delivered at a lower pressure than the plant takes it leaves the
  compression out of both (``state.pressure``);
- **allocation**: when the study itself shares burdens between co-products, a multi-product
  dataset is shared out by the same method (ISO 14044 4.3.4.5: one procedure for similar
  inputs and outputs);
- **system model**: the dataset's (unset: cutoff) is the study's; a crediting mismatch is
  ``cheme.lca-system-model-mixed`` already.

Transport is not compared: a dataset's ``transport:`` exchanges carry its own inputs, not its
product to the next plant, so nothing says whether a product is delivered.
"""

from __future__ import annotations

import re
from typing import Any

from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.schemas import CREDITING_MODELS, DatasetExchange
from chemeascode.foundation.findings import Finding

#: Pressures within this fraction count as the same (rounding of bar(a) values).
_PRESSURE_TOLERANCE = 0.02


def product_problems(taken: tuple[Any, str] | None, product: DatasetExchange) -> list[str]:
    """How *product* differs from what the plant takes (*taken*: its state and the CAS number
    of its main component), where both say."""
    if taken is None:
        return []
    mine, cas = taken
    theirs = product.state
    found = []
    if cas and product.cas and normalise_cas(cas) != normalise_cas(product.cas):
        found.append(f"another substance (CAS {product.cas}, the plant takes {cas})")
    if theirs is None:
        return found
    if mine.phase and theirs.phase and mine.phase != theirs.phase:
        found.append(f"another phase ({theirs.phase}, the plant takes {mine.phase})")
    if (
        mine.purity is not None
        and theirs.purity is not None
        and mine.basis
        and mine.basis == theirs.basis
        and theirs.purity < mine.purity - 1e-9
    ):
        found.append(
            f"a lower grade ({mine.basis} purity {theirs.purity:g}, the plant takes "
            f"{mine.purity:g})"
        )
    if (
        mine.pressure is not None
        and theirs.pressure is not None
        and theirs.pressure < mine.pressure * (1 - _PRESSURE_TOLERANCE)
    ):
        found.append(
            f"delivered at {theirs.pressure:g} bar(a), the plant takes it at {mine.pressure:g}: "
            "the compression is in neither"
        )
    return found


def key_line(text: str | None, key: str) -> int | None:
    """The 1-based line of *text* whose ``key:`` is exactly *key*, if any."""
    if not text:
        return None
    pattern = re.compile(rf"""\bkey:\s*['"]?{re.escape(key)}['"]?\s*(?:[,}}#]|$)""")
    for number, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            return number
    return None


def link_findings(scope: Any, inventory: Any, load: Any, file: str, text: str | None) -> list:
    """A warning per ``dataset:`` background of *inventory* that does not fit the flow it
    stands in for (info when its ``proxy:`` says why it stands). *load* returns a dataset by
    path (or why it does not load: then nothing is said here, the characterisation reports
    it); *text* is *file*'s text, for the line."""
    allocating = sum(1 for v in inventory.shares.values() if v > 0) > 1
    model = scope.model
    found = []
    for row in inventory.rows:
        background = inventory.backgrounds.get(row.key)
        ref = getattr(background, "dataset", None)
        if ref is None:
            continue
        dataset = load(ref.path)
        if isinstance(dataset, str):
            continue
        product = dataset.product(ref.product)
        if product is None:
            continue
        taken = inventory.inputs.get(row.key)
        problems = [f"its product is {p}" for p in product_problems(taken, product)]
        if allocating and len(dataset.products()) > 1:
            method = ref.allocation or (dataset.allocation.method if dataset.allocation else "mass")
            if method != inventory.method:
                problems.append(
                    f"its {len(dataset.products())} products are allocated by {method}, the "
                    f"study's by {inventory.method}"
                )
        theirs = dataset.system_model or "cutoff"
        if theirs != model and (theirs in CREDITING_MODELS) == (model in CREDITING_MODELS):
            problems.append(f"it is modelled {theirs}, the study {model}")
        if not problems:
            continue
        found.append(
            Finding(
                file,
                # a declared proxy (the result marks it PROXY) says why the link stands
                "info" if background.proxy else "warning",
                "cheme.lca-link-compat",
                f"{row.key} links {ref.path}#{product.key.split(':', 1)[1]}, which may not "
                f"stand in for it: {'; '.join(problems)}",
                line=key_line(text, row.key),
                ids=[row.key, ref.path],
                hint="link a dataset of the same product, state, allocation and system model "
                "(or give the link its allocation:), or keep it and say why in its proxy:",
            )
        )
    return found
