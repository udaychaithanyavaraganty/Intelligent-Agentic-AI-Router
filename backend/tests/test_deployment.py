from pathlib import Path

from backend.app import create_app


def test_production_app_initializes_both_databases_without_debug(tmp_path):
    operational_db = tmp_path / "missing" / "operational" / "router.sqlite3"
    evaluation_db = tmp_path / "another-missing" / "evaluation" / "results.sqlite3"

    app = create_app({
        "DATABASE": str(operational_db),
        "EVALUATION_DATABASE": str(evaluation_db),
        "LLM_PROVIDER": "demo",
    })

    assert app.debug is False
    assert Path(app.config["DATABASE"]).is_file()
    assert Path(app.config["EVALUATION_DATABASE"]).is_file()

    client = app.test_client()
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["status"] == "ok"
    assert health.json["storage"] == "ok"
    assert client.get("/").status_code == 200
