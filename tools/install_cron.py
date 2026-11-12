#!/usr/bin/env python3
from pathlib import Path
import subprocess

BEGIN = "# BEGIN AMNEZIA OBS"
END = "# END AMNEZIA OBS"


def job():
    root = Path(__file__).resolve().parents[1]
    return f"37 * * * * /usr/bin/timeout 100m {root}/tools/cron-cycle.sh"


def merge(previous):
    if previous.count(BEGIN) != previous.count(END) or previous.count(BEGIN) > 1:
        raise ValueError("Ambiguous managed cron block")
    if BEGIN in previous:
        start = previous.index(BEGIN)
        stop = previous.index(END) + len(END)
        previous = previous[:start] + previous[stop:].lstrip("\n")
    if previous and not previous.endswith("\n"):
        previous += "\n"
    return previous + BEGIN + "\n" + job() + "\n" + END + "\n"


def main():
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    if result.returncode and "no crontab for" not in result.stderr.lower():
        raise SystemExit("Cannot read the existing crontab; unchanged")
    subprocess.run(["crontab", "-"], input=merge(result.stdout), text=True, check=True)
    print("Hourly AmneziaVPN controller cron installed; unrelated jobs preserved.")


if __name__ == "__main__":
    main()
