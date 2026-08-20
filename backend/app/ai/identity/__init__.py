from app.ai.identity.company_profile import CompanyProfile, ProfileProvider
from app.ai.identity.injection import format_agent_identity, format_identity_brief_section

# app.ai.identity.parties is deliberately NOT re-exported here. It imports
# app.ai.verification.draft_verifier (to reuse the deterministic
# token-overlap ladder rather than inventing a second one -- see parties.py's
# own docstring), and importing that submodule also runs
# app.ai.verification's own package __init__, which pulls in a large chunk
# of app.ai (revision -> workflows -> retrieval -> vectorstore -> embeddings
# -> ...) that circles back to app.ai.identity.company_profile via
# app.ai.agents.assistant. Doing that eagerly from THIS package's own
# __init__ turned an ordinary `from app.ai.identity.company_profile import
# CompanyProfile` (used all over the codebase, including from inside that
# same cascade) into a circular import. Importing app.ai.identity.parties
# directly (`from app.ai.identity.parties import PartyContext`, as every
# caller does) is unaffected -- only re-exporting it from this __init__ was
# the problem.
__all__ = [
    "CompanyProfile",
    "ProfileProvider",
    "format_agent_identity",
    "format_identity_brief_section",
]
