"""Guards the SSE event vocabulary against silent drift.

``app.ai.workflows.events`` builds and pushes plain dicts (the queue is a
generic transport, not a place to pay Pydantic validation cost on every
token). ``event_schema.py`` writes the shape of each event name down once in
code; this test makes sure ``WORKFLOW_EVENT_NAMES`` -- the frozen set the
frontend's hand-written TypeScript union is checked against -- actually
matches the ``event`` literal every model class declares, since the two are
deliberately not derived from each other via reflection.
"""

from app.ai.workflows import event_schema
from app.ai.workflows.event_schema import WORKFLOW_EVENT_NAMES

EVENT_MODELS = [
    event_schema.SessionEvent,
    event_schema.NodeStartEvent,
    event_schema.NodeEndEvent,
    event_schema.NodeErrorEvent,
    event_schema.NodeSkippedEvent,
    event_schema.TokenEvent,
    event_schema.ToolCallEvent,
    event_schema.PartialResultEvent,
    event_schema.PlanningCompletedEvent,
    event_schema.InterruptEvent,
    event_schema.FinalResultEvent,
    event_schema.ErrorEvent,
]


def _literal_event_name(model: type) -> str:
    return model.model_fields["event"].default


def test_every_declared_model_names_an_event_in_the_frozen_set():
    for model in EVENT_MODELS:
        name = _literal_event_name(model)
        assert name in WORKFLOW_EVENT_NAMES, (
            f"{model.__name__} declares event={name!r}, missing from WORKFLOW_EVENT_NAMES"
        )


def test_the_frozen_set_has_no_names_without_a_backing_model():
    declared = {_literal_event_name(model) for model in EVENT_MODELS}
    assert WORKFLOW_EVENT_NAMES == declared


def test_every_event_model_carries_a_seq_field_for_client_side_ordering():
    """seq is what lets the client distinguish an interrupt replay (see
    emit_interrupt's docstring) from a genuinely new event."""
    for model in EVENT_MODELS:
        assert "seq" in model.model_fields


def test_workflow_event_names_matches_what_the_emit_helpers_actually_send():
    """Cross-check against the literal event strings hard-coded at their
    publish sites, so a renamed event string would fail here even without
    exercising every call site at runtime.

    Most events go through app.ai.workflows.events' emit_* helpers, but
    "session", "planning_completed" and "final_result"/"error" are published
    directly by the chat orchestration layer (there is no sub-graph node to
    attach an emit_* call to for "a whole run just started/finished").
    """
    import inspect

    import app.ai.workflows.events as events_module
    import app.ai.workflows.planning_graph as planning_graph_module
    import app.domains.chat.chat_service as chat_service_module
    import app.domains.chat.router as chat_router_module

    source = "\n".join(
        inspect.getsource(module)
        for module in (
            events_module,
            planning_graph_module,
            chat_service_module,
            chat_router_module,
        )
    )
    for name in WORKFLOW_EVENT_NAMES:
        assert f'"event": "{name}"' in source or f"'event': '{name}'" in source, (
            f"No publish site appears to send event={name!r}"
        )
