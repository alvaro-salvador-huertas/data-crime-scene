"""Public entrypoint; reuse the local application without duplicating its modes."""
from pathlib import Path
import sys

# Community Cloud starts at the repository root; AppTest may use another cwd.
project = str(Path(__file__).resolve().parents[1])
if project not in sys.path:
    sys.path.insert(0, project)

from app import main

main(public_demo=True)
