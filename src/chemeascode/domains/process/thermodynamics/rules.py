"""A small rule engine: a knowledge base of facts, outcomes and rules, and its inference.

A knowledge base is YAML (``meta``, ``facts``, ``outcomes``, ``rules``); rules branch on facts
(``equals``, ``in``, ``not_equals``, ``not_in``, nested ``all``/``any``) until one names an
outcome. A fact that is needed but not given raises :class:`InsufficientFactsError` with the
question to ask, so a caller (a person or an agent) can supply it and retry. The engine holds no
engineering knowledge; ``model_selection_rules.yml`` is the one knowledge base today.

Moved from LLM4ChemE (``src/tools/thermo_model_selection``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_UNSET = object()


class MetaDefinition(BaseModel):
    """Metadata describing the knowledge base."""

    name: str
    version: str
    description: str | None = None
    source: str | list[str] | None = None
    default_reasoning_prefix: str = ""


class FactDefinition(BaseModel):
    """Definition of a primitive fact that must be provided by the user."""

    id: str
    description: str | None = None
    possible_values: Sequence[str | bool | float | int] | None = None
    question: str | None = None


class OutcomeDefinition(BaseModel):
    """Possible recommendation emitted by the knowledge base."""

    id: str
    models: list[str]
    reasoning: str


class ConditionGroup(BaseModel):
    """Boolean expression over facts supporting nested and/or logic."""

    model_config = ConfigDict(populate_by_name=True)

    fact: str | None = None
    equals: bool | float | int | str | None = None
    in_: list[str] | None = Field(default=None, alias="in")
    not_equals: bool | float | int | str | None = None
    not_in: list[str] | None = None
    all: list[ConditionGroup] | None = None
    any: list[ConditionGroup] | None = None


ConditionGroup.model_rebuild()


class BranchOption(BaseModel):
    """Option within a named branch dispatcher."""

    when: ConditionGroup
    next: str | None = None
    then: str | None = None


class RuleDefinition(BaseModel):
    """Single rule definition."""

    id: str
    when: ConditionGroup | None = None
    then: str | None = None
    next: str | None = None
    branch: str | None = None
    name: str | None = None
    branches: list[BranchOption] | None = None
    is_entrypoint: bool = False


class KnowledgeBaseSchema(BaseModel):
    """Full schema for a rule-based knowledge base."""

    meta: MetaDefinition
    facts: list[FactDefinition] = Field(default_factory=list)
    outcomes: list[OutcomeDefinition] = Field(default_factory=list)
    rules: list[RuleDefinition]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeBaseSchema:
        """Validate incoming dictionary data and return a schema instance."""
        return cls.model_validate(data)


class InferenceResult(BaseModel):
    """Container for inference output."""

    provided_facts: dict[str, bool | str | float | int] = Field(
        default_factory=dict, description="Facts provided for inference"
    )
    source: str | list[str] | None = Field(
        default=None, description="Source(s) of the knowledge base rules and reasoning"
    )

    selected_outcome: str = Field(description="Name of the selected outcome in the rule database")
    models: list[str] = Field(description="List of recommended thermo models")
    reasoning: str = Field(description="Explanation of the reasoning behind the selected outcome")
    triggered_rules: list[str] = Field(
        description="List of rule IDs that were triggered during inference"
    )


class InsufficientFactsError(RuntimeError):
    """
    Raised when additional facts are needed before inference can continue.

    Attributes
    ----------
    missing_facts : list[str]
        List of missing fact IDs.
    fact_details : list[dict[str, str | None]]
        List of dictionaries containing details about each missing fact.
    """

    def __init__(
        self,
        missing_fact_ids: Iterable[str],
        fact_definitions: dict[str, FactDefinition],
    ) -> None:
        """
        Initialize the InsufficientFactsError.

        Parameters
        ----------
        missing_fact_ids : Iterable[str]
            Iterable of missing fact IDs.
        fact_definitions : dict[str, FactDefinition]
            Dictionary of fact definitions keyed by fact ID.
        """
        self.missing_facts = sorted(set(missing_fact_ids))
        self.fact_details = []
        for fact_id in self.missing_facts:
            fact_def = fact_definitions.get(fact_id)
            self.fact_details.append(
                {
                    "fact_id": fact_id,
                    "question": fact_def.question if fact_def else None,
                    "description": fact_def.description if fact_def else None,
                }
            )
        prompt_lines = []
        for detail in self.fact_details:
            question = detail["question"] or detail["description"] or "Provide value."
            prompt_lines.append(f"- {detail['fact_id']}: {question}")
        message = "Additional facts required to continue inference:\n" + "\n".join(prompt_lines)
        super().__init__(message)


class KnowledgeBase:
    """
    Simple interpreter for rule-based knowledge bases.

    Attributes
    ----------
    schema : KnowledgeBaseSchema
        The schema defining the knowledge base.
    meta : MetaDefinition
        Metadata about the knowledge base.
    outcomes : dict[str, OutcomeDefinition]
        Dictionary of outcome definitions keyed by outcome ID.
    rules : list[RuleDefinition]
        List of rule definitions in the knowledge base.
    fact_definitions : dict[str, FactDefinition]
        Dictionary of fact definitions keyed by fact ID.
    branch_routes : dict[str, list[BranchOption]]
        Dictionary mapping branch names to their options.
    """

    def __init__(self, schema: KnowledgeBaseSchema) -> None:
        """
        Initialize the KnowledgeBase instance.

        Parameters
        ----------
        schema : KnowledgeBaseSchema
            The schema defining the knowledge base.
        """
        self.schema = schema
        self.meta = schema.meta
        self.outcomes = {outcome.id: outcome for outcome in schema.outcomes}
        self.rules = schema.rules
        # Raise an error if there are duplicate rule IDs
        rule_ids = [rule.id for rule in self.rules if rule.id is not None]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Duplicate rule IDs found in knowledge base rules.")
        self.fact_definitions: dict[str, FactDefinition] = {fact.id: fact for fact in schema.facts}
        self.branch_routes: dict[str, list[BranchOption]] = {
            rule.id: rule.branches for rule in self.rules if rule.id and rule.branches
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeBase:
        """
        Build a knowledge base from raw dictionary data.

        Parameters
        ----------
        data : dict[str, Any]
            Raw dictionary data representing the knowledge base.

        Returns
        -------
        KnowledgeBase
            The constructed KnowledgeBase instance.
        """
        schema = KnowledgeBaseSchema.from_dict(data)
        return cls(schema)

    def infer(self, provided_facts: dict[str, bool | str | float | int]) -> InferenceResult:
        """
        Execute the rule base for the supplied facts.

        Parameters
        ----------
        provided_facts : dict[str, bool | str | float | int]
            Facts provided for inference.

        Returns
        -------
        InferenceResult
            The result of the inference process.

        Raises
        ------
        InsufficientFactsError
            If additional facts are required for inference.
        RuntimeError
            If no entry point found or if no rule produces an outcome.
        """
        facts = provided_facts.copy()

        # check that all provided fact values are in the respective possible_values
        for fact_id, value in facts.items():
            fact_def = self.fact_definitions.get(fact_id)
            if fact_def and fact_def.possible_values and value not in fact_def.possible_values:
                raise ValueError(
                    f"Value '{value}' for fact '{fact_id}' is not in "
                    f"possible values: {fact_def.possible_values}"
                )

        triggered: list[str] = []
        missing_facts: set[str] = set()

        # Find the entry point rule
        # Potential errors: No entry point defined OR multiple entry points
        entry_points = [rule for rule in self.rules if rule.is_entrypoint]

        if entry_points and len(entry_points) > 1:
            raise RuntimeError(
                "Multiple entry points found in knowledge base. "
                "Expected only one rule with is_entrypoint=True."
            )

        entry_point = entry_points[0] if entry_points else self.rules[0]

        if not entry_point.branch and (not entry_point.branches or entry_point.branches == []):
            entry_point.branch = entry_point.id

        # Resolve starting from the entry point
        outcome_id = self.resolve_branch(entry_point.id, facts, triggered, missing_facts)
        return self._build_result(outcome_id, triggered, provided_facts)

    def resolve_branch(
        self,
        branch_id: str,
        facts: dict[str, bool | str | float | int],
        triggered: list[str],
        missing_facts: set[str],
    ) -> str:
        """
        Recursively resolve branch structures to find the final outcome.

        Delegates to specialized handlers for branch routes vs branch rules.

        Parameters
        ----------
        branch_id : str
            The ID of the branch to resolve.
        facts : dict[str, bool | str | float | int]
            The current set of known facts.
        triggered : list[str]
            The list of triggered rule IDs.
        missing_facts : set[str]
            The set of currently missing fact IDs.

        Returns
        -------
        str
            The outcome ID resulting from branch resolution.

        Raises
        ------
        InsufficientFactsError
            If additional facts are required for branch resolution.
        RuntimeError
            If no branch option matches or if a branch rule lacks a 'then' outcome.
        """
        missing_before = set(missing_facts)

        # Try Case 1: Named branch routes (rules with branches list)
        if branch_id in self.branch_routes:
            return self.resolve_branch_routes(
                branch_id, facts, triggered, missing_facts, missing_before
            )
        else:
            # Try Case 2: Branch rules (individual rules with (the same)
            # branch attribute)
            return self.resolve_branch_rules(
                branch_id, facts, triggered, missing_facts, missing_before
            )

    def resolve_branch_routes(
        self,
        branch_id: str,
        facts: dict[str, bool | str | float | int],
        triggered: list[str],
        missing_facts: set[str],
        missing_before: set[str],
    ) -> str:
        """Handle branches defined as a list of options in a single rule."""
        for option in self.branch_routes[branch_id]:
            if self._matches_condition_group(option.when, facts, missing_facts):
                return self.resolve_outcome(
                    then_value=option.then,
                    next_value=option.next,
                    facts=facts,
                    triggered=triggered,
                    missing_facts=missing_facts,
                    missing_before=missing_before,
                )

        # No option matched
        self.check_and_raise_missing_facts(missing_facts, missing_before)
        raise RuntimeError(f"No branch option matched for '{branch_id}'.")

    def resolve_branch_rules(
        self,
        branch_id: str,
        facts: dict[str, bool | str | float | int],
        triggered: list[str],
        missing_facts: set[str],
        missing_before: set[str],
    ) -> str:
        """Handle branches defined as separate rules with a branch attribute."""
        branch_rules = [
            rule for rule in self.rules if hasattr(rule, "branch") and rule.branch == branch_id
        ]

        for rule in branch_rules:
            if self._matches_condition_group(rule.when, facts, missing_facts):
                triggered.append(rule.id)
                return self.resolve_outcome(
                    then_value=rule.then,
                    next_value=rule.next,
                    facts=facts,
                    triggered=triggered,
                    missing_facts=missing_facts,
                    missing_before=missing_before,
                    rule_id=rule.id,
                )

        # No branch rule matched
        self.check_and_raise_missing_facts(missing_facts, missing_before)
        raise RuntimeError(f"Rule '{branch_id}' did not yield a result.")

    def resolve_outcome(
        self,
        then_value: str | None,
        next_value: str | None,
        facts: dict[str, bool | str | float | int],
        triggered: list[str],
        missing_facts: set[str],
        missing_before: set[str],
        rule_id: str | None = None,
    ) -> str:
        """
        Resolve the outcome of a matched rule or branch option.

        Returns the outcome ID directly if 'then' is present, or recursively
        resolves the next branch if 'next' is present.
        """
        if then_value:
            return then_value
        if next_value:
            self.check_and_raise_missing_facts(missing_facts, missing_before)
            return self.resolve_branch(next_value, facts, triggered, missing_facts)

        rule_info = f"Rule '{rule_id}'" if rule_id else "Branch option"
        raise RuntimeError(f"{rule_info} matched but has no outcome (then/next).")

    def check_and_raise_missing_facts(
        self, missing_facts: set[str], missing_before: set[str]
    ) -> None:
        """Check for newly discovered missing facts and raise error if found."""
        new_missing = missing_facts.difference(missing_before)
        if new_missing:
            self._raise_missing_facts(new_missing)

    def _matches_condition_group(
        self,
        group: ConditionGroup | None,
        facts: dict[str, bool | str | float | int],
        missing_facts: set[str],
    ) -> bool:
        """
        Check if a condition group matches the provided facts.

        Parameters
        ----------
        group : ConditionGroup | None
            The condition group to evaluate.
        facts : dict[str, bool | str | float | int]
            The current set of known facts.
        missing_facts : set[str]
            The set of currently missing fact IDs.

        Returns
        -------
        bool
            True if the condition group matches, False otherwise.
        """
        if group is None:  # for fallback rules with no conditions
            return True
        if group.all:
            all_match = True
            for cond in group.all:
                if not self._matches_condition_group(cond, facts, missing_facts):
                    all_match = False
            return all_match
        if group.any:
            for cond in group.any:
                if self._matches_condition_group(cond, facts, missing_facts):
                    return True
            return False
        if group.fact is not None:
            return self._matches_condition(group, facts, missing_facts)
        raise ValueError(f"Invalid condition group: {group}")

    def _matches_condition(
        self,
        condition: ConditionGroup,
        facts: dict[str, bool | str | float | int],
        missing_facts: set[str],
    ) -> bool:
        """
        Check if a single condition matches the provided facts.

        Parameters
        ----------
        condition : ConditionGroup
            The condition to evaluate.
        facts : dict[str, bool | str | float | int]
            The current set of known facts.
        missing_facts : set[str]
            The set of currently missing fact IDs.

        Returns
        -------
        bool
            True if the condition matches, False otherwise.

        Raises
        ------
        NotImplementedError
            If the condition type is unsupported.
        """
        fact_id = condition.fact
        if fact_id is None:
            raise ValueError(
                f"Condition has fact=None but was called from _matches_condition_group: {condition}"
            )
        fact_value = facts.get(fact_id, _UNSET)
        if fact_value is _UNSET or self._is_missing_value(fact_value):
            missing_facts.add(fact_id)
            return False
        if condition.equals is not None:
            return fact_value == condition.equals
        if condition.in_ is not None:
            return fact_value in condition.in_
        if condition.not_equals is not None:
            return fact_value != condition.not_equals
        if condition.not_in is not None:
            return fact_value not in condition.not_in
        raise NotImplementedError(f"Unsupported condition {condition}.")

    def _raise_missing_facts(self, missing_fact_ids: Iterable[str]) -> None:
        """
        Raise an InsufficientFactsError for the given missing fact IDs.
        Parameters
        ----------
        missing_fact_ids : Iterable[str]
            Iterable of missing fact IDs.

        Raises
        ------
        InsufficientFactsError
            Always raised with the missing fact details.
        """
        ids = set(missing_fact_ids)
        if not ids:
            # Return in case there are actually no missing facts
            # (defensive programming)
            return

        raise InsufficientFactsError(ids, self.fact_definitions)

    @staticmethod
    def _is_missing_value(value: bool | float | int | str | None) -> bool:
        """
        Determine if a value is considered 'missing' (e.g., None or "unknown").

        Parameters
        ----------
        value : bool | float | int | str | None
            The value to check.

        Returns
        -------
        bool
            True if the value is missing, False otherwise.
        """
        if value is None:
            return True  # for defensive programming in case of runtime type violations
        if isinstance(value, str):
            return value.strip().lower() == "unknown"
        return False

    def _build_result(
        self,
        outcome_id: str,
        triggered: list[str],
        provided_facts: dict[str, bool | str | float | int],
    ) -> InferenceResult:
        """
        Build the InferenceResult for the given outcome ID.

        Parameters
        ----------
        outcome_id : str
            The ID of the selected outcome.
        triggered : list[str]
            The list of triggered rule IDs.

        Returns
        -------
        InferenceResult
            The constructed InferenceResult instance.
        """

        outcome = self.outcomes[outcome_id]
        return InferenceResult(
            provided_facts=provided_facts,
            source=self.meta.source,
            selected_outcome=outcome_id,
            models=list(outcome.models),
            reasoning=outcome.reasoning,
            triggered_rules=triggered,
        )
