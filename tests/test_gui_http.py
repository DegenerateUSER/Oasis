"""Non-visual HTTP contract: session isolation, safe inputs, and API integration."""
import contextlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture
def server(tmp_path):
    from tfmutate.gui.server import create_server
    static = tmp_path / "assets"
    static.mkdir()
    (static / "index.html").write_text('<meta name="oasis-token" content="__OASIS_TOKEN__">')
    instance = create_server(port=0, data_dir=tmp_path / "state", static_dir=static)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=3)


def request(server, path, *, method="GET", body=None, token=True, headers=None):
    values = dict(headers or {})
    if token:
        values["X-Oasis-Token"] = server.token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        values["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}", data=data, method=method, headers=values)
    try:
        response = urllib.request.urlopen(req, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with contextlib.closing(response):
        return response.code, dict(response.headers), response.read()


def test_api_requires_session_token(server):
    code, _, _ = request(server, "/api/bootstrap", token=False)
    assert code == 403


def test_bootstrap_uses_actual_catalog(server):
    from tfmutate.mutators import CATALOG
    code, _, body = request(server, "/api/bootstrap")
    assert code == 200
    assert {item["id"] for item in json.loads(body)["operators"]} == set(CATALOG)


def test_index_injects_session_without_inline_script(server):
    code, headers, body = request(server, "/", token=False)
    assert code == 200
    assert server.token.encode() in body
    assert b"__OASIS_TOKEN__" not in body
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("headers", [{"Origin": "https://attacker.invalid"}, {"Host": "attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}])
def test_cross_origin_requests_are_rejected_before_content(server, headers):
    code, _, _ = request(server, "/", token=False, headers=headers)
    assert code == 403


def test_real_import_flows_through_shared_summary(server):
    from tfmutate.metrics import summarize
    csv = "repo_name,mutant_id,operator_id,operator_category,test_status,validate_status,survival_reason\nrepo,m1,MUT_RES_002,resource,survived,valid,unknown\n"
    code, _, body = request(server, "/api/import", method="POST", body={"name": "Actual import test", "csv": csv})
    assert code == 201
    dataset = json.loads(body)
    assert dataset["summary"]["overall"] == summarize(dataset["rows"])
    assert dataset["provenance"]["kind"] == "imported"
    code, _, body = request(server, f"/api/datasets/{dataset['id']}/csv")
    assert code == 200 and body.decode() == csv
    code, _, body = request(server, "/api/datasets")
    assert json.loads(body)["datasets"][0]["id"] == dataset["id"]


def test_imported_csv_never_grants_filesystem_log_access(server):
    code, _, _ = request(server, "/api/datasets/" + "a" * 32 + "/logs?path=/etc/passwd")
    assert code in {400, 404}


def test_static_path_traversal_does_not_read_source(server):
    code, _, _ = request(server, "/assets/%2e%2e/store.py", token=False)
    assert code in {400, 404}


def test_rejects_non_json_and_oversized_request(server):
    code, _, _ = request(server, "/api/import", method="POST", headers={"Content-Length": str(32 * 1024 * 1024)})
    assert code == 413
    code, _, _ = request(server, "/api/import", method="POST")
    assert code in {400, 415}


def test_public_binding_is_rejected_before_creating_state(tmp_path):
    from tfmutate.gui.server import create_server
    with pytest.raises(ValueError, match="loopback"):
        create_server(host="0.0.0.0", port=0, data_dir=tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def test_launcher_explains_missing_compiled_frontend(tmp_path):
    from tfmutate.gui import serve
    from unittest.mock import patch
    with patch("tfmutate.gui.server.STATIC_DIR", Path(tmp_path / "absent")):
        with pytest.raises(RuntimeError, match="frontend"):
            serve(data_dir=tmp_path / "state", open_browser=False)


def test_dataset_filters_and_csv_export_share_one_scoring_contract(server):
    import csv as csv_module
    import io
    text = ("repo_name,mutant_id,operator_id,operator_category,test_status,validate_status,survival_reason\n"
            "alpha,m1,MUT-RES-002,resource,survived,valid,unknown\n"
            "beta,m2,MUT-SEC-001,security,killed_assert,valid,n/a\n")
    _, _, body = request(server, "/api/import", method="POST", body={"name": "Filter test", "csv": text})
    identifier = json.loads(body)["id"]
    code, _, body = request(server, f"/api/datasets/{identifier}?repo=alpha&status=survived")
    result = json.loads(body)
    assert code == 200
    assert result["selection"] == {"total_rows": 2, "filtered_rows": 1}
    assert result["filter_options"]["repo"] == ["alpha", "beta"]
    assert result["summary"]["overall"]["generated_mutants"] == 1
    assert result["summary"]["overall"]["mutation_score"] == 0.0
    assert [row["repo_name"] for row in result["rows"]] == ["alpha"]
    _, _, body = request(server, f"/api/datasets/{identifier}/csv?repo=alpha")
    assert [row["repo_name"] for row in csv_module.DictReader(io.StringIO(body.decode()))] == ["alpha"]
    _, _, body = request(server, f"/api/datasets/{identifier}?q=does-not-match")
    empty = json.loads(body)
    assert empty["rows"] == []
    assert empty["summary"]["overall"]["mutation_score"] is None
    assert empty["selection"]["total_rows"] == 2


@pytest.mark.parametrize("query", ["repo=alpha&repo=beta", "unknown=1"])
def test_ambiguous_or_unsupported_dataset_filters_are_actionable_errors(server, query):
    csv = "repo_name,mutant_id,operator_id,operator_category,test_status,validate_status\na,m1,MUT-RES-002,resource,killed_assert,valid\n"
    _, _, body = request(server, "/api/import", method="POST", body={"csv": csv})
    identifier = json.loads(body)["id"]
    code, _, body = request(server, f"/api/datasets/{identifier}?{query}")
    assert code == 400
    assert json.loads(body)["error"]
