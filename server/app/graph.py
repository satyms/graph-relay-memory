import logging
from typing import Any, Dict, List, Optional
from falkordb import FalkorDB
import redis.exceptions
from server.app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[FalkorDB] = None


def get_client() -> FalkorDB:
    """Return the singleton FalkorDB client configured from settings."""
    global _client
    if _client is None:
        _client = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)
    return _client


def get_graph(graph_name: str):
    """Retrieve a graph instance by name."""
    client = get_client()
    return client.select_graph(graph_name)


def execute_query(graph_name: str, query: str, params: Optional[Dict[str, Any]] = None):
    """
    Execute a parameterised read-write Cypher query on the specified graph.
    All parameters are strictly passed as a dictionary.
    """
    g = get_graph(graph_name)
    logger.debug("Executing RW query on '%s': %s (params: %s)", graph_name, query, params)
    return g.query(query, params=params or {})


def execute_ro_query(graph_name: str, query: str, params: Optional[Dict[str, Any]] = None):
    """
    Execute a parameterised read-only Cypher query using FalkorDB ro_query.
    If the graph key does not yet exist in FalkorDB, safely returns an empty result object.
    """
    g = get_graph(graph_name)
    logger.debug("Executing RO query on '%s': %s (params: %s)", graph_name, query, params)
    try:
        return g.ro_query(query, params=params or {})
    except redis.exceptions.ResponseError as exc:
        if "Invalid graph operation on empty key" in str(exc):
            logger.debug("Graph '%s' is empty or not yet initialized in FalkorDB; returning empty result.", graph_name)
            # Create a lightweight shim matching result_set interface
            class EmptyQueryResult:
                result_set: List[List[Any]] = []
            return EmptyQueryResult()
        raise
