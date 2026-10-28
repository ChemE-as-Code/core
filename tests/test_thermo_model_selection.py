"""Thermodynamic model selection: the rule engine and the packaged knowledge base.

Ported from LLM4ChemE (tests/tools/test_ruledb_inference_engine.py,
test_thermo_model_selection_tool.py and the knowledge-base fixtures of its conftest.py).
"""

from importlib.util import find_spec
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.process.thermodynamics.model_selection import RULES_FILE
from chemeascode.domains.process.thermodynamics.model_selection import (
    select_thermo_model as thermo_model_selection_rulebase_inference,
)
from chemeascode.domains.process.thermodynamics.rules import (
    InferenceResult,
    InsufficientFactsError,
    KnowledgeBase,
    KnowledgeBaseSchema,
)

THERMO_MODEL_SELECTION_KB_PATH = RULES_FILE


@pytest.fixture(autouse=True)
def _run_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize(
    ("pressure_value", "pressure_unit", "expected_band"),
    [
        (50.0, "bar", "high"),
        pytest.param(
            1.0,
            "atm",
            "not_extreme",
            marks=pytest.mark.skipif(find_spec("pint") is None, reason="needs the units extra"),
        ),
        (10.0, "kPa", "vacuum"),
    ],
)
def test_tool_with_pressure(pressure_value: float, pressure_unit: str, expected_band: str) -> None:
    result = thermo_model_selection_rulebase_inference(
        provided_facts={
            "pressure_value": pressure_value,
            "pressure_unit": pressure_unit,
            "is_polar": False,
            "is_electrolyte": False,
            "has_pseudocomponents": True,
        }
    )

    assert isinstance(result, InferenceResult)
    assert result.provided_facts["pressure_band"] == expected_band
    assert "pressure_value" not in result.provided_facts
    assert "pressure_unit" not in result.provided_facts
    expected_outcome = (
        "nonpolar_pseudocomponents_vacuum"
        if expected_band == "vacuum"
        else "nonpolar_pseudocomponents_nonvacuum"
    )
    assert result.selected_outcome == expected_outcome
    assert result.models


def test_tool_without_pressure_reports_pressure_inputs() -> None:
    # The internal KB fact pressure_band is not a tool input, so the error must
    # name the inputs the LLM has to fill in instead.
    with pytest.raises(InsufficientFactsError) as exc_info:
        thermo_model_selection_rulebase_inference(
            provided_facts={"is_polar": True, "is_electrolyte": False}
        )

    assert exc_info.value.missing_facts == ["pressure_unit", "pressure_value"]
    message = str(exc_info.value)
    assert "pressure_band" not in message
    assert "- pressure_value: What is the operating pressure" in message


def test_tool_reports_pressure_inputs_alongside_other_missing_facts() -> None:
    with pytest.raises(InsufficientFactsError) as exc_info:
        thermo_model_selection_rulebase_inference(
            provided_facts={"is_polar": False, "has_pseudocomponents": True}
        )

    assert exc_info.value.missing_facts == ["pressure_unit", "pressure_value"]

    with pytest.raises(InsufficientFactsError) as exc_info:
        thermo_model_selection_rulebase_inference(
            provided_facts={
                "pressure_value": 1.0,
                "pressure_unit": "bar",
                "is_polar": True,
                "is_electrolyte": False,
            }
        )

    assert exc_info.value.missing_facts == [
        "interaction_parameters_available",
        "liquid_liquid_expected",
    ]


def test_tool_rejects_pressure_band_input() -> None:
    # An LLM retrying with the internal fact name must get a validation error
    # instead of the key being dropped silently and the same missing-facts
    # error repeating.
    with pytest.raises(ValidationError, match="pressure_band"):
        thermo_model_selection_rulebase_inference(
            provided_facts={
                "is_polar": True,
                "is_electrolyte": False,
                "pressure_band": "high",
            }
        )


def test_tool_rejects_unknown_input() -> None:
    with pytest.raises(ValidationError, match="vapor_phase_association_expected"):
        thermo_model_selection_rulebase_inference(
            provided_facts={"is_polar": True, "vapor_phase_association_expected": True}
        )


def test_tool_without_pressure_when_not_needed() -> None:
    result = thermo_model_selection_rulebase_inference(
        provided_facts={"is_polar": False, "has_pseudocomponents": False}
    )

    assert result.selected_outcome == "nonpolar_no_pseudocomponents"
    assert "pressure_band" not in result.provided_facts


