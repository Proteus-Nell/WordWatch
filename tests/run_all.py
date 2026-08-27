#!/usr/bin/env python3
"""Runs every WordWatch test file and exits non-zero if any of them fail.

    python3 tests/run_all.py

Requires only discord.py (already in requirements.txt); no test framework.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_fixes.py", "test_behaviour.py"]

failed = []
for name in SUITES:
    print("=" * 60)
    print("running {}".format(name))
    print("=" * 60)
    result = subprocess.run([sys.executable, os.path.join(HERE, name)])
    if result.returncode != 0:
        failed.append(name)
    print()

if failed:
    print("FAILED: {}".format(", ".join(failed)))
    sys.exit(1)
print("all suites passed")
