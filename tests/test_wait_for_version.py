from scripts.wait_for_version import wait_for_version


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def run(answers: list[str | None], timeout: float = 30, interval: float = 10) -> bool:
    clock = Clock()
    queue = iter(answers)
    return wait_for_version(
        "abc",
        lambda: next(queue, None),
        timeout,
        interval,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_succeeds_when_version_matches() -> None:
    assert run(["abc"])


def test_waits_through_not_ready_and_old_versions() -> None:
    assert run([None, "old", "abc"])


def test_old_version_forever_is_a_failure_not_a_pass() -> None:
    assert not run(["old"] * 10)


def test_unreachable_forever_is_a_failure() -> None:
    assert not run([None] * 10)