def test_tool_pressure_value_without_unit() -> None:
    with pytest.raises(ValueError, match="pressure_unit"):
        thermo_model_selection_rulebase_inference(
            provided_facts={"pressure_value": 5.0, "is_polar": True}
        )


def test_loading_db() -> None:
    kb_dict = yaml.safe_load(THERMO_MODEL_SELECTION_KB_PATH.read_text(encoding="utf-8"))
    kb = KnowledgeBaseSchema.from_dict(kb_dict)
    assert kb


def test_inference_insufficient_info() -> None:
    kb_dict = yaml.safe_load(THERMO_MODEL_SELECTION_KB_PATH.read_text(encoding="utf-8"))
    kb = KnowledgeBase.from_dict(kb_dict)
    provided_facts = {
        "pressure_band": "not_extreme",
        "is_polar": True,
        "is_electrolyte": False,
    }
    with pytest.raises(InsufficientFactsError) as exc_info:
        kb.infer(provided_facts)
    assert exc_info.value.missing_facts == [
        "interaction_parameters_available",
        "liquid_liquid_expected",
    ]


def test_inference_sufficient_info() -> None:
    kb_dict = yaml.safe_load(THERMO_MODEL_SELECTION_KB_PATH.read_text(encoding="utf-8"))
    kb = KnowledgeBase.from_dict(kb_dict)
    provided_facts = {
        "pressure_band": "not_extreme",
        "is_polar": True,
        "is_electrolyte": False,
        "interaction_parameters_available": True,
        "liquid_liquid_expected": False,
        "vapor_association_expected": False,
    }
    result = kb.infer(provided_facts)
    assert "NRTL" in result.models[0]
    assert result.source  # the knowledge base's sources travel with the result
    assert result.source
    assert len(result.source) == 2
    assert "Carlson" in result.source[0]
    assert "Aspen Plus" in result.source[1]


def test_multiple_entry_points(
    mock_kb_multiple_entry_points: KnowledgeBaseSchema,
) -> None:
    kb = KnowledgeBase.from_dict(mock_kb_multiple_entry_points)
    provided_facts = {
        "fact_1": "yes",
    }
    with pytest.raises(RuntimeError) as exc_info:
        kb.infer(provided_facts)
    assert (
        str(exc_info.value) == "Multiple entry points found in knowledge base. "
        "Expected only one rule with is_entrypoint=True."
    )


