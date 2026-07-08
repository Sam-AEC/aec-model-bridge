import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HelloWorldModule:
    def validate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Hook validate logic
        name = payload.get("name", "")
        if name.lower() == "blocker":
            return {"blockers": ["The name 'blocker' is explicitly disallowed."]}
        elif name.lower() == "warning":
            return {"warnings": ["Using the name 'warning' triggers a warning."]}
        return {"ok": True}

    def say_hello(self, name: str) -> Dict[str, Any]:
        return {
            "status": "success",
            "message": f"Hello, {name}!"
        }

    def on_result(self, payload: Dict[str, Any]) -> None:
        logger.info(f"HelloWorldModule post-result hook called with: {payload}")
