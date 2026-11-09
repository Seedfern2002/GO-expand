"""Download a source with a task-wide streaming byte budget and source ledger."""

import argparse
import fcntl
import json
from pathlib import Path
import urllib.request

from engine.knowledge import read_json, sha256, write_json


def fetch(url, output, root=Path.cwd()):
    root = Path(root).resolve()
    output = (root / output).resolve()
    if not output.is_relative_to(root) or output.exists():
        raise ValueError("Use a new output file inside the task workspace")
    output.parent.mkdir(parents=True, exist_ok=True)
    ledger = root / "download_ledger.json"
    limit = read_json(root / "task.json")["retrieval_budget"]["max_download_bytes"]
    with (root / "download.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(ledger) if ledger.exists() else {"downloaded_bytes": 0, "sources": []}
        received = 0
        partial = output.with_suffix(output.suffix + ".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "TaskGO/1.0 research knowledge acquisition"})
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as stream:
                resolved = response.url
                while True:
                    block = response.read(65536)
                    if not block:
                        break
                    received += len(block)
                    if state["downloaded_bytes"] + received > limit:
                        raise ValueError("Task download budget exceeded")
                    stream.write(block)
            partial.replace(output)
            item = {"url": url, "resolved_url": resolved, "path": str(output.relative_to(root)),
                    "bytes": received, "sha256": sha256(output), "status": "complete"}
        except Exception as error:
            item = {"url": url, "bytes": received, "status": "failed", "error": str(error)}
            raise
        finally:
            state["downloaded_bytes"] += received
            state["sources"].append(item)
            write_json(ledger, state)
        return item


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(fetch(args.url, args.output), indent=2))
