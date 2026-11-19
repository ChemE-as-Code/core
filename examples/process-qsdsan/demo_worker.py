"""Replay teaching data to demonstrate the interface without a solver installation."""

import json
import sys
from pathlib import Path


def main():
    request = json.loads(Path(sys.argv[1]).read_bytes())
    values = json.loads(Path(request["input"]).read_bytes())
    result = {
        "schema": "cheme/adapter-result/v1",
        "case": request["case"],
        "solver": {"name": "QSDsan", "version": "fixture", "method": "recorded data"},
        "status": "converged",
        "units": [{"id": "TANK", "status": "simulated"}],
        "streams": [{"id": name, "values": cells} for name, cells in values.items()],
        "messages": ["Protocol example with recorded quantities."],
    }
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
