#!/usr/bin/env python3
import argparse
import os
import subprocess
from pathlib import Path

BEGIN = "# BEGIN AMNEZIA OBS"
END = "# END AMNEZIA OBS"


def job():
    root = Path(__file__).resolve().parents[1]
    return f"37 * * * * /usr/bin/timeout 100m {root}/tools/cron-cycle.sh"


def remove_block(previous):
    lines = previous.splitlines()
    begins = [idx for idx, line in enumerate(lines) if line == BEGIN]
    ends = [idx for idx, line in enumerate(lines) if line == END]
    if len(begins) != len(ends) or len(begins) > 1 or (begins and begins[0] > ends[0]):
        raise ValueError("Ambiguous managed cron block")
    if begins:
        del lines[begins[0] : ends[0] + 1]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def merge(previous):
    cleaned = remove_block(previous)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned + BEGIN + "\n" + job() + "\n" + END + "\n"


def main():
    parser = argparse.ArgumentParser(description="Install or remove the AmneziaVPN OBS controller cron job")
    parser.add_argument("--remove", action="store_true", help="Remove only the managed AmneziaVPN cron block")
    args = parser.parse_args()

    env = {**os.environ, "LC_ALL": "C"}
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False, env=env)
    no_crontab = bool(result.returncode and "no crontab for" in result.stderr.lower())
    if result.returncode and not no_crontab:
        raise SystemExit("Cannot read the existing crontab; unchanged")

    existing = "" if no_crontab else result.stdout
    if args.remove:
        updated = remove_block(existing)
        if not updated:
            if not no_crontab:
                subprocess.run(["crontab", "-r"], check=True, env=env)
        else:
            subprocess.run(["crontab", "-"], input=updated, text=True, check=True, env=env)
        print("Removed AmneziaVPN controller cron block; unrelated jobs preserved.")
        return

    subprocess.run(["crontab", "-"], input=merge(existing), text=True, check=True, env=env)
    print("Hourly AmneziaVPN controller cron installed; unrelated jobs preserved.")


if __name__ == "__main__":
    main()
