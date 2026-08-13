"""This module intentionally holds no tests.

It originally covered a graph shape that no longer exists
(``EditorOutput``/``PlanOutput``/``QueryRewriteOutput``/``create_system_graph``
were all removed from the codebase before this file was last touched), which
failed at collection and took the rest of the workflow test suite down with
it. Per the Phase 11 implementation plan, its coverage now lives split by
sub-graph instead of in one file:

- ``test_correspondence.py``   -- resolve_correspondence_type's precedence and genre/sub-genre matching
- ``test_draft_verifier.py``   -- the deterministic groundedness/structure verifier
- ``test_llm_judge.py``        -- judge_draft() and merge_verdicts()
- ``test_draft_loop.py``       -- the draft graph's reflexion loop end-to-end
- ``test_rag_graph.py``        -- build_search_query() and the retrieval sub-graph
- ``test_routing_graph.py``    -- the unit-routing sub-graph's short-circuits
- ``test_step_dependencies.py``-- planning_graph's dependency-skip guard (D6)
- ``../../integration/test_hitl_flow.py`` -- the planning graph's interrupt/resume gate
"""
