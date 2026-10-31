"""La entrada sin interfaz comparte los resultados y rechaza parámetros inválidos."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from data_crime_scene.experiments import run_experiment


ROOT = Path(__file__).resolve().parents[1]


def test_cli_exports_all_cases_from_the_same_engine(tmp_path):
    destination = tmp_path / "nested" / "report.json"
    process = subprocess.run(
        [sys.executable, "-m", "data_crime_scene", "--seeds", "7", "--output", str(destination)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert [item["case_id"] for item in payload["experiments"]] == ["future", "groups", "selection"]
    for report in payload["experiments"]:
        assert report == run_experiment(report["case_id"], 7).to_dict()
        assert report["case_id"] in process.stdout


@pytest.mark.parametrize("arguments", [["--seeds", "-1"], ["--cases", "unknown"]])
def test_cli_invalid_parameters_have_a_clear_error(arguments):
    process = subprocess.run(
        [sys.executable, "-m", "data_crime_scene", *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 2
    assert "error:" in process.stderr
    assert "Traceback" not in process.stderr
