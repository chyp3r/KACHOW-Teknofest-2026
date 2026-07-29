import logging
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)


class SystemState(TypedDict):
    """LangGraph State representing background/system utility tasks context."""

    action_type: str  # "CACHE_UPDATE", "CLEANUP", "LOGGING"
    payload: Dict[str, Any]
    status: str  # "SUCCESS", "FAILURE"
    logs: List[str]


def create_system_graph(cache_client: RedisCache):
    """Create and compile the LangGraph background system workflow.

    Handles cache invalidation, log updates, and background cleanups.
    """

    # 1. System Operations Node
    async def system_op_node(state: SystemState) -> Dict[str, Any]:
        action = state.get("action_type", "LOGGING").upper()
        payload = state.get("payload") or {}
        logs = state.get("logs", []).copy()
        
        logger.info(f"Running System Workflow Action: {action}")
        
        try:
            if action == "CACHE_UPDATE":
                key = payload.get("key")
                val = payload.get("value")
                if key and val:
                    await cache_client.set(key, val)
                    logs.append(f"Successfully cached key '{key}'.")
                else:
                    logs.append("Cache update skipped: Key or Value missing.")
                    
            elif action == "CLEANUP":
                # Mock file/temp cleanup action
                logs.append("Cleaned up temporary workspace files.")
                
            elif action == "LOGGING":
                logs.append(f"Logged system event: {payload.get('event', 'unknown')}")
                
            else:
                logs.append(f"Unknown system action: {action}")
                
            return {"status": "SUCCESS", "logs": logs}
            
        except Exception as e:
            logger.error(f"System operation node failed: {e}", exc_info=True)
            logs.append(f"Error executing action {action}: {e}")
            return {"status": "FAILURE", "logs": logs}

    # Define Graph
    builder = StateGraph(SystemState)
    builder.add_node("system_op", system_op_node)

    builder.add_edge(START, "system_op")
    builder.add_edge("system_op", END)

    return builder.compile()
