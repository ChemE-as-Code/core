"""MkDocs hook: the reference pages, generated from the code at build time.

Three pages are added to the site as virtual files (nothing is written into ``docs/``):

- ``reference/cli.md``: every command and sub-app of the Typer app ``cheme``, read through
  its click command tree (usage, help, arguments and options; Typer vendors click, so the
  objects are inspected by attribute, not by class);
- ``reference/schemas.md``: every kind of the ``cheme schema`` catalogue, with its top-level
  fields and its JSON Schema;
- ``reference/serve-api.md``: the routes of ``cheme serve`` from the OpenAPI document of
  ``create_app`` (run on a plant repository made by ``cheme init`` in a temporary directory).

They change whenever the code does, so they cannot drift from it.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from mkdocs.structure.files import File

CLI_PAGE = "reference/cli.md"
SCHEMA_PAGE = "reference/schemas.md"
API_PAGE = "reference/serve-api.md"

GENERATED_NOTE = (
    '!!! info "Generated"\n'
    "    This page is generated from the code when the documentation is built "
    "(`docs/hooks/reference.py`). Do not edit it; change the code instead.\n"
)


def on_files(files, config):
    for path, build in ((CLI_PAGE, cli_page), (SCHEMA_PAGE, schema_page), (API_PAGE, api_page)):
        files.append(File.generated(config, path, content=build()))
    return files


# --- helpers ------------------------------------------------------------------------------


def _esc(text: object) -> str:
    """Text safe inside a Markdown paragraph or table cell."""
    s = "" if text is None else str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("|", "\\|").replace("\n", " ").strip()


def _anchor(text: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in text.lower())
    return re.sub("-+", "-", slug).strip("-")


def _summary(doc: str | None) -> str:
    """The first paragraph of a docstring, on one line, reST literals as Markdown code."""
    first = (doc or "").strip().split("\n\n")[0]
    return " ".join(first.split()).replace("``", "`")


# --- CLI ----------------------------------------------------------------------------------


def _param_rows(cmd, ctx) -> list[str]:
    rows = []
    for p in cmd.get_params(ctx):
        if getattr(p, "hidden", False) or "--help" in getattr(p, "opts", ()):
            continue
        if p.param_type_name == "argument":
            kind = "argument"
            names = f"`{p.human_readable_name}`"
        else:
            kind = "option"
            decls = list(p.opts) + list(p.secondary_opts)
            names = " / ".join(f"`{d}`" for d in decls)
        help_text = getattr(p, "help", None) or ""
        default = p.default
        if (
            callable(default)
            or default in (None, (), [])
            or getattr(p, "is_flag", False)
            and (default is False)
        ):
            default_s = ""
        else:
            default_s = f"`{_esc(default)}`" if not isinstance(default, bool) else f"`{default}`"
        required = "yes" if p.required else ""
        try:
            type_s = _esc(p.type.name) if not getattr(p, "is_flag", False) else "flag"
        except AttributeError:
            type_s = ""
        if getattr(p.type, "choices", None):
            type_s = " \\| ".join(f"`{c}`" for c in p.type.choices)
        rows.append(
            f"| {names} | {kind} | {type_s} | {required} | {default_s} | {_esc(help_text)} |"
        )
    return rows


def _help_text(cmd) -> str:
    text = (cmd.help or "").replace("\b\n", "").replace("\b", "")
    paras = [" ".join(line.strip() for line in p.splitlines()) for p in text.split("\n\n")]
    return "\n\n".join(_esc(p) for p in paras if p.strip())


def _command_doc(cmd, path: list[str], parent) -> list[str]:
    name = " ".join(path)
    ctx = cmd.context_class(cmd, info_name=path[-1], parent=parent)
    level = "#" * min(len(path) + 1, 4)
    out = [f"{level} `{name}` {{ #{_anchor(name)} }}", ""]
    help_text = _help_text(cmd)
    if help_text:
        out += [help_text, ""]
    usage = " ".join(cmd.collect_usage_pieces(ctx))
    out += ["```text", f"{name} {usage}".rstrip(), "```", ""]
    rows = _param_rows(cmd, ctx)
    if rows:
        out += [
            "| name | kind | type | required | default | help |",
            "|---|---|---|---|---|---|",
            *rows,
            "",
        ]
    if hasattr(cmd, "commands"):
        subs = [(n, c) for n, c in cmd.commands.items() if not c.hidden]
        if subs:
            out += [
                "Subcommands: "
                + ", ".join(f"[`{n}`](#{_anchor(name + ' ' + n)})" for n, _ in subs),
                "",
            ]
        for sub_name, sub in subs:
            out += _command_doc(sub, [*path, sub_name], ctx)
    return out


def cli_page() -> str:
    import typer

    from chemeascode.interfaces.cli import app

    root = typer.main.get_command(app)
    lines = [
        "# CLI reference",
        "",
        GENERATED_NOTE,
        "Every command of `cheme`, with its arguments and options, as `cheme <command> --help`"
        " prints them. The guides explain how the commands fit together.",
        "",
    ]
    if hasattr(root, "commands"):
        top = [n for n, c in root.commands.items() if not c.hidden]
        lines += [
            "| command | what it does |",
            "|---|---|",
            *(
                f"| [`cheme {n}`](#{_anchor('cheme ' + n)}) | "
                f"{_esc(root.commands[n].get_short_help_str(limit=120))} |"
                for n in top
            ),
            "",
        ]
    lines += _command_doc(root, ["cheme"], None)
    return "\n".join(lines) + "\n"


# --- schemas ------------------------------------------------------------------------------


def _schema_catalogue():
    """The kinds of ``cheme schema``: {kind: (model, file)} in its order."""
    from chemeascode.foundation.workspace import LAYOUT_FILES, LIST_FILES, PLANT_FILE
    from chemeascode.schemas import LAYOUT_SCHEMAS, LIST_SCHEMAS, OTHER_SCHEMAS, PlantConfig

    models = {"plant": PlantConfig, **LIST_SCHEMAS, **LAYOUT_SCHEMAS}
    models.update({name: model for name, (model, _) in OTHER_SCHEMAS.items()})
    files = {"plant": PLANT_FILE, **LIST_FILES, **LAYOUT_FILES}
    files.update({name: where for name, (_, where) in OTHER_SCHEMAS.items()})
    return {kind: (model, files.get(kind, "")) for kind, model in models.items()}


def _type_of(prop: dict) -> str:
    if "$ref" in prop:
        return prop["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in prop or "oneOf" in prop:
        parts = [_type_of(p) for p in prop.get("anyOf", prop.get("oneOf", []))]
        return " or ".join(dict.fromkeys(p for p in parts if p))
    if "enum" in prop:
        return " \\| ".join(f"`{v}`" for v in prop["enum"])
    if "const" in prop:
        return f"`{prop['const']}`"
    t = prop.get("type")
    if t == "array":
        items = prop.get("items")
        return f"list of {_type_of(items)}" if isinstance(items, dict) and items else "list"
    if t == "object" and isinstance(prop.get("additionalProperties"), dict):
        return f"map of {_type_of(prop['additionalProperties'])}"
    if isinstance(t, list):
        return " or ".join(t)
    return t or ""


def _top_fields(schema: dict) -> list[str]:
    target = schema
    if "properties" not in target and "items" in target:  # a list kind
        items = target["items"]
        if "$ref" in items:
            target = schema.get("$defs", {}).get(items["$ref"].rsplit("/", 1)[-1], {})
    props = target.get("properties", {})
    required = set(target.get("required", []))
    rows = []
    for name, prop in props.items():
        default = prop.get("default", "")
        default_s = f"`{_esc(json.dumps(default))}`" if "default" in prop else ""
        rows.append(
            f"| `{name}` | {_esc(_type_of(prop)) if '`' not in _type_of(prop) else _type_of(prop)}"
            f" | {'yes' if name in required else ''} | {default_s} |"
            f" {_esc(prop.get('description', ''))} |"
        )
    return rows


def schema_page() -> str:
    catalogue = _schema_catalogue()
    lines = [
        "# Schema reference",
        "",
        GENERATED_NOTE,
        "The schemas of the YAML files of a plant repository, as `cheme schema` lists them;"
        " `cheme schema <kind>` prints the JSON Schema shown under each kind (for editors), and"
        " `cheme validate` checks the files against them.",
        "",
        "| kind | file | what it holds |",
        "|---|---|---|",
    ]
    for kind, (model, where) in catalogue.items():
        title = _esc(_summary(model.__doc__))
        lines.append(f"| [`{kind}`](#{_anchor(kind)}) | `{_esc(where)}` | {title} |")
    lines.append("")
    for kind, (model, where) in catalogue.items():
        schema = model.model_json_schema(by_alias=True)
        doc = "\n\n".join(
            " ".join(p.split()).replace("``", "`") for p in (model.__doc__ or "").split("\n\n")
        ).strip()
        lines += [f"## {kind} {{ #{_anchor(kind)} }}", ""]
        lines += [f"File: `{where}`. Model: `{model.__module__}.{model.__name__}`.", ""]
        if doc:
            lines += [doc.replace("<", "&lt;"), ""]
        rows = _top_fields(schema)
        if rows:
            lines += [
                "| field | type | required | default | description |",
                "|---|---|---|---|---|",
                *rows,
                "",
            ]
        body = json.dumps(schema, indent=2)
        lines += [f'??? note "JSON Schema: `cheme schema {kind}`"', "", "    ```text"]
        lines += [f"    {line}" for line in body.splitlines()]
        lines += ["    ```", ""]
    return "\n".join(lines) + "\n"


# --- serve API ----------------------------------------------------------------------------


def _openapi() -> dict:
    from chemeascode.interfaces.api.serve import create_app
    from chemeascode.templates.install import init

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "plant"
        init(root, "Docs example")
        return create_app(root).openapi()


def _readme_notes() -> dict[str, str]:
    """What each route returns, from the endpoint table of README.md's ``### serve`` section."""
    readme = Path(__file__).resolve().parents[2] / "README.md"
    notes, inside = {}, False
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            inside = line.strip() == "### serve"
            continue
        m = re.match(r"^\| `(GET|POST) ([^`?]+)[^`]*` \| (.*) \|$", line) if inside else None
        if m:
            notes[f"{m.group(1)} {m.group(2)}"] = m.group(3)
    return notes


