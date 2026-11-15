import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import obs_controller as oc


def _populate_binary(state: Path, package_version: str, srcmd5: str, mtime_ns: int | None = None):
    bnd = state / "binaries" / srcmd5
    bnd.mkdir(parents=True, exist_ok=True)
    deb = bnd / f"{oc.BINARY_PACKAGE}_{package_version}_amd64.deb"
    deb.write_bytes(b"deb")
    if mtime_ns is not None:
        os.utime(deb, ns=(mtime_ns, mtime_ns))
    return deb


class ObsRetentionTests(unittest.TestCase):
    def test_prune_keeps_at_most_two_versions_and_clears_recheck(self):
        with TemporaryDirectory() as d, patch.object(oc, "STATE", Path(d)):
            state = Path(d)
            versions = [
                ("4.8.10.0+git20261101.aaaaaaaaaaaa-0ubuntu1~obs1", "src-1"),
                ("4.8.11.0+git20261110.bbbbbbbbbbbb-0ubuntu1~obs1", "src-2"),
                ("4.8.11.0+git20261111.cccccccccccc-0ubuntu1~obs1", "src-3"),
                ("4.8.11.0+git20261112.dddddddddddd-0ubuntu1~obs1", "src-4"),
            ]
            for pkg_ver, srcmd5 in versions:
                _populate_binary(state, pkg_ver, srcmd5)

            recheck = state / "recheck"
            recheck.mkdir(parents=True, exist_ok=True)
            (recheck / f"{oc.BINARY_PACKAGE}_{versions[1][0]}_amd64.deb").write_bytes(b"old")

            (state / "stable.json").write_text(json.dumps({
                "package_version": versions[3][0],
                "srcmd5": "src-4",
            }))

            oc.prune_state()

            self.assertEqual(
                sorted(x.name for x in (state / "binaries").iterdir()),
                ["src-3", "src-4"],
            )
            self.assertEqual(list(recheck.iterdir()), [])

    def test_prune_removes_part_files_and_breaks_same_day_ties_by_mtime(self):
        with TemporaryDirectory() as d, patch.object(oc, "STATE", Path(d)):
            state = Path(d)
            _populate_binary(
                state,
                "5.1.1.4+git20261114.aaaaaaaaaaaa-0ubuntu1~obs1",
                "src-older",
                mtime_ns=1_000_000_000,
            )
            (state / "binaries" / "src-older" / "partial.deb.part").write_bytes(b"part")
            _populate_binary(
                state,
                "5.1.1.4+git20261114.bbbbbbbbbbbb-0ubuntu1~obs1",
                "src-newer",
                mtime_ns=2_000_000_000,
            )
            _populate_binary(
                state,
                "5.1.1.4+git20261114.bbbbbbbbbbbb-0ubuntu1~obs2",
                "src-obs2",
                mtime_ns=1_500_000_000,
            )
            (state / "binaries" / "src-obs2" / "partial.deb.part").write_bytes(b"part")
            (state / "binaries" / "src-only-part").mkdir(parents=True, exist_ok=True)
            (state / "binaries" / "src-only-part" / "orphan.deb.part").write_bytes(b"part")

            (state / "stable.json").write_text(json.dumps({"srcmd5": "src-obs2"}))

            oc.prune_state(keep=2)

            self.assertEqual(
                sorted(x.name for x in (state / "binaries").iterdir()),
                ["src-newer", "src-obs2"],
            )
            self.assertEqual(
                [p.name for p in (state / "binaries" / "src-obs2").iterdir()],
                [f"{oc.BINARY_PACKAGE}_5.1.1.4+git20261114.bbbbbbbbbbbb-0ubuntu1~obs2_amd64.deb"],
            )


if __name__ == "__main__":
    unittest.main()
