"""pyDEXPI glue: how the levels pyDEXPI reports map onto finding levels."""

from __future__ import annotations

from chemeascode.foundation.findings import Level

#: The level of a finding for each level pyDEXPI's loader reports an issue at.
_LOADER_LEVELS: dict[str, Level] = {
    "critical": "error",
    "error": "error",
    "warning": "warning",
    "info": "info",
}
#: The level of a finding for each obligation of a pyDEXPI validation rule.
_RULE_LEVELS: dict[str, Level] = {
    "Mandatory": "error",
    "Recommended": "warning",
    "Optional": "info",
}
