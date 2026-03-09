from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

START_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) INFO\s+=== CAN Bus Viewer started\s+Python (?P<pyver>[^ ]+)\s+pid=(?P<pid>\d+) ===$"
)
DISCONNECT_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) INFO\s+Disconnect: messages=(?P<messages>\d+) errors=(?P<errors>\d+) dropped=(?P<dropped>\d+)$"
)
DECODE_ERR_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) DEBUG\s+Decode error\s+arb=(?P<arb>0x[0-9A-Fa-f]+)\s+dlc=(?P<dlc>\d+)\s+data=(?P<data>[0-9A-Fa-f]+)\s+err=(?P<err>.+)$"
)


@dataclass
class SessionStart:
    timestamp: str
    pid: int
    python_version: str


@dataclass
class DisconnectSummary:
    timestamp: str
    messages: int
    errors: int
    dropped: int


@dataclass
class DecodeError:
    timestamp: str
    arbitration_id_hex: str
    dlc: int
    data_hex: str
    error: str


def parse_log(path: Path) -> dict:
    starts: list[SessionStart] = []
    disconnects: list[DisconnectSummary] = []
    decode_errors: list[DecodeError] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue

            m = START_RE.match(line)
            if m:
                starts.append(
                    SessionStart(
                        timestamp=m.group("ts"),
                        pid=int(m.group("pid")),
                        python_version=m.group("pyver"),
                    )
                )
                continue

            m = DISCONNECT_RE.match(line)
            if m:
                disconnects.append(
                    DisconnectSummary(
                        timestamp=m.group("ts"),
                        messages=int(m.group("messages")),
                        errors=int(m.group("errors")),
                        dropped=int(m.group("dropped")),
                    )
                )
                continue

            m = DECODE_ERR_RE.match(line)
            if m:
                decode_errors.append(
                    DecodeError(
                        timestamp=m.group("ts"),
                        arbitration_id_hex=m.group("arb").lower(),
                        dlc=int(m.group("dlc")),
                        data_hex=m.group("data").lower(),
                        error=m.group("err"),
                    )
                )

    return {
        "source_file": str(path.name),
        "summary": {
            "start_count": len(starts),
            "disconnect_count": len(disconnects),
            "decode_error_count": len(decode_errors),
        },
        "starts": [asdict(item) for item in starts],
        "disconnects": [asdict(item) for item in disconnects],
        "decode_errors": [asdict(item) for item in decode_errors],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build parity fixtures from can_viewer_diag.log")
    parser.add_argument("input_log", type=Path, help="Path to can_viewer_diag.log")
    parser.add_argument("output_json", type=Path, help="Path to output fixture JSON")
    args = parser.parse_args()

    data = parse_log(args.input_log)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote fixture: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
