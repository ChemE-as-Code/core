# 0010. Deterministic engineering functions: no LLM or agent calls in the package

- **Status:** Accepted
- **Date:** 2026-10-21

## Context

The project uses agents to design plants, and some ported code (LLM4ChemE) originally mixed
engineering methods with LLM calls. If checks or calculations called a model, their results
would be non-reproducible, untestable and unattributable, and an agent could mark its own
guesses as computed values.

## Decision

- Domain functions, `project`, `foundation` and `integrations` are deterministic: they contain
  no agent or LLM calls and import no LLM library. Agents are never a dependency of a
  deterministic function. A skill may orchestrate an agent workflow; a domain function may not.
- Values with `provenance: calculated` are produced only by deterministic `cheme` commands
  (`process simulate`, `propagate`, `props`, `datasheets fill`, ...), which put their name at
  the start of `source` and rewrite only values they wrote (`written_by`). Agents write `given`
  or `assumed` values with a source or basis, never `calculated`.
- External services are reached only through `integrations/` adapters with an injectable
  transport and no environment or API keys read; tests do not touch the network.

## Consequences

- Positive: every check and calculation is reproducible from the files and the version; results
  can be fingerprinted ([0011](0011-per-value-provenance-and-fingerprints.md)) and tested.
- Positive: a clear line between judgment (skills, agents, people) and computation (core).
- Negative: methods that would need a learned model (e.g. property prediction by ML) need their
  own adapter, extra and benchmark before they enter.
- Limitation: "agents never write `calculated`" is a convention taught by skills and checked
  indirectly (staleness fingerprints, `written_by`), not proved; a hand-written `calculated`
  value without a fingerprint is not always detectable.

## Evidence

- Responsibilities table ("Must not contain ... agent or LLM calls") and the LLM4ChemE port
  "None of it imports an LLM or agent library": pre-release PR 58,
  [SUMMARY.md](../framework/SUMMARY.md), [llm4cheme-migration.md](../framework/llm4cheme-migration.md).
- [contributing.md](../framework/contributing.md) ("Agents and LLMs are never a dependency of a
  deterministic function"; "Web databases and prediction services").
- [contract.md](../framework/contract.md) ("`calculated`: a tool's result, never edited by hand";
  "agent skills and MCP tools call it and hold no algorithm of their own").
- `tests/test_hazop.py` (no `anthropic`, `openai`, `langchain` loaded by the HAZOP modules).
