from datetime import datetime
from typing import Any, Awaitable, Callable, TypeAlias

AsyncCallable: TypeAlias = Callable[..., Awaitable[Any]]
DateTimeUTC: TypeAlias = datetime
