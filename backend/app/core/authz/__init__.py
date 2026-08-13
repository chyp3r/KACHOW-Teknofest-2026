"""In-house ABAC policy decision point (PDP).

Deliberately not OPA/Casbin: the rest of the deterministic decision layer
(``app.ai.policy.schema``) already commits to typed, frozen, import-time
-validated Python over an external engine or config format, and this module
follows the same convention -- see ``rules.py``'s module docstring for the
full reasoning.

Layering rule this package must never violate: ``app.ai.*`` never imports
``app.domains.*`` (see ``app.domains.units.provider``'s docstring), so this
package is never imported from ``app.ai.*``. Confidentiality clearance
(``app.core.permissions.role_checker``) stays a separate, downstream gate --
see ``engine.py``'s module docstring for the composition order.

Public surface:
    - ``attributes``: ``Subject``, ``Resource``, ``Environment``, ``Action``.
    - ``rules``: the frozen built-in role/action rule table.
    - ``engine``: ``authorize()`` (pure) and ``role_permitted()``.
    - ``model``/``repository``: the ``permission_grants`` persistence layer.
    - ``cache``: the Redis epoch-invalidated decision cache.
    - ``service``: ``AuthzService``, the async orchestration wrapping all of
      the above for DB-backed grant consumers.
    - ``dependency``: ``require_permission()``, the FastAPI PEP.
"""
