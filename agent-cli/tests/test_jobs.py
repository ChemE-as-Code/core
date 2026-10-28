"""jobs.py state machine without real sessions: `uv run --with pytest pytest -q`."""

import json
from argparse import Namespace

import pytest

import jobs


@pytest.fixture
def batch(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "HERE", tmp_path)
    (tmp_path / "wt").mkdir()
    (tmp_path / "pre.md").write_text("PREAMBLE", encoding="utf-8")
    (tmp_path / "impl.md").write_text("implement it", encoding="utf-8")
    f = tmp_path / "b.json"
    f.write_text(json.dumps({
        "preamble_file": "pre.md", "defaults": {"budget": 5, "max_restarts": 1},
        "jobs": [{"name": "impl", "cwd": "wt", "task_file": "impl.md",
                  "then": {"name": "rev", "budget": 3, "task": "review it"}},
                 {"name": "solo", "cwd": "wt", "budget": 50, "task": "big"}]}), encoding="utf-8")
    args = Namespace(total=20, max_sessions=4, min_free_gb=0, emergency_gb=0, stale_pytest_min=60)
    return jobs.Batch(f, args)


def record(b, job, **kw):
    with (jobs.HERE / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"batch": b.state["batch"], "job": job, "finished": "9999", "budget_usd": 5, **kw}) + "\n")


def test_loading(batch):
    assert set(batch.jobs) == {"impl", "rev", "solo"}
    assert batch.jobs["impl"]["task"].startswith("PREAMBLE") and batch.jobs["impl"]["task"].endswith("implement it")
    assert batch.jobs["rev"]["after"] == "impl" and batch.jobs["rev"]["cwd"] == batch.jobs["impl"]["cwd"]
    assert batch.state["jobs"]["rev"]["status"] == "waiting"


def test_done_releases_then_job(batch):
    batch.state["jobs"]["impl"].update(status="running", attempts=1, run_started="")
    record(batch, "impl", subtype="success", final_status="DONE", cost_usd=1.2)
    batch.finish("impl")
    assert batch.state["jobs"]["impl"]["status"] == "done"
    assert batch.state["jobs"]["rev"]["status"] == "queued"


def test_crash_is_retried_then_fails_and_skips_children(batch):
    st = batch.state["jobs"]["impl"]
    st.update(status="running", attempts=1, run_started="")
    record(batch, "impl", subtype="crashed", final_status=None, cost_usd=0.7)
    batch.finish("impl")
    assert st["status"] == "queued" and "crashed" in st["why"]
    st.update(status="running", attempts=2)
    batch.finish("impl")
    assert st["status"] == "failed"
    assert batch.state["jobs"]["rev"]["status"] == "skipped"


def test_spend_counts_crashes_without_cost_at_their_cap(batch):
    record(batch, "impl", subtype="crashed", cost_usd=None)
    record(batch, "impl", subtype="success", cost_usd=1.5)
    assert batch.spent() == pytest.approx(6.5)


def test_budget_gate_skips_jobs_that_do_not_fit(batch, monkeypatch):
    started = []
    monkeypatch.setattr(batch, "start", lambda name, why: (started.append(name),
                        batch.state["jobs"][name].update(status="running", pid=0)))
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    monkeypatch.setattr(batch, "alive", lambda name: True)
    batch.tick()
    assert started == ["impl"]  # solo's $50 cap does not fit the $20 total
