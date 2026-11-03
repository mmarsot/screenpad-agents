"""Tests for install.sh: run as the user against a temporary HOME and XDG
directories, with stub id and systemctl first on PATH (so the real user
manager is never asked anything), and the client library from a local wheel
built from vendor/ (so nothing is fetched). Skipped when run as root.

Run with: python3 -m unittest discover -s tests
"""

import base64
import configparser
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import zipfile

from agents_support import REPO, VENDOR

STUBS = ("id", "systemctl")


def build_wheel(directory):
    """A wheel of the vendored screenpad_app, for pip to install offline."""
    info = os.path.basename(glob.glob(os.path.join(VENDOR, "screenpad_app-*.dist-info"))[0])
    version = info[len("screenpad_app-") : -len(".dist-info")]
    path = os.path.join(directory, "screenpad_app-%s-py3-none-any.whl" % version)
    files = {}
    for name in sorted(os.listdir(os.path.join(VENDOR, "screenpad_app"))):
        if name.endswith(".py"):
            with open(os.path.join(VENDOR, "screenpad_app", name), "rb") as f:
                files["screenpad_app/" + name] = f.read()
    files[info + "/METADATA"] = b"Metadata-Version: 2.1\nName: screenpad-app\nVersion: %s\n" % version.encode()
    files[info + "/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    record = []
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append("%s,sha256=%s,%d" % (name, digest, len(data)))
    record.append(info + "/RECORD,,")
    files[info + "/RECORD"] = ("\n".join(record) + "\n").encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def read(path):
    with open(path) as f:
        return f.read()


@unittest.skipIf(os.geteuid() == 0, "runs install.sh, so never as root")
class InstallTests(unittest.TestCase):
    wheels: tempfile.TemporaryDirectory
    wheel: str

    @classmethod
    def setUpClass(cls):
        cls.wheels = tempfile.TemporaryDirectory(dir="/tmp")
        cls.wheel = build_wheel(cls.wheels.name)

    @classmethod
    def tearDownClass(cls):
        cls.wheels.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(self.tmp, "data")
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.home)
        self.bin = os.path.join(self.tmp, "stub-bin")
        self.calls = os.path.join(self.tmp, "calls")
        self.uid = os.path.join(self.tmp, "uid")
        with open(self.uid, "w") as f:
            f.write("1000\n")
        os.makedirs(self.bin)
        for name in STUBS:
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write('#!/bin/sh\necho "%s $*" >> "$STUB_CALLS"\n' % name)
                if name == "id":
                    f.write('cat "$STUB_UID"\n')
            os.chmod(path, 0o755)
        self.path = self.bin + os.pathsep + os.environ.get("PATH", "")
        for name in STUBS:
            # Fail closed: the real commands must never run.
            self.assertEqual(shutil.which(name, path=self.path), os.path.join(self.bin, name))
        self.lib = os.path.join(self.home, ".local", "lib", "screenpad-agents")
        self.command = os.path.join(self.home, ".local", "bin", "screenpad-agents")
        self.unit = os.path.join(self.data, "systemd", "user", "screenpad-agents.service")
        self.agents_toml = os.path.join(self.config, "screenpad", "agents.toml")

    def install(self, *argv, library=None):
        env = dict(
            os.environ,
            HOME=self.home,
            XDG_DATA_HOME=self.data,
            XDG_CONFIG_HOME=self.config,
            PATH=self.path,
            STUB_CALLS=self.calls,
            STUB_UID=self.uid,
            SCREENPAD_APP=library or self.wheel,
        )
        return subprocess.run(
            ["sh", os.path.join(REPO, "install.sh"), *argv], env=env, capture_output=True, text=True, timeout=120
        )

    def called(self):
        try:
            return [line.split() for line in read(self.calls).splitlines()]
        except FileNotFoundError:
            return []

    def systemctl(self):
        return [c[1:] for c in self.called() if c[0] == "systemctl"]

    def run_installed(self, *args):
        env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=self.config, XDG_RUNTIME_DIR=self.tmp)
        return subprocess.run([self.command, *args], cwd=self.tmp, capture_output=True, text=True, env=env, timeout=30)

    def test_install_puts_the_program_and_its_library_under_home(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(self.command), "../lib/screenpad-agents/agents.py")
        self.assertEqual(read(os.path.join(self.lib, "agents.py")), read(os.path.join(REPO, "agents.py")))
        installed = sorted(os.listdir(os.path.join(self.lib, "screenpad_agents")))
        modules = sorted(n for n in os.listdir(os.path.join(REPO, "screenpad_agents")) if n.endswith(".py"))
        self.assertEqual(installed, modules)
        self.assertTrue(os.path.isfile(os.path.join(self.lib, "vendor", "screenpad_app", "client.py")))
        self.assertFalse(os.path.exists(self.lib + ".new"))
        self.assertIn("not enabled", r.stdout)
        self.assertIn("It runs only once you write %s" % self.agents_toml, r.stdout)

    def test_the_unit_is_installed_off(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        unit = read(self.unit)
        self.assertEqual(unit, read(os.path.join(REPO, "systemd", "screenpad-agents.service")))
        parsed = configparser.ConfigParser(interpolation=None, strict=False)
        parsed.optionxform = str  # type: ignore[assignment,method-assign]  # systemd keys are case-sensitive
        parsed.read_string(unit)
        self.assertEqual(parsed["Unit"]["ConditionPathExists"], "%E/screenpad/agents.toml")
        # %h is the home directory: the command install.sh links.
        self.assertEqual(parsed["Service"]["ExecStart"], "%h/.local/bin/screenpad-agents run")
        self.assertEqual(os.path.relpath(self.command, self.home), ".local/bin/screenpad-agents")
        self.assertEqual(parsed["Service"]["Restart"], "on-failure")
        self.assertEqual(parsed["Service"]["RestartPreventExitStatus"], "2")
        self.assertEqual(parsed["Install"]["WantedBy"], "graphical-session.target")
        # Only the user manager's reload: nothing enables or starts it.
        self.assertEqual(self.systemctl(), [["--user", "daemon-reload"]])

    def test_the_installed_command_runs_isolated_and_refuses_without_its_config(self):
        self.assertEqual(self.install().returncode, 0)
        done = self.run_installed("run")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("agents.toml does not exist", done.stderr)
        # It found its package and the library in its own directory.
        self.assertNotIn("screenpad_app is not in", done.stderr)
        shutil.rmtree(os.path.join(self.lib, "vendor"))
        done = self.run_installed("run")
        self.assertEqual(done.returncode, 1)
        self.assertIn("the client library screenpad_app is not in %s" % os.path.join(self.lib, "vendor"), done.stderr)

    def test_an_update_replaces_the_copy_whole(self):
        self.assertEqual(self.install().returncode, 0)
        for stale in ("screenpad_agents/gone.py", "vendor/stale.py"):
            with open(os.path.join(self.lib, stale), "w") as f:
                f.write("# from an earlier version\n")
        os.makedirs(os.path.dirname(self.agents_toml))
        with open(self.agents_toml, "w") as f:
            f.write('[herdr]\nsession = "lab"\n')
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        for stale in ("screenpad_agents/gone.py", "vendor/stale.py"):
            self.assertFalse(os.path.exists(os.path.join(self.lib, stale)), stale)
        self.assertIn("systemctl --user restart screenpad-agents", r.stdout)
        self.assertEqual(read(self.agents_toml), '[herdr]\nsession = "lab"\n')

    def test_a_failed_library_install_keeps_the_previous_copy(self):
        self.assertEqual(self.install().returncode, 0)
        before = sorted(os.listdir(self.lib))
        r = self.install(library=os.path.join(self.tmp, "missing.whl"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not install the client library screenpad_app", r.stderr)
        self.assertEqual(sorted(os.listdir(self.lib)), before)
        self.assertFalse(os.path.exists(self.lib + ".new"))

    def test_refuses_root(self):
        with open(self.uid, "w") as f:
            f.write("0\n")
        for argv in ((), ("uninstall",)):
            r = self.install(*argv)
            self.assertEqual(r.returncode, 1)
            self.assertIn("run as your user, not root", r.stderr)
        self.assertEqual(os.listdir(self.home), [])
        self.assertEqual(self.systemctl(), [])

    def test_uninstall_removes_it_and_keeps_the_config(self):
        self.assertEqual(self.install().returncode, 0)
        os.makedirs(os.path.dirname(self.agents_toml))
        with open(self.agents_toml, "w") as f:
            f.write('[herdr]\nsession = "lab"\n')
        r = self.install("uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        for path in (self.command, self.unit, self.lib):
            self.assertFalse(os.path.lexists(path), path)
        self.assertTrue(os.path.exists(self.agents_toml))
        self.assertIn("Your config %s is kept" % self.agents_toml, r.stdout)
        self.assertEqual(
            self.systemctl()[1:],
            [["--user", "disable", "--now", "screenpad-agents.service"], ["--user", "daemon-reload"]],
        )

    def test_uninstall_with_nothing_installed(self):
        os.makedirs(os.path.dirname(self.command))
        with open(self.command, "w") as f:
            f.write("a file of your own\n")
        r = self.install("uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.systemctl(), [["--user", "daemon-reload"]])
        # Only the link install.sh makes is removed.
        self.assertTrue(os.path.exists(self.command))

    def test_usage(self):
        r = self.install("purge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage:", r.stderr)


class LibraryTests(unittest.TestCase):
    def test_the_library_is_pinned_to_a_commit_and_vendored_from_it(self):
        with open(os.path.join(REPO, "pyproject.toml"), "rb") as f:
            deps = tomllib.load(f)["project"]["dependencies"]
        self.assertEqual(len(deps), 1)
        m = re.fullmatch(r"screenpad-app @ git\+(https://github\.com/mmarsot/screenpad-linux)@([0-9a-f]{40})", deps[0])
        assert m is not None, deps[0]
        # vendor/ holds that commit ('make vendor' fetches it again when
        # pyproject.toml changes).
        info = glob.glob(os.path.join(VENDOR, "screenpad_app-*.dist-info"))[0]
        with open(os.path.join(info, "direct_url.json")) as f:
            source = json.load(f)
        self.assertEqual(source["url"], m.group(1))
        self.assertEqual(source["vcs_info"]["commit_id"], m.group(2))


if __name__ == "__main__":
    unittest.main()
