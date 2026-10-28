"""python -m scripts.navigation status|watch|pause|... (no startup motion)."""
import argparse
import json
import time
from robot_tools.navigation import navigation_control
from edge.navigation.bridge import status
from edge.navigation.state import TOOL_COMMANDS as COMMANDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*COMMANDS, "watch"], default="status", nargs="?")
    args = parser.parse_args()
    try:
        if args.command == "watch":
            while True:
                print(json.dumps(status(), ensure_ascii=False), flush=True)
                time.sleep(1)
        else:
            result = navigation_control({"command": args.command})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
