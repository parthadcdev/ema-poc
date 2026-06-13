from ema_poc.agent.rate_limiter import RateLimiter


def _fake_clock():
    """Returns (clock_fn, sleep_fn, state) with a controllable monotonic clock."""
    state = {"t": 0.0, "sleeps": []}

    def clock():
        return state["t"]

    def sleep(d):
        state["sleeps"].append(d)
        state["t"] += d

    return clock, sleep, state


def test_first_acquire_does_not_sleep():
    clock, sleep, state = _fake_clock()
    rl = RateLimiter(60, clock=clock, sleep=sleep)  # 60/min -> 1s min interval
    rl.acquire()
    assert state["sleeps"] == []


def test_second_acquire_waits_min_interval():
    clock, sleep, state = _fake_clock()
    rl = RateLimiter(60, clock=clock, sleep=sleep)  # 1s interval
    rl.acquire()
    rl.acquire()  # clock hasn't advanced -> must wait ~1s
    assert state["sleeps"] == [1.0]


def test_zero_rpm_disables_limiting():
    clock, sleep, state = _fake_clock()
    rl = RateLimiter(0, clock=clock, sleep=sleep)
    rl.acquire()
    rl.acquire()
    assert state["sleeps"] == []
