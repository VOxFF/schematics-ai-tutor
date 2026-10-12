"""Claude down: which failures mark it, the window, and the guarded client."""

import asyncio

import anthropic
import pytest

from app.claude_status import ClaudeDown, ClaudeStatus, GuardedClaude, available, outage
from tests.conftest import FakeClaude, text_response


class StatusError(anthropic.APIError):
    def __init__(self, status: int, message: str = "error"):
        super().__init__(message, request=None, body=None)
        self.status_code = status


@pytest.mark.parametrize("error,reason", [
    (anthropic.APITimeoutError(request=None), "timeout"),
    (anthropic.APIConnectionError(request=None), "connection"),
    (StatusError(429), "http_429"),
    (StatusError(529), "http_529"),
    (StatusError(500), "http_500"),
    (StatusError(401), "http_401"),
    (StatusError(400, "Your credit balance is too low to access the Anthropic API."), "account"),
    (StatusError(400, "You have reached your specified API usage limits."), "account"),
    (StatusError(400, "messages: field required"), None),  # this request, not Claude
    (ClaudeDown(10), None),
])
def test_which_failures_mean_claude_is_down(error, reason):
    assert outage(error) == reason


def test_down_for_down_s_then_tried_again():
    now = [0.0]
    status = ClaudeStatus(300, clock=lambda: now[0])
    status.failed(StatusError(400, "bad request"))
    assert not status.down
    status.failed(StatusError(529))
    assert status.down
    now[0] = 299
    with pytest.raises(ClaudeDown):
        status.check()
    now[0] = 300
    assert not status.down


def test_the_guarded_client_refuses_while_down_and_marks_on_failure():
    class Failing(FakeClaude):
        async def create(self, **kwargs):
            self.requests.append(kwargs)
            raise StatusError(529)

    failing = Failing([])
    guarded = GuardedClaude(failing, ClaudeStatus(300))
    assert available(guarded)
    for _ in range(2):
        with pytest.raises(anthropic.APIError):
            asyncio.run(guarded.with_options(timeout=5).messages.create(model="m"))
    assert len(failing.requests) == 1 and guarded.down and not available(guarded)
    assert not available(None)


def test_the_guarded_client_passes_responses_through():
    guarded = GuardedClaude(FakeClaude([text_response({"ok": True})]), ClaudeStatus(300))
    response = asyncio.run(guarded.messages.create(model="m"))
    assert response.content[0].text == '{"ok": true}'
