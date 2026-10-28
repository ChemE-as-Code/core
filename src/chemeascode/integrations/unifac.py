"""Published UNIFAC parameters of the DDBST (main groups, sub groups with R and Q, interaction
parameters), read from https://www.ddbst.com/published-parameters-unifac.html."""

from __future__ import annotations

import re

from lxml import html
from pydantic import BaseModel

from chemeascode.integrations.http import HttpClient

DDBST_UNIFAC_URL = "https://www.ddbst.com/published-parameters-unifac.html"
# Main-group cell of the sub-group table: "[1]CH2", "1CH2" or "1".
_MAIN_GROUP_ID_RE = re.compile(r"^\s*\[?\s*(\d+)")


class SubGroup(BaseModel):
    name: str
    R: float
    Q: float


class MainGroup(BaseModel):
    name: str
    subgroups: list[SubGroup]


class InteractionParameter(BaseModel):
    """a_ij and a_ji (K) between two main groups."""

    group_i: str
    group_j: str
    a_ij: float
    a_ji: float


class UNIFACParameters(BaseModel):
    main_groups: list[MainGroup]
    interaction_parameters: list[InteractionParameter]


def _table(doc, header_text: str):
    for header in doc.xpath("//h1 | //h2 | //h3"):
        if header_text in header.text_content():
            tables = header.xpath("following::table[1]")
            if tables:
                return tables[0]
    raise ValueError(
        f"Table {header_text!r} not found on the DDBST UNIFAC page; the layout may have changed."
    )


def _rows(table) -> list[dict[str, str]]:
    rows = table.xpath(".//tr")
    if not rows:
        return []
    headers = [" ".join(c.text_content().split()) for c in rows[0].xpath("./th | ./td")]
    entries = []
    for row in rows[1:]:
        cells = [" ".join(c.text_content().split()) for c in row.xpath("./td")]
        if len(cells) == len(headers):
            entries.append(dict(zip(headers, cells, strict=True)))
    return entries


def parse_unifac_parameters(page: str) -> UNIFACParameters:
    """The parameters on the DDBST page; sub groups of an unknown main group are skipped."""
    doc = html.fromstring(page)
    main_rows = _rows(_table(doc, "List of Main Groups"))
    names = {
        r["No."]: r["Maingroup Name"] for r in main_rows if "No." in r and "Maingroup Name" in r
    }
    groups = {name: MainGroup(name=name, subgroups=[]) for name in names.values()}
    sub_table = _table(doc, "List of Sub Groups and their Group Surfaces and Volumes")
    for row in _rows(sub_table):
        match = _MAIN_GROUP_ID_RE.match(row.get("Maingroup") or "")
        main = names.get(match.group(1)) if match else None
        if main is None or not (row.get("Subgroup Name") and row.get("R") and row.get("Q")):
            continue
        groups[main].subgroups.append(
            SubGroup(name=row["Subgroup Name"], R=float(row["R"]), Q=float(row["Q"]))
        )
    interactions = []
    for row in _rows(_table(doc, "List of Interaction Parameters")):
        try:
            interactions.append(
                InteractionParameter(
                    group_i=names.get(row.get("i", ""), row.get("i", "")),
                    group_j=names.get(row.get("j", ""), row.get("j", "")),
                    a_ij=float(row["Aij"]),
                    a_ji=float(row["Aji"]),
                )
            )
        except (KeyError, ValueError):
            continue
    return UNIFACParameters(main_groups=list(groups.values()), interaction_parameters=interactions)


def retrieve_unifac_parameters(*, client: HttpClient | None = None) -> UNIFACParameters:
    """Download and parse the DDBST page."""
    client = client or HttpClient()
    return parse_unifac_parameters(client.get(DDBST_UNIFAC_URL).text)
