"""User-driven draft revision: instruction parsing, conflict auditing,
conditional legislation re-retrieval and change logging.

See ``app.ai.workflows.revise_graph`` for how these pieces compose into the
revision sub-graph, and ``app.ai.workflows.revise`` for the public entry
point (``run_revise``) that callers outside this package use.
"""

from app.ai.revision.changelog import ChangeEntry, RevisionChangelog, build_changelog
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

__all__ = [
    "ChangeEntry",
    "EditDirective",
    "Operation",
    "RevisionChangelog",
    "RevisionInstruction",
    "Scope",
    "TargetSpan",
    "build_changelog",
    "decompose_instruction",
    "locate_target",
    "needs_reretrieval",
    "parse_revision_instruction",
]
