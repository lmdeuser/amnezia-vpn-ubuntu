import getpass
import re
import socket
import unittest
from pathlib import Path

from tools.install_cron import BEGIN, END, job, merge, remove_block

ROOT = Path(__file__).resolve().parents[1]
NON_VENDOR_FILES = [
    ROOT / ".dockerignore",
    ROOT / ".gitignore",
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    *sorted((ROOT / "docs").rglob("*")),
    *sorted((ROOT / "debian").rglob("*")),
    *sorted((ROOT / "obs").rglob("*")),
    *sorted((ROOT / "packaging").rglob("*")),
    *sorted((ROOT / "tools").rglob("*")),
    *sorted((ROOT / "tests").rglob("*")),
]


class RunnerTests(unittest.TestCase):
    def test_cron_merge_and_remove_preserve_unrelated_jobs(self):
        previous = (
            "5 3 * * * /home/user/backup\n"
            "# BEGIN AMNEZIA SPLIT\n"
            "15 22 * * * /home/user/split/update.sh\n"
            "# END AMNEZIA SPLIT\n"
        )
        updated = merge(previous)
        self.assertTrue(updated.startswith(previous))
        self.assertIn(str(ROOT / "tools/cron-cycle.sh"), job())
        self.assertEqual(merge(updated), updated)
        self.assertEqual(remove_block(updated), previous)
        self.assertEqual(remove_block(previous), previous)

    def test_cron_rejects_malformed_markers(self):
        with self.assertRaises(ValueError):
            merge(f"{END}\n{BEGIN}\n")
        with self.assertRaises(ValueError):
            remove_block(f"{BEGIN}\n{BEGIN}\n{END}\n")
        with self.assertRaises(ValueError):
            merge(f"{BEGIN}\n")

    def test_run_controller_runs_host_python_directly_without_controller_container(self):
        controller = (ROOT / "tools/run-controller.sh").read_text()
        self.assertNotIn("docker run", controller)
        self.assertIn("XDG_CONFIG_HOME", controller)
        self.assertIn("CLIENT_CONFIG_FILE", controller)
        self.assertIn("exec python3 tools/obs_controller.py", controller)

    def test_public_files_avoid_private_details_and_stale_controller_dockerfile(self):
        self.assertFalse((ROOT / "packaging/controller.Dockerfile").exists())

        rfc1918 = re.compile(
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
        )
        home_path = re.compile(r"/home/([A-Za-z0-9._-]+)")
        allowed_homes = {"user", "tester"}
        generic_tokens = {"root", "user", "ubuntu", "tester", "runner", "localhost"}
        runtime_tokens = {
            token
            for token in (getpass.getuser(), socket.gethostname().split(".", 1)[0])
            if len(token) >= 4 and token not in generic_tokens
        }

        for path in NON_VENDOR_FILES:
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text()

            self.assertIsNone(rfc1918.search(text), f"{rel} contains a private IPv4 address")
            for match in home_path.finditer(text):
                self.assertIn(match.group(1), allowed_homes, f"{rel} leaks local home path")
            for forbidden in ("amnezia-vpn-" + "obs", "antigravity-obs-" + "controller"):
                self.assertNotIn(forbidden, text, f"{rel} leaked {forbidden}")
            for token in runtime_tokens:
                self.assertNotRegex(
                    text,
                    rf"\b{re.escape(token)}\b",
                    f"{rel} leaked runtime identifier",
                )

        self.assertIn("GitHub", (ROOT / "AGENTS.md").read_text())


if __name__ == "__main__":
    unittest.main()
