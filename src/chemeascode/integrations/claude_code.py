"""Claude Code session transcripts: where they are and what a run record reads from them.

Claude Code writes one JSON object per line to
``<config dir>/projects/<cwd, every non-alphanumeric character as ->/<session id>.jsonl``
(config dir: ``CLAUDE_CONFIG_DIR``, else ``~/.claude``). An assistant line carries
``message: {id, model, content, usage}`` and a ``timestamp``; one API message may span several
lines with the same ``message.id``, the last of which holds its final usage; each line names the
Claude Code ``version`` that wrote it. Tool calls are content blocks ``{type: tool_use, name,
input}``. The format is Claude Code's, not ours: a line that is not JSON, or not shaped as
expected, is skipped and counted, never an error.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

#: Tools that bring third-party text into a session.
WEB_TOOLS = ("WebFetch", "WebSearch")
_WEB_COMMAND = re.compile(r"(?:^|[\s;&|(`])(curl|wget)(?:\s|$)")
#: Where one shell command ends and the next begins.
_SEPARATOR = re.compile(r"&&|\|\||[;|\n]")
#: The model name Claude Code gives the messages it makes up itself (no API call).
_SYNTHETIC = "<synthetic>"


def config_dir() -> Path:
    """Claude Code's configuration directory: ``CLAUDE_CONFIG_DIR``, else ``~/.claude``."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def project_dir(cwd: Path, base: Path | None = None) -> Path:
    """The folder of the transcripts of sessions started in *cwd*."""
    return (base or config_dir()) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def find_transcript(cwd: Path, session_id: str, base: Path | None = None) -> Path | None:
    """The transcript of *session_id* started in *cwd* (as given or resolved), or None."""
    if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
        return None
    for folder in dict.fromkeys((cwd, cwd.resolve())):
        path = project_dir(folder, base) / f"{session_id}.jsonl"
        if path.is_file():
            return path
    return None


@dataclass
class Transcript:
    """What a run record takes from a session transcript (each None when it does not say)."""

    session_id: str | None = None
    started: datetime | None = None
    finished: datetime | None = None
    #: input, output, cache_read, cache_write and thinking (None: never reported).
    tokens: dict[str, int | None] = field(default_factory=dict)
    num_turns: int = 0
    model: str | None = None
    #: The Claude Code version of the last line that names one.
    claude_code: str | None = None
    #: Each shell command (one per segment of a chain) that starts with ``cheme``.
    cheme_commands: list[str] = field(default_factory=list)
    #: Each web use: a WebFetch or WebSearch call, or ``Bash: curl``/``wget``.
    web: list[str] = field(default_factory=list)
    first_user_text: str | None = None
    #: The lines read (inside the window), as they were in the file.
    raw: bytes = b""
    lines: int = 0
    skipped: int = 0


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def _text_of(content: Any) -> str | None:
    """The text a user typed: a string, or the text blocks of a content list (tool results
    and Claude Code's own command echoes excluded)."""
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
    else:
        return None
    text = "\n".join(p for p in parts if p.strip()).strip()
    if not text or text.startswith(("<command-", "<local-command", "Caveat:")):
        return None
    return text


def _commands(command: str) -> list[str]:
    return [part.strip() for part in _SEPARATOR.split(command) if part.strip()]


def read_transcript(path: Path, since: datetime | None = None) -> Transcript:
    """Read the transcript at *path*. With *since*, a line stamped earlier is left out (a
    resumed session: the record covers what happened after it was taken up again)."""
    result = Transcript()
    kept: list[bytes] = []
    usage: dict[str, dict[str, Any]] = {}
    models: Counter[str] = Counter()
    stamps: list[datetime] = []
    for raw in path.read_bytes().splitlines(keepends=True):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            result.skipped += 1
            continue
        if not isinstance(entry, dict):
            result.skipped += 1
            continue
        stamp = _timestamp(entry.get("timestamp"))
        if since is not None and stamp is not None and stamp < since:
            continue
        kept.append(raw)
        result.lines += 1
        if stamp is not None:
            stamps.append(stamp)
        if isinstance(entry.get("version"), str) and entry["version"].strip():
            result.claude_code = entry["version"].strip()
        if result.session_id is None and isinstance(entry.get("sessionId"), str):
            result.session_id = entry["sessionId"]
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        if entry.get("type") == "user" and not entry.get("isMeta"):
            if result.first_user_text is None:
                result.first_user_text = _text_of(message.get("content"))
            continue
        if entry.get("type") != "assistant":
            continue
        model = message.get("model")
        message_id = message.get("id")
        if model == _SYNTHETIC:
            continue
        if isinstance(message_id, str):
            if isinstance(message.get("usage"), dict):
                usage[message_id] = message["usage"]  # the last line of a message counts
            else:
                usage.setdefault(message_id, {})
            if isinstance(model, str):
                models[model] += 1
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name in WEB_TOOLS:
                result.web.append(str(name))
            elif name == "Bash":
                command = (block.get("input") or {}).get("command")
                if not isinstance(command, str):
                    continue
                for part in _commands(command):
                    if part == "cheme" or part.startswith("cheme "):
                        result.cheme_commands.append(part)
                    found = _WEB_COMMAND.search(part)
                    if found:
                        result.web.append(f"Bash: {found.group(1)}")
    result.raw = b"".join(kept)
    if stamps:
        result.started, result.finished = min(stamps), max(stamps)
    result.num_turns = len(usage)
    if models:
        result.model = models.most_common(1)[0][0]
    if usage:
        result.tokens = _tokens(usage.values())
    return result


def _tokens(usages: Any) -> dict[str, int | None]:
    def total(key: str) -> int:
        return sum(int(u[key]) for u in usages if isinstance(u.get(key), int | float))

    usages = list(usages)
    thinking = [
        u["output_tokens_details"].get("thinking_tokens")
        for u in usages
        if isinstance(u.get("output_tokens_details"), dict)
        and isinstance(u["output_tokens_details"].get("thinking_tokens"), int | float)
    ]
    return {
        "input": total("input_tokens"),
        "output": total("output_tokens"),
        "thinking": int(sum(thinking)) if thinking else None,
        "cache_read": total("cache_read_input_tokens"),
        "cache_write": total("cache_creation_input_tokens"),
    }
