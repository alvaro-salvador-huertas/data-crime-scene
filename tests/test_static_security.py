"""The static-analysis exception must fail closed when evidence changes."""

from copy import deepcopy
import shutil

import pytest

from scripts import check_static_security as security


def report():
    return {"errors": [], "metrics": {"_totals": {"loc": 1}}, "results": [{
        "filename": security.REVIEWED_FILE, "test_id": "B311", "line_number": 154,
        "code": security.REVIEWED_CODE,
    }]}


def test_exact_reviewed_shuffle_is_allowed():
    assert security.unreviewed_findings(report()) == []


@pytest.mark.parametrize("field,value", [
    ("filename", "ui/public_limits.py"), ("test_id", "B602"),
    ("line_number", 155), ("code", "random.Random().getrandbits(128)"),
])
def test_changed_finding_is_not_allowed(field, value):
    changed = report()
    changed["results"][0][field] = value
    assert security.unreviewed_findings(changed) == changed["results"]


def test_changed_source_requires_review(tmp_path):
    path = tmp_path / security.REVIEWED_FILE
    path.parent.mkdir(parents=True)
    shutil.copy2(security.ROOT / security.REVIEWED_FILE, path)
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    assert security.unreviewed_findings(report(), tmp_path) == report()["results"]


def test_duplicate_issue_is_not_suppressed():
    changed = report()
    changed["results"] *= 2
    assert len(security.unreviewed_findings(changed)) == 1


@pytest.mark.parametrize("replacement", [None, {}, {"errors": ["parse failed"]},
    {"errors": [], "metrics": {}, "results": []},
    {"errors": [], "metrics": {"_totals": {"loc": 1}}, "results": None}])
def test_incomplete_or_failed_scans_rejected(replacement):
    with pytest.raises(ValueError):
        security.unreviewed_findings(deepcopy(replacement))
