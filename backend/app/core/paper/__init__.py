"""Paper trading module."""
from app.core.paper.events import paper_events, _PaperEventBus
from app.core.paper.manager import PaperAccountManager
from app.core.paper.account import PaperAccount, PaperPositionRuntime
from app.core.paper.matcher import PaperMatcher, PaperTradeRuntime, PaperExecutionResult

__all__ = [
    "PaperAccountManager", "PaperAccount", "PaperPositionRuntime",
    "PaperMatcher", "PaperTradeRuntime", "PaperExecutionResult",
    "paper_events", "_PaperEventBus",
]