def test_branch_rules_logic_outcome_1(kb_with_branch_rules: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_branch_rules)
    provided_facts = {
        "fact_0": "1",
        "fact_1": "A",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_a"]


def test_branch_rules_logic_outcome_2(kb_with_branch_rules: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_branch_rules)
    provided_facts = {
        "fact_0": "1",
        "fact_1": "B",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_b"]


def test_branch_rules_logic_outcome_2_direct(kb_with_branch_rules: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_branch_rules)
    provided_facts = {
        "fact_0": "2",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_b"]


def test_impossible_value(kb_with_branch_rules: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_branch_rules)
    provided_facts = {
        "fact_0": "stupid",
    }
    with pytest.raises(ValueError) as exc_info:
        kb.infer(provided_facts)
    assert (
        str(exc_info.value)
        == "Value 'stupid' for fact 'fact_0' is not in possible values: ['1', '2']"
    )


def test_no_branch_option_matched(kb_with_branch_rules_no_match: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_branch_rules_no_match)
    provided_facts = {
        "fact_0": "3",  # This value does not match any branch option
        "fact_1": "A",
    }
    with pytest.raises(RuntimeError) as exc_info:
        kb.infer(provided_facts)
    assert str(exc_info.value) == "No branch option matched for 'rule_1'."


def test_rule_matched_no_outcome(kb_with_branch_rules_no_match: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_branch_rules_no_match)
    provided_facts = {"fact_0": "1", "fact_1": "C"}
    with pytest.raises(RuntimeError) as exc_info:
        kb.infer(provided_facts)
    assert str(exc_info.value) == "Rule 'rule_4' matched but has no outcome (then/next)."


def test_diverse_conditions(kb_with_diverse_conditions: dict) -> None:
    kb = KnowledgeBase.from_dict(kb_with_diverse_conditions)
    provided_facts = {
        "fact_1": True,
        "fact_2": "A",
        "fact_3": "blue",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_a"]
    provided_facts = {
        "fact_1": False,
        "fact_2": "B",
        "fact_3": "blue",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_b"]
    provided_facts = {
        "fact_1": True,
        "fact_2": "D",
        "fact_3": "red",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_c"]
    provided_facts = {
        "fact_1": True,
        "fact_2": "C",
        "fact_3": "blue",
    }
    result = kb.infer(provided_facts)
    assert result.models == ["model_d"]


def test_unsupported_condition(kb_with_unsupported_condition_type):
    kb = KnowledgeBase.from_dict(kb_with_unsupported_condition_type)
    provided_facts = {
        "fact_1": "A",
    }
    with pytest.raises(NotImplementedError) as exc_info:
        kb.infer(provided_facts)
    assert (
        "Unsupported condition fact='fact_1' equals=None in_=None not_equals=None "
        "not_in=None all=None any=None." in str(exc_info.value)
    )


def test_branch_rules_no_match_error(
    kb_with_branch_rules_no_match_coverage: dict,
) -> None:
    """Test Case 2 branch rules when no rule matches and all facts are present."""
    kb = KnowledgeBase.from_dict(kb_with_branch_rules_no_match_coverage)
    provided_facts = {
        "entry_fact": "route_to_branch",
        "branch_fact": "Z",  # This value doesn't match any branch rule
    }
    with pytest.raises(RuntimeError) as exc_info:
        kb.infer(provided_facts)
    assert str(exc_info.value) == "Rule 'target_branch' did not yield a result."


def test_empty_condition_group(kb_with_empty_condition_group: dict) -> None:
    """Test that empty/invalid condition group raises ValueError."""
    kb = KnowledgeBase.from_dict(kb_with_empty_condition_group)
    provided_facts = {
        "fact_1": "A",
    }
    with pytest.raises(ValueError) as exc_info:
        kb.infer(provided_facts)
    assert "Invalid condition group" in str(exc_info.value)


def test_duplicate_rule_ids(kb_with_duplicate_rule_ids: dict) -> None:
    """Test that duplicate rule IDs raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        KnowledgeBase.from_dict(kb_with_duplicate_rule_ids)
    assert str(exc_info.value) == "Duplicate rule IDs found in knowledge base rules."


@pytest.fixture
def mock_kb_zero_entry_points() -> dict:
    kb_dict = {
        "meta": {
            "name": "Mock KB with Zero Entry Points",
            "version": "1.0",
            "description": "A mock knowledge base for testing with zero entry points.",
        },
        "facts": [
            {
                "id": "fact_1",
                "description": "A sample fact.",
                "possible_values": ["yes", "no"],
            }
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on fact_1 being yes.",
            }
        ],
        "rules": [
            {
                "id": "rule_1",
                "when": {"fact": "fact_1", "equals": "yes"},
                "then": "outcome_1",
            }
        ],
    }

    return kb_dict


@pytest.fixture
def mock_kb_multiple_entry_points() -> dict:
    kb_dict = {
        "meta": {
            "name": "Mock KB with Multiple Entry Points",
            "version": "1.0",
            "description": "A mock knowledge base for testing with multiple entry points.",
        },
        "facts": [
            {
                "id": "fact_1",
                "description": "A sample fact.",
                "possible_values": ["yes", "no"],
            }
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on fact_1 being yes.",
            }
        ],
        "rules": [
            {
                "id": "rule_1",
                "when": {"fact": "fact_1", "equals": "yes"},
                "then": "outcome_1",
                "is_entrypoint": True,
            },
            {
                "id": "rule_2",
                "when": {"fact": "fact_1", "equals": "no"},
                "then": "outcome_1",
                "is_entrypoint": True,
            },
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_branch_rules() -> dict:
    kb_dict = {
        "meta": {
            "name": "Mock KB with Branch Rules",
            "version": "1.0",
            "description": "A mock knowledge base for testing branch rules.",
        },
        "facts": [
            {
                "id": "fact_0",
                "description": "A sample fact for entry.",
                "possible_values": ["1", "2"],
            },
            {
                "id": "fact_1",
                "description": "A sample fact for branching.",
                "possible_values": ["A", "B"],
            },
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on fact_1 being A.",
            },
            {
                "id": "outcome_2",
                "models": ["model_b"],
                "reasoning": "Based on fact_1 being B.",
            },
        ],
        "rules": [
            {
                "id": "rule_1",
                "is_entrypoint": True,
                "name": "entry_rule",
                "branches": [
                    {
                        "when": {"fact": "fact_0", "equals": "1"},
                        "next": "branch_1",
                    },
                    {
                        "when": {"fact": "fact_0", "equals": "2"},
                        "then": "outcome_2",
                    },
                ],
            },
            {
                "id": "rule_2",
                "when": {"fact": "fact_1", "equals": "A"},
                "then": "outcome_1",
                "branch": "branch_1",
            },
            {
                "id": "rule_3",
                "when": {"fact": "fact_1", "equals": "B"},
                "then": "outcome_2",
                "branch": "branch_1",
            },
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_branch_rules_no_match() -> dict:
    kb_dict = {
        "meta": {
            "name": "Mock KB with Branch Rules No Match",
            "version": "1.0",
            "description": "A mock knowledge base for testing branch rules with no match.",
        },
        "facts": [
            {
                "id": "fact_0",
                "description": "A sample fact for entry.",
                "possible_values": ["1", "2", "3"],
            },
            {
                "id": "fact_1",
                "description": "A sample fact for branching.",
                "possible_values": ["A", "B", "C"],
            },
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on fact_1 being A.",
            },
            {
                "id": "outcome_2",
                "models": ["model_b"],
                "reasoning": "Based on fact_1 being B.",
            },
        ],
        "rules": [
            {
                "id": "rule_1",
                "is_entrypoint": True,
                "name": "entry_rule",
                "branches": [
                    {
                        "when": {"fact": "fact_0", "equals": "1"},
                        "next": "branch_1",
                    },
                    {
                        "when": {"fact": "fact_0", "equals": "2"},
                        "then": "outcome_2",
                    },
                ],
            },
            {
                "id": "rule_2",
                "when": {"fact": "fact_1", "equals": "A"},
                "then": "outcome_1",
                "branch": "branch_1",
            },
            {
                "id": "rule_3",
                "when": {"fact": "fact_1", "equals": "B"},
                "then": "outcome_2",
                "branch": "branch_1",
            },
            {
                "id": "rule_4",
                "when": {"fact": "fact_1", "equals": "C"},
                "branch": "branch_1",
            },
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_diverse_conditions() -> dict:
    kb_dict = {
        "meta": {
            "name": "Mock KB with Diverse Conditions",
            "version": "1.0",
            "description": "A mock knowledge base for testing diverse condition types.",
        },
        "facts": [
            {
                "id": "fact_1",
                "description": "A sample fact for equality check.",
                "possible_values": [True, False],
            },
            {
                "id": "fact_2",
                "description": "A sample fact for inclusion check.",
                "possible_values": ["A", "B", "C", "D"],
            },
            {
                "id": "fact_3",
                "description": "A sample fact for inclusion check.",
                "possible_values": ["blue", "green", "red"],
            },
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on diverse conditions.",
            },
            {
                "id": "outcome_2",
                "models": ["model_b"],
                "reasoning": "Based on diverse conditions.",
            },
            {
                "id": "outcome_3",
                "models": ["model_c"],
                "reasoning": "Based on diverse conditions.",
            },
            {
                "id": "outcome_4",
                "models": ["model_d"],
                "reasoning": "Based on diverse conditions.",
            },
        ],
        "rules": [
            {
                "id": "rule_1",
                "is_entrypoint": True,
                "name": "entry_rule",
                "branches": [
                    {
                        "when": {
                            "all": [
                                {"fact": "fact_1", "equals": True},
                                {"fact": "fact_2", "equals": "A"},
                                {"fact": "fact_3", "equals": "blue"},
                            ]
                        },
                        "then": "outcome_1",
                    },
                    {
                        "when": {
                            "any": [
                                {"fact": "fact_1", "equals": False},
                                {"fact": "fact_2", "equals": "B"},
                                {"fact": "fact_3", "equals": "green"},
                            ]
                        },
                        "then": "outcome_2",
                    },
                    {
                        "when": {
                            "fact": "fact_3",
                            "not_in": ["blue", "green"],
                        },
                        "then": "outcome_3",
                    },
                    {
                        "when": {
                            "fact": "fact_2",
                            "not_equals": "D",
                        },
                        "then": "outcome_4",
                    },
                ],
            }
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_unsupported_condition_type() -> dict:
    kb_dict = {
        "meta": {
            "name": "Mock KB with Unsupported Condition Type",
            "version": "1.0",
            "description": "A mock knowledge base for testing unsupported condition type handling.",
        },
        "facts": [
            {
                "id": "fact_1",
                "description": "A sample fact with unsupported condition type.",
                "possible_values": ["A", "B"],
            }
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_unsupported"],
                "reasoning": "Based on unsupported condition type.",
            }
        ],
        "rules": [
            {
                "id": "rule_1",
                "when": {"fact": "fact_1", "looks_like": "A"},
                "then": "outcome_1",
            }
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_branch_rules_no_match_coverage() -> dict:
    """Knowledge base to test Case 2 branch rules where no rule matches."""
    kb_dict = {
        "meta": {
            "name": "Mock KB Branch Rules No Match Coverage",
            "version": "1.0",
            "description": "KB for testing Case 2 branch rules with no matching conditions.",
        },
        "facts": [
            {
                "id": "entry_fact",
                "description": "Entry fact to route to branch.",
                "possible_values": ["route_to_branch"],
            },
            {
                "id": "branch_fact",
                "description": "Fact used in branch rules.",
                "possible_values": ["X", "Y", "Z"],
            },
        ],
        "outcomes": [
            {
                "id": "outcome_x",
                "models": ["model_x"],
                "reasoning": "X outcome.",
            },
            {
                "id": "outcome_y",
                "models": ["model_y"],
                "reasoning": "Y outcome.",
            },
        ],
        "rules": [
            {
                "id": "entry_rule",
                "is_entrypoint": True,
                "name": "entry",
                "branches": [
                    {
                        "when": {"fact": "entry_fact", "equals": "route_to_branch"},
                        "next": "target_branch",
                    }
                ],
            },
            {
                "id": "branch_rule_1",
                "branch": "target_branch",
                "when": {"fact": "branch_fact", "equals": "X"},
                "then": "outcome_x",
            },
            {
                "id": "branch_rule_2",
                "branch": "target_branch",
                "when": {"fact": "branch_fact", "equals": "Y"},
                "then": "outcome_y",
            },
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_empty_condition_group() -> dict:
    """Knowledge base with malformed empty condition group."""
    kb_dict = {
        "meta": {
            "name": "Mock KB with Empty Condition Group",
            "version": "1.0",
            "description": "KB for testing empty/invalid condition group handling.",
        },
        "facts": [
            {
                "id": "fact_1",
                "description": "Sample fact.",
                "possible_values": ["A", "B"],
            }
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on empty condition.",
            }
        ],
        "rules": [
            {
                "id": "rule_1",
                "is_entrypoint": True,
                "name": "entry",
                "branches": [
                    {
                        "when": {},  # Empty condition - will create malformed ConditionGroup
                        "then": "outcome_1",
                    }
                ],
            }
        ],
    }

    return kb_dict


@pytest.fixture
def kb_with_duplicate_rule_ids() -> dict:
    """Knowledge base with duplicate rule IDs to test error handling."""
    kb_dict = {
        "meta": {
            "name": "Mock KB with Duplicate Rule IDs",
            "version": "1.0",
            "description": "KB for testing duplicate rule ID handling.",
        },
        "facts": [
            {
                "id": "fact_1",
                "description": "Sample fact.",
                "possible_values": ["A", "B"],
            }
        ],
        "outcomes": [
            {
                "id": "outcome_1",
                "models": ["model_a"],
                "reasoning": "Based on fact_1 being A.",
            }
        ],
        "rules": [
            {
                "id": "duplicate_rule",
                "when": {"fact": "fact_1", "equals": "A"},
                "then": "outcome_1",
            },
            {
                "id": "duplicate_rule",  # Duplicate ID
                "when": {"fact": "fact_1", "equals": "B"},
                "then": "outcome_1",
            },
        ],
    }

    return kb_dict


def test_result_is_deterministic():
    """No random id: the same facts give the same result (LLM4ChemE added a uuid per call)."""
    facts = {
        "pressure_value": 5.0,
        "pressure_unit": "bar(a)",
        "is_polar": False,
        "is_electrolyte": False,
        "has_pseudocomponents": True,
    }
    assert thermo_model_selection_rulebase_inference(facts) == (
        thermo_model_selection_rulebase_inference(facts)
    )
