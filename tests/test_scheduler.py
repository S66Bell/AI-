from datetime import datetime

from jarvis.scheduler import Schedule, Scheduler, compute_next_run


class DummyRunner:
    def __init__(self):
        self.submitted = []

    def submit(self, goal, source="manual"):
        self.submitted.append((goal, source))

        class T:
            id = "t%d" % len(self.submitted)

        return T()


def test_next_run_daily_today_and_tomorrow():
    s = Schedule(id="a", goal="g", daily_at="08:00")
    assert compute_next_run(s, datetime(2026, 1, 1, 7, 0)) == datetime(2026, 1, 1, 8, 0)
    assert compute_next_run(s, datetime(2026, 1, 1, 8, 0)) == datetime(2026, 1, 2, 8, 0)


def test_next_run_interval():
    s = Schedule(id="a", goal="g", every_minutes=30)
    assert compute_next_run(s, datetime(2026, 1, 1, 7, 0)) == datetime(2026, 1, 1, 7, 30)


def test_scheduler_fires_due_and_persists(tmp_path):
    runner = DummyRunner()
    sched = Scheduler(runner, tmp_path)
    s = sched.add("check news", every_minutes=60)
    assert s.next_run is not None
    # Not due yet.
    assert sched.tick(datetime.fromisoformat(s.created)) == 0
    # Simulate the phone having slept past the due time: fires exactly once.
    late = datetime.fromisoformat(s.next_run).replace(year=2099)
    assert sched.tick(late) == 1
    assert sched.tick(late) == 0
    assert runner.submitted == [("check news", f"schedule:{s.id}")]

    reloaded = Scheduler(DummyRunner(), tmp_path)
    [r] = reloaded.list()
    assert r.last_task_id == "t1" and r.goal == "check news"


def test_scheduler_validation_and_toggle(tmp_path):
    sched = Scheduler(DummyRunner(), tmp_path)
    import pytest

    with pytest.raises(ValueError):
        sched.add("x")
    with pytest.raises(ValueError):
        sched.add("x", daily_at="25:00")
    s = sched.add("x", daily_at="09:30")
    assert sched.set_enabled(s.id, False).enabled is False
    assert sched.due(datetime(2099, 1, 1)) == []
    assert sched.remove(s.id) and not sched.remove(s.id)
