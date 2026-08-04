"""Conversation memory lives in the planning graph's checkpointed state
(``PlanningState.history`` / ``history_summary``, see
``app.ai.workflows.planning_graph`` and ``docs/development/ai-standards.md``
-> Memory), not in this package. A ``BaseMemory``/``CheckpointMemory`` pair
used to live here as a read-only view over that same state, but nothing ever
instantiated it -- a second, always-empty abstraction over a single real
store was more surface than the store needed.
"""
