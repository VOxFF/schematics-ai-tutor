import json

from app.config import load_config
from app.rate_limits import DailyBudget, RateLimiter, SlidingWindow, client_ip


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_root_rate_limits_load_into_the_config():
    limits = load_config()["rate_limits"]
    assert limits["claude_budget"]["usd_per_day"] > 0
    assert limits["grid"]["max_points"] == 30


def test_sliding_window_allows_up_to_the_limit_per_key_then_frees_up():
    clock = Clock()
    window = SlidingWindow(2, 60, clock)
    assert window.allow("a") and window.allow("a")
    assert not window.allow("a")
    assert window.allow("b")  # keys are independent
    assert window.retry_after("a") == 60
    clock.now = 60
    assert window.allow("a")


def test_budget_caps_background_work_first(tmp_path):
    budget = DailyBudget(10, background_share=0.8)
    budget.spend(7.9)
    assert budget.allows(background=True)
    budget.spend(0.2)
    assert not budget.allows(background=True)
    assert budget.allows()
    budget.spend(2)
    assert not budget.allows()


def test_budget_survives_a_restart_and_resets_the_next_day(tmp_path):
    state = tmp_path / "claude-budget.json"
    DailyBudget(10, state_file=state, today=lambda: "2026-10-11").spend(4.5)
    assert json.loads(state.read_text()) == {"day": "2026-10-11", "usd": 4.5}
    assert DailyBudget(10, state_file=state, today=lambda: "2026-10-11").usd == 4.5
    day = ["2026-10-11"]
    budget = DailyBudget(10, state_file=state, today=lambda: day[0])
    day[0] = "2026-10-12"
    assert budget.allows() and budget.usd == 0


def test_unpriced_calls_cost_nothing():
    budget = DailyBudget(10)
    budget.spend(None)
    assert budget.usd == 0


def test_open_sessions_per_ip(tmp_path):
    limits = RateLimiter({"sessions": {"per_ip_per_hour": 30, "open_per_ip": 2}})
    assert limits.session_opened("1.2.3.4") and limits.session_opened("1.2.3.4")
    assert not limits.session_opened("1.2.3.4")
    assert limits.session_opened("5.6.7.8")
    limits.session_closed("1.2.3.4")
    assert limits.session_opened("1.2.3.4")


def test_grid_errors():
    limits = RateLimiter({"grid": {"max_points": 30, "max_components": 1, "max_wires": 2}})
    board = {"grid": {"columns": 31, "rows": 8}, "components": [{}, {}], "wires": [{}, {}]}
    assert limits.grid_errors(board) == ["grid larger than 30 x 30", "more than 1 components"]


def test_state_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEMATICS_STATE_DIR", str(tmp_path / "volume" / "state"))
    limits = RateLimiter.from_settings({"claude_budget": {"usd_per_day": 1}}, tmp_path)
    limits.budget.spend(0.5)
    assert (tmp_path / "volume" / "state" / "claude-budget.json").exists()


def test_client_ip_prefers_flys_header():
    class Conn:
        def __init__(self, headers, host):
            self.headers, self.client = headers, type("C", (), {"host": host})()

    assert client_ip(Conn({"fly-client-ip": "9.9.9.9"}, "172.16.0.1")) == "9.9.9.9"
    assert client_ip(Conn({}, "127.0.0.1")) == "127.0.0.1"
