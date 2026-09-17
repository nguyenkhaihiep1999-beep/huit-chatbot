import uuid
import logging
from contextvars import ContextVar
from typing import Optional

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

def get_current_request_id() -> str:
    rid = request_id_ctx.get()
    if not rid:
        rid = f"req-{uuid.uuid4().hex[:12]}"
        request_id_ctx.set(rid)
    return rid

def set_current_request_id(rid: Optional[str] = None) -> str:
    new_rid = rid or f"req-{uuid.uuid4().hex[:12]}"
    request_id_ctx.set(new_rid)
    return new_rid

class RequestIdFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = get_current_request_id()
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
)
for handler in logging.root.handlers:
    handler.addFilter(RequestIdFilter())

logger = logging.getLogger("huit_chatbot")
logger.addFilter(RequestIdFilter())