def _schema_type(schema: dict) -> str:
    return _type_of(schema or {})


def api_page() -> str:
    spec = _openapi()
    notes = _readme_notes()
    lines = [
        "# Serve API reference",
        "",
        GENERATED_NOTE,
        "The routes of `cheme serve` (extra `serve`), from the OpenAPI document of"
        " `chemeascode.interfaces.api.serve.create_app`; a running server also serves it at"
        " `/api/openapi.json`. What each route returns, the error codes and the security rules"
        ' are described in [Viewer and cheme serve](../guides/serve.md); the "Returns" notes'
        " below come from the endpoint table there (README.md).",
        "",
        "| method | path | summary |",
        "|---|---|---|",
    ]
    ops = []
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            ops.append((method.upper(), path, op))
    for method, path, op in ops:
        lines.append(
            f"| {method} | [`{path}`](#{_anchor(method + ' ' + path)}) |"
            f" {_esc(op.get('summary'))} |"
        )
    lines.append("")
    for method, path, op in ops:
        lines += [f"## {method} {path} {{ #{_anchor(method + ' ' + path)} }}", ""]
        if op.get("summary"):
            lines += [f"**{_esc(op['summary'])}**", ""]
        if op.get("description"):
            lines += [_esc(op["description"]), ""]
        if note := notes.get(f"{method} {path}"):
            lines += [f"Returns: {note}", ""]
        params = op.get("parameters", [])
        if params:
            lines += [
                "| parameter | in | type | required | default | description |",
                "|---|---|---|---|---|---|",
            ]
            for p in params:
                schema = p.get("schema", {})
                default = f"`{_esc(json.dumps(schema['default']))}`" if "default" in schema else ""
                t = _schema_type(schema)
                lines.append(
                    f"| `{p['name']}` | {p.get('in', '')} | {t if '`' in t else _esc(t)} |"
                    f" {'yes' if p.get('required') else ''} | {default} |"
                    f" {_esc(p.get('description', schema.get('description', '')))} |"
                )
            lines.append("")
        else:
            lines += ["No parameters.", ""]
        responses = op.get("responses", {})
        if responses:
            lines += ["Responses:", ""]
            for code, resp in responses.items():
                media = ", ".join(f"`{m}`" for m in resp.get("content", {}))
                lines.append(
                    f"- `{code}`: {_esc(resp.get('description', ''))}"
                    + (f" ({media})" if media else "")
                )
            lines.append("")
    return "\n".join(lines) + "\n"
