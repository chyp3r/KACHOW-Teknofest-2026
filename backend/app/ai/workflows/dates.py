"""Server-resolved "today", for the one field a draft must never ask about.

A generated draft's own "Tarih:" line is the date it is written on, not a
fact extracted from a document or supplied by the user -- asking the user
for it (see Görev's bug report item 3) makes as little sense as asking them
what day it is. This module is the single place that date comes from, so
every caller (the writer's brief, the deterministic placeholder backstop,
the verifier's groundedness check) agrees on the same value for the same
turn.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def today_tr() -> str:
    """The current date in the app's configured timezone, Turkish format.

    Returns:
        ``"DD.MM.YYYY"``, matching the format real Turkish official
        correspondence and this codebase's own examples already use (see
        ``datasets/resmi_yazisma``).
    """
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).strftime("%d.%m.%Y")
