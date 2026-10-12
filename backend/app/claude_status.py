"""Claude down: after an outage-like failure, Claude is skipped for a while (docs/design.md §6,
Fallback when Claude is unavailable).

`GuardedClaude` wraps the API client. Every call goes through it: while Claude is down a call
fails at once with `ClaudeDown`, an `anthropic.APIConnectionError`, so the callers' existing
error handling applies, and a call that fails like an outage marks Claude down for
`claude.down_s`. Generation then serves the fallback pack, and the tutor its plain messages,
without waiting out timeouts.
"""

import time

import anthropic

# A 400 or 403 with one of these is the account, not the request: an exhausted balance or spend limit.
_ACCOUNT = ("credit balance", "usage limit", "billing", "spend limit")


class ClaudeDown(anthropic.APIConnectionError):
    """A call refused because Claude is marked down."""

    def __init__(self, seconds: float):
        super().__init__(message=f"Claude is marked down for another {seconds:.0f} s.", request=None)  # no HTTP request was made


def outage(error: Exception) -> str | None:
    """Why `error` means Claude is unavailable for everyone, or None if it is about this request."""
    if isinstance(error, ClaudeDown):
        return None
    if isinstance(error, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(error, anthropic.APIConnectionError):
        return "connection"
    status = getattr(error, "status_code", None)
    if status in (401, 429, 529) or (isinstance(status, int) and status >= 500):
        return f"http_{status}"
    if status in (400, 403) and any(word in str(error).lower() for word in _ACCOUNT):
        return "account"
    return None


class ClaudeStatus:
    def __init__(self, down_s: float = 300, usage_log=None, clock=time.monotonic):
        self.down_s = down_s
        self.usage_log = usage_log
        self.clock = clock
        self.until = 0.0

    @property
    def down(self) -> bool:
        return self.clock() < self.until

    def check(self) -> None:
        if self.down:
            raise ClaudeDown(self.until - self.clock())

    def failed(self, error: Exception) -> None:
        reason = outage(error)
        if reason is None:
            return
        self.until = self.clock() + self.down_s
        if self.usage_log is not None:
            self.usage_log.event("claude_down", reason=reason, down_s=self.down_s, error=str(error)[:300])


class GuardedClaude:
    """The API client with `ClaudeStatus` around `messages.create`."""

    def __init__(self, client, status: ClaudeStatus):
        self._client = client
        self.status = status

    @property
    def down(self) -> bool:
        return self.status.down

    def with_options(self, **options) -> "GuardedClaude":
        return GuardedClaude(self._client.with_options(**options), self.status)

    @property
    def messages(self) -> "_Messages":
        return _Messages(self._client.messages, self.status)


class _Messages:
    def __init__(self, messages, status: ClaudeStatus):
        self._messages = messages
        self.status = status

    async def create(self, **request):
        self.status.check()
        try:
            return await self._messages.create(**request)
        except anthropic.APIError as error:
            self.status.failed(error)
            raise


def available(claude) -> bool:
    """Whether Claude can be called now: configured and not marked down."""
    return claude is not None and not getattr(claude, "down", False)
