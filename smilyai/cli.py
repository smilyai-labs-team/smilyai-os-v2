from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from .server import main as server_main


def main() -> None:
    parser = argparse.ArgumentParser(prog="smilyai")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="start the local shell and harness")
    ask = sub.add_parser("ask", help="send an intent to a running harness")
    ask.add_argument("text", nargs="+")
    args = parser.parse_args()
    if args.command in {None, "serve"}:
        server_main()
        return
    payload = json.dumps({"text": " ".join(args.text)}).encode()
    with urllib.request.urlopen("http://127.0.0.1:47811/api/bootstrap", timeout=5) as response:
        token = json.load(response)["session_token"]
    request = urllib.request.Request("http://127.0.0.1:47811/api/intent", data=payload, headers={"Content-Type": "application/json", "X-SmilyAI-Session": token})
    with urllib.request.urlopen(request, timeout=60) as response:
        print(json.dumps(json.load(response), indent=2))


if __name__ == "__main__":
    main()
