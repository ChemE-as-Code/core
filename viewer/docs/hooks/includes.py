"""MkDocs hook: include sections of repository files (README.md above all) into pages.

Copied from ChemE-as-Code/core (docs/hooks/includes.py), so every ChemE-as-Code docs site
includes its sources the same way; the only change is that GitHub links follow ``repo_url``.

The README and the project template are the single sources of the command guides; the pages
only arrange their sections. A page includes one with a comment on a line of its own:

    <!-- readme: ### process: BFD, PFD, stream table and properties -->
    <!-- readme: ### validate | without: #### 3D layout -->
    <!-- readme: ## Install | body -->
    <!-- include: src/chemeascode/templates/project/STAGES.md :: # Stages | body -->
    <!-- include-code: src/chemeascode/templates/project/plant.yaml yaml -->

``readme:`` reads README.md, ``include: PATH ::`` any Markdown file of the repository. The
section runs from the heading to the next heading of the same or a higher level. Its headings
are shifted so that the section heading becomes ``##``. Options: ``body`` leaves the section
heading out, ``intro`` keeps only the text before the first subheading, ``without:`` drops
subsections (several separated by ``;``). ``include-code:`` puts a whole file into a code block.

Links into ``docs/`` are made relative to the page, links to other repository files become
GitHub links. A heading or file that no longer exists is a warning, so
``mkdocs build --strict`` fails on drift.
"""

from __future__ import annotations

import logging
import posixpath
import re
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.includes")

DIRECTIVE = re.compile(
    r"^<!--\s*(?P<kind>readme|include|include-code):\s*(?P<spec>.+?)\s*-->\s*$", re.M
)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")

_root = Path(".")
_repo_blob = ""


class IncludeError(ValueError):
    pass


def on_config(config):
    global _root, _repo_blob
    _root = Path(config.config_file_path).parent
    _repo_blob = (config.repo_url or "").rstrip("/") + "/blob/main/"
    return config


def _read(rel: str) -> list[str]:
    path = (_root / rel).resolve()
    if _root.resolve() not in path.parents or not path.is_file():
        raise IncludeError(f"no file {rel}")
    return path.read_text(encoding="utf-8").splitlines()


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, text) of every heading outside fenced code blocks."""
    out, fence = [], None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            mark = stripped[:3]
            if fence is None:
                fence = mark
            elif fence == mark:
                fence = None
            continue
        if fence is None and (m := HEADING.match(line)):
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def _section(lines: list[str], level: int, title: str) -> tuple[int, int] | None:
    heads = _headings(lines)
    for n, (i, lvl, text) in enumerate(heads):
        if lvl == level and text == title:
            end = next((j for j, lv, _ in heads[n + 1 :] if lv <= level), len(lines))
            return i, end
    return None


def _heading(text: str) -> tuple[int, str]:
    m = HEADING.match(text.strip())
    if m is None:
        raise IncludeError(f"not a heading: {text!r}")
    return len(m.group(1)), m.group(2)


def _rewrite_links(text: str, source: str, page_uri: str) -> str:
    source_dir = posixpath.dirname(source)
    page_dir = posixpath.dirname(page_uri) or "."

    def fix(m: re.Match) -> str:
        path, _, anchor = m.group(1).partition("#")
        repo_path = posixpath.normpath(posixpath.join(source_dir, path))
        if repo_path.startswith("docs/"):
            new = posixpath.relpath(repo_path[len("docs/") :], page_dir)
        else:
            new = _repo_blob + repo_path
        return f"]({new}{'#' + anchor if anchor else ''})"

    return LINK.sub(fix, text)


def _section_text(source: str, spec: str, page_uri: str) -> str:
    parts = [p.strip() for p in spec.split("|")]
    level, title = _heading(parts[0])
    without, body, intro = [], False, False
    for opt in parts[1:]:
        if opt == "body":
            body = True
        elif opt == "intro":
            intro = True
        elif opt.startswith("without:"):
            without += [_heading(item) for item in opt[len("without:") :].split(";")]
        else:
            raise IncludeError(f"unknown option {opt!r}")
    all_lines = _read(source)
    span = _section(all_lines, level, title)
    if span is None:
        raise IncludeError(f"{source} has no section {parts[0]!r}")
    lines = all_lines[span[0] : span[1]]
    for wlevel, wtitle in without:
        cut = _section(lines, wlevel, wtitle)
        if cut is None:
            raise IncludeError(f"{source} has no {'#' * wlevel} {wtitle} under {title}")
        lines = lines[: cut[0]] + lines[cut[1] :]
    heads = [i for i, _, _ in _headings(lines)]
    if intro:
        lines = lines[: heads[1]] if len(heads) > 1 else lines
        heads = heads[:1]
    shift = 2 - level - (1 if body else 0)
    out = []
    for i, line in enumerate(lines):
        if i in heads:
            if i == 0 and body:
                continue
            m = HEADING.match(line)
            line = f"{'#' * max(1, min(6, len(m.group(1)) + shift))} {m.group(2)}"
        out.append(line)
    return _rewrite_links("\n".join(out).strip("\n"), source, page_uri)


def _code_text(spec: str) -> str:
    path, _, lang = spec.partition(" ")
    body = "\n".join(_read(path))
    return f'```{lang.strip()} title="{path}"\n{body}\n```'


def on_page_markdown(markdown, page, config, files):
    def replace(m: re.Match) -> str:
        kind, spec = m.group("kind"), m.group("spec")
        try:
            if kind == "readme":
                return _section_text("README.md", spec, page.file.src_uri)
            if kind == "include":
                source, sep, rest = spec.partition("::")
                if not sep:
                    raise IncludeError("expected PATH :: HEADING")
                return _section_text(source.strip(), rest.strip(), page.file.src_uri)
            return _code_text(spec)
        except IncludeError as err:
            log.warning("%s: %s", page.file.src_uri, err)
            return ""

    return DIRECTIVE.sub(replace, markdown)
