#!/usr/bin/env python3
import re
import sys


def candidates(tree):
    found = []
    for line in tree.splitlines():
        match = re.search(r'^\s*(0x[0-9a-fA-F]+)\s+"([^"]*)".*?\s(\d+)x(\d+)[+-]', line)
        if match and re.search(r"amnezia|welcome|get started", match[2], re.I) and int(match[3]) >= 320 and int(match[4]) >= 200:
            found.append(match[1])
    return found


if __name__ == "__main__":
    print("\n".join(candidates(sys.stdin.read())))
