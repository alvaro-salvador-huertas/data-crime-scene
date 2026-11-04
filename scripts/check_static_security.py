"""Run Bandit, retaining all rules and one exact reviewed non-crypto finding."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REVIEWED_FILE = "data_crime_scene/detective.py"
REVIEWED_SHA256 = "c2cfe7d2f4e2f1a2c7fb13fbc9e82a1e999bd3acf8c40719101d47e0352cf8fa"
REVIEWED_CODE = "153     order = list(TEMPLATES)\n154     random.Random(seed).shuffle(order)\n155     fingerprint = detective_fingerprint()\n"


def unreviewed_findings(report, root=ROOT):
    if not isinstance(report, dict) or report.get("errors") != []:
        raise ValueError("Bandit did not complete without scanner errors")
    findings = report.get("results")
    if not isinstance(findings, list) or not report.get("metrics", {}).get("_totals", {}).get("loc", 0):
        raise ValueError("Bandit report is missing results or scanned source")
    remaining, reviewed = [], False
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Malformed Bandit finding")
        # The educational shuffle is not used for credentials, tokens or access
        # control. Any source change or second/new B311 requires another review.
        accepted = (
            not reviewed
            and finding.get("filename") == REVIEWED_FILE
            and finding.get("test_id") == "B311"
            and finding.get("line_number") == 154
            and finding.get("code") == REVIEWED_CODE
            and hashlib.sha256((root / REVIEWED_FILE).read_bytes()).hexdigest() == REVIEWED_SHA256
        )
        if accepted:
            reviewed = True
        else:
            remaining.append(finding)
    return remaining


def main():
    result = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", "app.py", "demo", "ui", "data_crime_scene", "-f", "json"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode not in (0, 1):
        print("Bandit execution failed; no clean result.", file=sys.stderr)
        return 2
    try:
        remaining = unreviewed_findings(json.loads(result.stdout))
    except (ValueError, OSError) as error:
        print(f"Security check failed: {error}", file=sys.stderr)
        return 2
    # Report locations and rules, not source snippets that could contain secrets.
    for finding in remaining:
        print(f"{finding.get('filename')}:{finding.get('line_number')} {finding.get('test_id')} {finding.get('issue_severity')}")
    print(f"Bandit: {len(remaining)} unreviewed findings. Exact educational shuffle exception documented in docs/seguridad-demo.md.")
    return 1 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
