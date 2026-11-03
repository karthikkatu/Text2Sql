"""Routes module for text2sql API."""

# Routes module for text2sql API

from .graphs import graphs_router
from .database import database_router

__all__ = ["graphs_router", "database_router"]
