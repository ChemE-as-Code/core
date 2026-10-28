"""A plant's issues as engineering items: labels read into records, the ``kind: issues`` gate,
``cheme issues``, ``GET /api/issues`` and the GitHub reader (no network: a fake transport)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.foundation.workspace import Workspace
from chemeascode.integrations import github
from chemeascode.integrations.http import HttpClient, Response
from chemeascode.interfaces.cli import app
from chemeascode.project import issues as issues_module
from chemeascode.project.checks import run_checks
from chemeascode.project.issues import issue_from_github, new_issue_links

runner = CliRunner()


@pytest.fixture(autouse=True)
def fresh_cache():
    issues_module.clear_cache()
    yield
    issues_module.clear_cache()


def item(number: int, labels: list[str], state: str = "open", title: str = "x") -> dict:
    return {
        "number": number,
        "title": title,
        "state": state,
        "labels": [{"name": n} for n in labels],
        "html_url": f"https://github.com/o/r/issues/{number}",
        "created_at": "2026-10-25T00:00:00Z",
        "updated_at": "2026-10-25T00:00:00Z",
        "closed_at": None,
    }


ITEMS = [
    item(1, ["process:p1", "type:hold", "gate:basic", "discipline:control", "waiting:input"]),
    item(2, ["process:p1", "type:action", "gate:concept", "status:for-verification"]),
    item(3, ["process:p1", "type:action", "gate:detail"]),
    item(4, ["process:p1", "type:change", "gate:basic"], state="closed"),
]


@pytest.fixture
def tracked(plant: Path, monkeypatch) -> Path:
    path = plant / "plant.yaml"
    path.write_text(
        path.read_text()
        + 'issues: {repository: o/r, label: "process:p1", forms: {action: 1-action-item.yml}}\n'
    )
    monkeypatch.setattr(github, "list_issues", lambda *a, **k: list(ITEMS))
    monkeypatch.chdir(plant)
    return plant


def gates(root: Path) -> dict[str, tuple[str, str]]:
    return {
        c.id: (c.status, c.detail)
        for c in run_checks(Workspace(root))
        if c.id.startswith("issues-")
    }


def test_labels_become_engineering_fields():
    issue = issue_from_github(ITEMS[0])
    assert (issue.type, issue.gate, issue.status, issue.waiting) == (
        "hold",
        "basic",
        "open",
        "input",
    )
    assert issue.disciplines == ["control"]
    assert issue_from_github(ITEMS[1]).status == "for-verification"
    assert issue_from_github(ITEMS[3]).status == "closed"


def test_without_issues_the_gates_are_not_applicable(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    assert set(gates(plant).values()) == {("n/a", "plant.yaml declares no issues")}
    assert runner.invoke(app, ["issues"]).exit_code == 2


def test_open_items_block_their_gate_and_the_later_ones(tracked: Path):
    result = gates(tracked)
    assert result["issues-concept"][0] == "fail" and "#2" in result["issues-concept"][1]
    # basic: #1 (gate:basic) and #2 (concept, still open); #4 is closed
    status, detail = result["issues-basic"]
    assert status == "fail" and "#1" in detail and "#2" in detail and "#4" not in detail
    assert "#3" in result["issues-detail"][1]


def test_a_gate_can_count_some_types_only(tracked: Path):
    checks = tracked / "checks" / "checks.yaml"
    checks.write_text(
        checks.read_text().replace(
            "  - id: issues-basic\n", "  - id: issues-basic\n    types: [change]\n"
        )
    )
    assert gates(tracked)["issues-basic"][0] == "pass"


def test_unreadable_issues_never_pass(tracked: Path, monkeypatch):
    calls = []

    def offline(*args, **kwargs):
        calls.append(args)
        raise github.GitHubError("no GitHub token")

    monkeypatch.setattr(github, "list_issues", offline)
    result = gates(tracked)
    assert {status for status, _ in result.values()} == {"fail"}
    assert result["issues-concept"][1].startswith("not evaluated")
    assert len(calls) == 1  # one attempt per run, not one per gate


def test_a_stale_or_mistyped_gate_label_still_blocks(tracked: Path, monkeypatch):
    items = [
        item(5, ["process:p1", "type:action", "gate:detail", "gate:basic"]),
        item(6, ["process:p1", "type:action", "gate:Basic"]),
    ]
    monkeypatch.setattr(github, "list_issues", lambda *a, **k: items)
    assert issue_from_github(items[0]).gate == "basic"
    result = gates(tracked)
    assert "#5" in result["issues-basic"][1] and "#5" not in result["issues-concept"][1]
    assert "#6" in result["issues-concept"][1]


def test_new_issue_links_fill_in_the_form(tracked: Path):
    links = new_issue_links(Workspace(tracked), {"refs": "P-04 PIC-4101"})
    assert links["action"].startswith(
        "https://github.com/o/r/issues/new?template=1-action-item.yml"
    )
    assert "process=p1" in links["action"] and "refs=P-04%20PIC-4101" in links["action"]


def test_cli_lists_by_gate(tracked: Path):
    result = runner.invoke(app, ["issues"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("#2") and "before concept" in lines[0]
    data = json.loads(runner.invoke(app, ["issues", "--json"]).output)
    assert sorted(data["blocking"]["basic"]) == [1, 2]
    assert data["open_by_gate"]["basic"] == {"hold": 1}


def test_api(tracked: Path, plant: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    api = TestClient(create_app(tracked, None, allowed_hosts=["testserver"]))
    assert api.get("/api/repo").json()["has_issues"] is True
    data = api.get("/api/issues").json()
    assert [i["number"] for i in data["issues"]] == [4, 3, 2, 1]
    assert "action" in data["new"]


def test_github_reader_pages_and_skips_pull_requests(monkeypatch):
    pages = {
        1: [{"number": n, "title": "t", "state": "open", "labels": []} for n in range(100)],
        2: [{"number": 100, "pull_request": {}}, {"number": 101, "state": "open", "labels": []}],
    }
    seen = []

    def transport(request):
        seen.append(request)
        from urllib.parse import parse_qs, urlparse

        page = int(parse_qs(urlparse(request.url).query)["page"][0])
        return Response(200, json.dumps(pages[page]), request.url)

    found = github.list_issues(
        "o/r", "process:p1", access_token="t", client=HttpClient(transport=transport)
    )
    assert len(found) == 101 and found[-1]["number"] == 101
    assert seen[0].headers["Authorization"] == "Bearer t"


def test_github_reader_needs_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    with pytest.raises(github.GitHubError, match="no GitHub token"):
        github.list_issues("o/r", "process:p1")


def test_github_reader_refuses_redirects_and_partial_lists():
    moved = HttpClient(transport=lambda r: Response(301, "", r.url))
    with pytest.raises(github.GitHubError, match="HTTP 301"):
        github.list_issues("o/r", "process:p1", access_token="t", client=moved)
    full = json.dumps([{"number": n, "state": "open", "labels": []} for n in range(100)])
    endless = HttpClient(transport=lambda r: Response(200, full, r.url))
    with pytest.raises(github.GitHubError, match="more than"):
        github.list_issues("o/r", "process:p1", access_token="t", client=endless)


def test_the_token_only_goes_to_api_github_com(plant: Path):
    path = plant / "plant.yaml"
    path.write_text(
        path.read_text() + 'issues: {repository: o/r, label: "p", api: "https://evil.example"}\n'
    )
    with pytest.raises(Exception, match="api"):
        Workspace(plant).config()


def test_redirects_are_returned_not_followed():
    import threading
    from functools import partial
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from chemeascode.integrations.http import Request, no_redirect_opener, urllib_transport

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(301)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    send = partial(urllib_transport, opener=no_redirect_opener())
    url = f"http://127.0.0.1:{server.server_port}/start"
    reply = send(Request("GET", url, {"Authorization": "Bearer t"}))
    server.server_close()
    assert reply.status == 301 and [path for path, _ in seen] == ["/start"]
