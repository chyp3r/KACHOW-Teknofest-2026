"""Embedding-based matching: layer 2 of the decision ladder.

Sits between the lexical rules (blind to paraphrase) and the fast-tier model
(1-3s a call). Only messages the lexical layer abstained on reach it.
"""

from app.ai.semantic.prototype_matcher import PrototypeMatcher, SemanticMatch

__all__ = ["PrototypeMatcher", "SemanticMatch"]
