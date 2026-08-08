"""User-driven draft revision: instruction parsing, conflict auditing,
conditional legislation re-retrieval and change logging.

See ``app.ai.workflows.revise_graph`` for how these pieces compose into the
revision sub-graph, and ``app.ai.workflows.revise`` for the public entry
point (``run_revise``) that callers outside this package use.
"""

from app.ai.revision.changelog import ChangeEntry, RevisionChangelog, build_changelog
from app.ai.revision.conflict import (
    ConflictFinding,
    ConflictReport,
    assess_conflicts_llm,
    detect_conflicts_deterministic,
    merge_conflicts,
)
from app.ai.revision.instruction import (
    EditDirective,
    Operation,
    RevisionInstruction,
    Scope,
    TargetSpan,
    decompose_instruction,
    locate_target,
    needs_reretrieval,
    parse_revision_instruction,
)
from app.ai.revision.retrieval import maybe_extend_context

__all__ = [
    "ChangeEntry",
    "ConflictFinding",
    "ConflictReport",
    "EditDirective",
    "Operation",
    "RevisionChangelog",
    "RevisionInstruction",
    "Scope",
    "TargetSpan",
    "assess_conflicts_llm",
    "build_changelog",
    "decompose_instruction",
    "detect_conflicts_deterministic",
    "locate_target",
    "maybe_extend_context",
    "merge_conflicts",
    "needs_reretrieval",
    "parse_revision_instruction",
]
