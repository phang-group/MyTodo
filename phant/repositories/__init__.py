"""
phant.repositories — data-access layer for PHANT cognition.

One repository per aggregate. Each takes a request-scoped SQLAlchemy Session and
encapsulates all queries for its entity, so services and routers never write raw
queries against PHANT tables. Mutating methods commit within the request scope.
"""

from .contexts    import ContextRepository
from .sessions    import SessionRepository
from .memories    import MemoryRepository
from .decisions   import DecisionRepository
from .outcomes    import OutcomeRepository
from .constraints import ConstraintRepository
from .divergences import DivergenceRepository

__all__ = [
    "ContextRepository",
    "SessionRepository",
    "MemoryRepository",
    "DecisionRepository",
    "OutcomeRepository",
    "ConstraintRepository",
    "DivergenceRepository",
]
