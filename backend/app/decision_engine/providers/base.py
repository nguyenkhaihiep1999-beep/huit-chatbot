"""
base.py
Neutral Decision Provider Interface.
Định nghĩa giao diện trừu tượng trung lập, không phụ thuộc vào TypeSafe hay bất kỳ nhà cung cấp cụ thể nào.
"""
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional
from backend.app.decision_engine.contracts import DecisionRequest, DecisionResult


_api_call_observer: ContextVar[Optional[Callable[[], None]]] = ContextVar(
    "decision_api_call_observer", default=None
)


@contextmanager
def observe_api_calls(observer: Callable[[], None]):
    """Bind HTTP-attempt evidence to this async request, never a shared provider."""
    token = _api_call_observer.set(observer)
    try:
        yield
    finally:
        _api_call_observer.reset(token)


def notify_api_call() -> None:
    """Providers call this immediately before an HTTP attempt, including retries.

    An attempt is not proof of server receipt, successful inference or billing.
    """
    observer = _api_call_observer.get()
    if observer is not None:
        observer()


class DecisionProviderError(Exception):
    """Lỗi cơ sở cho các thao tác của Decision Provider."""
    def __init__(self, message: str, retryable: bool = False, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class DecisionAuthenticationError(DecisionProviderError):
    """401/403 Unauthorized/Forbidden - Không retry."""
    def __init__(self, message: str = "Lỗi xác thực API Key với nhà cung cấp"):
        super().__init__(message, retryable=False, status_code=401)


class DecisionQuotaExhaustedError(DecisionProviderError):
    """402 Payment Required hoặc hết credit/quota - Không retry."""
    def __init__(self, message: str = "Tài khoản TypeSafe Jev đã hết credit hoặc quota"):
        super().__init__(message, retryable=False, status_code=402)


class DecisionValidationError(DecisionProviderError):
    """422 Unprocessable Entity - Payload sai định dạng - Không retry."""
    def __init__(self, message: str = "Dữ liệu yêu cầu không hợp lệ với schema của nhà cung cấp"):
        super().__init__(message, retryable=False, status_code=422)


class DecisionRateLimitError(DecisionProviderError):
    """429 Too Many Requests - Retry có giới hạn."""
    def __init__(
        self,
        message: str = "Vượt quá giới hạn tần suất (Rate limited)",
        retry_after: Optional[float] = None,
    ):
        super().__init__(message, retryable=True, status_code=429)
        self.retry_after = retry_after


class DecisionServerError(DecisionProviderError):
    """5xx Server Error - Lỗi máy chủ nhà cung cấp - Retry có giới hạn."""
    def __init__(self, message: str = "Lỗi hệ thống từ máy chủ nhà cung cấp", status_code: int = 500):
        super().__init__(message, retryable=True, status_code=status_code)


class DecisionTimeoutError(DecisionProviderError):
    """Timeout khi kết nối nhà cung cấp."""
    def __init__(self, message: str = "Quá thời gian chờ phản hồi (Timeout)"):
        super().__init__(message, retryable=True, status_code=504)


class BaseDecisionProvider(ABC):
    """Giao diện trừu tượng cho Decision Provider."""

    @abstractmethod
    def get_name(self) -> str:
        """Trả về tên định danh của provider (ví dụ: typesafe_jev)."""
        pass

    @abstractmethod
    async def decide(
        self,
        request: DecisionRequest,
        total_budget_ms: Optional[float] = None,
    ) -> DecisionResult:
        """Return a decision; call notify_api_call() immediately before actual HTTP.

        Local/mock implementations that do not send HTTP must not notify.
        """
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """Kiểm tra sức khỏe thụ động/nhẹ của provider (không gọi paid inference API)."""
        pass
