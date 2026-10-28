"""CLI regression tests using real PHP/semver and stubbed external services.

Run with: python3 -m unittest discover -s tests -v
Requires bash, PHP, jq, and a Composer PHAR on PATH (or COMPOSER_AUTOLOAD).
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "bin/php-compat-check"
CHECKER = ROOT / "docker/bin/php-compat-check"

STUB = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps({"tool": name, "args": args, "cwd": os.getcwd()}) + "\n")
if name == "docker":
    pass
elif name == "composer":
    if args == ["config", "--global", "home"]:
        print(os.environ["TEST_COMPOSER_HOME"])
    elif args[0] == "install":
        packages = json.loads(os.environ.get("TEST_PACKAGES", "[]"))
        pathlib.Path("composer.lock").write_text(json.dumps({"packages": packages}))
        for package in packages:
            folder = pathlib.Path("vendor") / package["name"]
            folder.mkdir(parents=True, exist_ok=True)
    elif args[:2] != ["config", "platform.php"]:
        sys.exit(90)
elif name == "git":
    if args[0] == "clone":
        shutil.copytree(os.environ["TEST_REMOTE"], args[-1], dirs_exist_ok=True)
    elif "describe" in args:
        sys.exit(1)
    elif "--abbrev-ref" in args:
        print("main")
    else:
        print("abc1234")
elif name == "curl":
    print(json.dumps({"package": {"repository": "https://example.test/repository",
                                 "versions": {"v1.0.0": {}, "v1.2.0": {}, "dev-main": {}}}}))
elif name == "phpcs":
    target = args[args.index("testVersion") + 1]
    errors = int(tuple(map(int, target.split("."))) < (8, 1))
    print(json.dumps({"totals": {"errors": errors, "warnings": 0}, "files": {}}))
    sys.exit(errors)
'''


class VersionTest(unittest.TestCase):
    def check_version(self, script, version):
        for executable in (str(script), script.name):
            for args in (("--version",), (".", "8.1", "--version")):
                with self.subTest(script=script, executable=executable, args=args):
                    result = subprocess.run(
                        [shutil.which("bash"), executable, *args],
                        cwd=script.parent, env=dict(os.environ, PATH=""), text=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(result.stdout, f"php-compat-check {version}\n")

    def test_checkout_executables_read_the_shared_version_without_dependencies(self):
        for script in (WRAPPER, CHECKER):
            self.check_version(script, (ROOT / "VERSION").read_text().strip())

    def test_both_executables_follow_changes_to_the_shared_version(self):
        with tempfile.TemporaryDirectory(prefix="php-compat-check version ") as directory:
            checkout = Path(directory)
            (checkout / "VERSION").write_text("9.8.7-test\n")
            for script in (WRAPPER, CHECKER):
                copied = checkout / script.relative_to(ROOT)
                copied.parent.mkdir(parents=True)
                shutil.copyfile(script, copied)
                self.check_version(copied, "9.8.7-test")

    def test_installed_executables_read_the_packaged_version(self):
        with tempfile.TemporaryDirectory(prefix="php-compat-check install ") as directory:
            prefix = Path(directory)
            result = subprocess.run(
                ["make", "install", f"INSTALL_DIR={prefix / 'bin'}"],
                cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr)
            version = (ROOT / "VERSION").read_text().strip()
            self.assertEqual((prefix / "share/php-compat-check/VERSION").read_text().strip(),
                             version)
            installed = prefix / "bin/php-compat-check"
            self.check_version(installed, version)
            # Docker installs the checker with the same bin/share layout.
            shutil.copyfile(CHECKER, installed)
            self.check_version(installed, version)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="php-compat-check-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project with spaces"
        self.project.mkdir()
        self.write("composer.json", {"autoload": {"psr-4": {"App\\": "src/"}}})
        (self.project / "src").mkdir()
        (self.project / "src/uncommitted.php").write_text("<?php echo 'working tree';\n")
        self.log = self.base / "calls.jsonl"
        tools = self.base / "bin"
        tools.mkdir()
        stub = tools / "stub"
        stub.write_text(STUB)
        stub.chmod(0o755)
        for name in ("docker", "composer", "git", "curl", "phpcs"):
            (tools / name).symlink_to(stub)
        composer_home = self.base / "composer"
        (composer_home / "vendor").mkdir(parents=True)
        autoload = os.environ.get("COMPOSER_AUTOLOAD")
        if not autoload:
            composer = shutil.which("composer")
            if not composer:
                self.skipTest("Composer PHAR or COMPOSER_AUTOLOAD is required")
            shutil.copyfile(composer, self.base / "composer.phar")
            autoload = f"phar://{self.base}/composer.phar/vendor/autoload.php"
        (composer_home / "vendor/autoload.php").write_text(
            "<?php require " + json.dumps(autoload) + ";\n"
        )
        self.env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}",
                        TEST_LOG=str(self.log), TEST_COMPOSER_HOME=str(composer_home),
                        TEST_REMOTE=str(self.project))

    def write(self, name, data):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def run_cli(self, *args, wrapper=False):
        return subprocess.run(["bash", str(WRAPPER if wrapper else CHECKER), *args],
                              cwd=self.project, env=self.env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def calls(self, tool):
        if not self.log.exists():
            return []
        return [call for line in self.log.read_text().splitlines()
                if (call := json.loads(line))["tool"] == tool]

    def snapshot(self):
        return {str(p.relative_to(self.project)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.project.rglob("*") if p.is_file()}

    def install(self, packages, dev=()):
        self.write("vendor/composer/installed.json",
                   {"packages": packages, "dev-package-names": list(dev)})
        self.write("composer.lock", {"packages": [{"name": "stale/lock", "version": "1"}]})
        for package in packages:
            if package.get("type") != "metapackage":
                self.write(f"vendor/{package['name']}/composer.json", package)
                (self.project / f"vendor/{package['name']}/code.php").write_text("<?php\n")

    def test_wrapper_mounts_local_paths_read_only(self):
        for source in (".", "../project with spaces", str(self.project),
                       "local:.", f"local:{self.project}"):
            with self.subTest(source=source):
                result = self.run_cli("--show-warnings", source, "8.1", wrapper=True)
                self.assertEqual(result.returncode, 0, result.stdout)
                args = self.calls("docker")[-1]["args"]
                self.assertIn(f"{self.project}:/project:ro", args)
                self.assertEqual(args[-3:], ["--show-warnings", "local:/project", "8.1"])

    def test_unknown_options_fail_before_external_commands(self):
        for wrapper in (False, True):
            for option in ("--source-version", "--unknown", "--unknown=value", "-v"):
                for args in ((option,), ("--show-warnings", option, ".", "8.1"),
                             ("vendor/package", option),
                             ("https://example.test/repo", "8.1", option)):
                    with self.subTest(wrapper=wrapper, args=args):
                        result = self.run_cli(*args, wrapper=wrapper)
                        self.assertEqual(result.returncode, 1, result.stdout)
                        self.assertIn(f"Unknown option: {option}", result.stdout)
                        self.assertFalse(self.log.exists(), result.stdout)

    def test_wrapper_forwards_source_version_and_normalizes_deprecated_alias(self):
        for option in ("--source-version=dev-main", "--version=dev-main"):
            with self.subTest(option=option):
                result = self.run_cli("https://example.test/repo", "8.1", option, wrapper=True)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.calls("docker")[-1]["args"][-1],
                                 "--source-version=dev-main")
                self.assertEqual("deprecated" in result.stdout, option.startswith("--version="))

    def test_wrapper_preserves_remote_arguments_and_image_override(self):
        (self.project / "vendor/package").mkdir(parents=True)
        self.env["PHP_COMPAT_CHECK_IMAGE"] = "php-compat-check:dev"
        for source in ("vendor/package", "package:vendor/package:^1.0", "https://example.test/repo",
                       "repo:https://example.test/repo", "repository:git@example.test:repo"):
            with self.subTest(source=source):
                result = self.run_cli(source, "8.1", wrapper=True)
                self.assertEqual(result.returncode, 0, result.stdout)
                args = self.calls("docker")[-1]["args"]
                self.assertEqual(args[-4:], ["php-compat-check:dev", "php-compat-check", source, "8.1"])
                self.assertNotIn("local:/project", args)

    def test_missing_local_directory_fails_before_docker(self):
        for source in ("./missing", "local:", "local:src/uncommitted.php"):
            with self.subTest(source=source):
                result = self.run_cli(source, "8.1", wrapper=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Local directory not found", result.stdout)
        self.assertEqual(self.calls("docker"), [])

    def test_local_source_without_git_keeps_working_files_and_excludes_vendor(self):
        self.install([{"name": "vendor/library", "version": "1"}])
        before = self.snapshot()
        for source in (".", "./", str(self.project), "local:."):
            with self.subTest(source=source):
                result = self.run_cli(source, "8.1")
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("Compatible with PHP 8.1", result.stdout)
                scan = self.calls("phpcs")[-1]
                self.assertEqual(scan["cwd"], str(self.project))
                self.assertIn("src", scan["args"])
                self.assertIn("*/vendor/*", next(a for a in scan["args"] if a.startswith("--ignore=")))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls("git"), [])
        self.assertEqual(self.calls("curl"), [])
        self.assertTrue(all(c["args"] == ["config", "--global", "home"] for c in self.calls("composer")))

    def test_local_dependency_modes_use_installed_metadata_and_exclude_dev(self):
        self.install([{"name": "vendor/trusted", "version": "1", "require": {"php": "^8.0"}},
                      {"name": "vendor/unknown", "version": "2"},
                      {"name": "symfony/polyfill-php80", "version": "3"},
                      {"name": "vendor/dev", "version": "4", "require": {"php": ">=8.5"}}],
                     dev=["vendor/dev"])
        before = self.snapshot()
        for mode in ("--check-deps", "--check-deps=full"):
            with self.subTest(mode=mode):
                result = self.run_cli(".", "8.1", mode, "--show-deps")
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("Dependencies (3 packages)", result.stdout)
                self.assertNotIn("stale/lock", result.stdout)
                self.assertNotIn("vendor/dev", result.stdout)
                args = self.calls("phpcs")[-1]["args"]
                ignores = next(a for a in args if a.startswith("--ignore="))
                self.assertIn("*/vendor/vendor/dev/*", ignores)
                self.assertEqual("*/vendor/vendor/trusted/*" in ignores, mode == "--check-deps")
                self.assertIn("vendor", args)
                self.assertIn("--standard=PHPCompatibility,PHPCompatibilitySymfonyPolyfillPHP80", args)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(c["args"] == ["config", "--global", "home"] for c in self.calls("composer")))

    def test_local_minimum_respects_installed_dependency_requirements(self):
        self.install([{"name": "vendor/newer", "version": "1", "require": {"php": ">=8.2"}}])
        before = self.snapshot()
        result = self.run_cli(".", "--min-php-version", "--from-php-version=8.1", "--check-deps")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Installed dependency vendor/newer requires PHP >=8.2", result.stdout)
        self.assertIn("Minimum supported PHP version: 8.2", result.stdout)
        self.assertEqual(len(self.calls("phpcs")), 1)
        self.assertEqual(self.snapshot(), before)

    def test_missing_dependencies_and_local_version_fail(self):
        self.write("composer.json", {"require": {"vendor/missing": "*"}})
        result = self.run_cli(".", "8.1", "--check-deps")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Run Composer install", result.stdout)
        self.install([])
        result = self.run_cli(".", "8.1", "--check-deps")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Missing installed dependency: vendor/missing", result.stdout)
        for option in ("--source-version=v1", "--version=v1"):
            with self.subTest(option=option):
                result = self.run_cli(".", "8.1", option)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--source-version is not supported", result.stdout)
        self.assertEqual(self.calls("phpcs"), [])

    def test_local_project_without_dependencies_needs_no_vendor(self):
        result = self.run_cli(".", "8.1", "--check-deps", "--show-deps")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("No dependencies", result.stdout)
        self.assertNotIn("vendor", self.calls("phpcs")[-1]["args"])

    def test_local_incompatibility_returns_failure(self):
        result = self.run_cli(".", "8.0")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Not compatible with PHP 8.0", result.stdout)
        self.install([{"name": "vendor/newer", "version": "1", "require": {"php": ">=8.2"}}])
        for mode in ("--check-deps", "--check-deps=full"):
            with self.subTest(mode=mode):
                result = self.run_cli(".", "8.1", mode)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("Installed dependency vendor/newer requires PHP >=8.2", result.stdout)

    def test_large_installed_metadata_does_not_exceed_command_argument_limits(self):
        self.install([{"name": "vendor/library", "version": "1", "require": {"php": "^8.0"},
                       "description": "x" * 200000}])
        result = self.run_cli(".", "8.1", "--check-deps")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Trusting 1 vendor package(s)", result.stdout)

    def test_composer_one_metadata_and_missing_dependency_directory(self):
        packages = [{"name": "vendor/runtime", "version": "1"}, {"name": "vendor/dev", "version": "2"}]
        self.install(packages)
        self.write("vendor/composer/installed.json", packages)
        self.write("composer.lock", {"packages": [packages[0]], "packages-dev": [packages[1]]})
        result = self.run_cli(".", "8.1", "--check-deps", "--show-deps")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Dependencies (1 packages)", result.stdout)
        self.assertNotIn("vendor/dev", result.stdout)
        shutil.rmtree(self.project / "vendor/vendor/runtime")
        result = self.run_cli(".", "8.1", "--check-deps")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Installed dependency directory missing", result.stdout)

    def test_root_scan_fallback_and_minimum_version_with_composer_constraint(self):
        self.write("composer.json", {"require": {"php": "^8.0"}})
        before = self.snapshot()
        result = self.run_cli(".", "--min-php-version")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Minimum supported PHP version: 8.1", result.stdout)
        self.assertIn(".", self.calls("phpcs")[-1]["args"])
        self.assertIn("*/vendor/*", next(a for a in self.calls("phpcs")[-1]["args"] if a.startswith("--ignore=")))
        self.assertEqual(self.snapshot(), before)

    def test_remote_sources_keep_resolution_and_version_selection(self):
        for source in ("vendor/package:^1.0", "package:vendor/package:^1.0"):
            with self.subTest(source=source):
                result = self.run_cli(source, "8.1")
                self.assertEqual(result.returncode, 0, result.stdout)
                clone = next(c for c in reversed(self.calls("git")) if c["args"][0] == "clone")
                self.assertEqual(clone["args"][1:4], ["--depth=1", "--branch", "v1.2.0"])
                self.assertEqual(clone["args"][-2], "https://example.test/repository")
                self.assertFalse(Path(clone["args"][-1]).exists())
        for source in ("https://example.test/repo", "http://example.test/repo",
                       "repo:https://example.test/repo", "repository:https://example.test/repo",
                       "git@example.test:repo", "repo:vendor/package"):
            with self.subTest(source=source):
                before = len(self.calls("curl"))
                result = self.run_cli(source, "8.1", "--source-version=dev-main")
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(len(self.calls("curl")), before)
                clone = next(c for c in reversed(self.calls("git")) if c["args"][0] == "clone")
                self.assertIn("main", clone["args"])

    def test_source_version_and_deprecated_alias_select_package_versions(self):
        for option in ("--source-version=^1.0", "--version=^1.0"):
            with self.subTest(option=option):
                result = self.run_cli("vendor/package", "8.1", option)
                self.assertEqual(result.returncode, 0, result.stdout)
                clone = next(c for c in reversed(self.calls("git")) if c["args"][0] == "clone")
                self.assertEqual(clone["args"][1:4], ["--depth=1", "--branch", "v1.2.0"])
                self.assertEqual("deprecated" in result.stdout, option.startswith("--version="))
        result = self.run_cli("https://example.test/repo", "8.1", "--version=dev-main")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("deprecated", result.stdout)
        clone = next(c for c in reversed(self.calls("git")) if c["args"][0] == "clone")
        self.assertIn("main", clone["args"])

    def test_empty_and_conflicting_source_versions_fail_before_external_commands(self):
        for args in (("vendor/package", "--source-version="),
                     ("vendor/package", "--version="),
                     ("vendor/package:^1.0", "--source-version=^2.0"),
                     ("vendor/package:^1.0", "--version=^2.0"),
                     ("vendor/package", "--source-version=v1", "--version=v2"),
                     ("vendor/package", "--version=v2", "--source-version=v1")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("[ERROR]", result.stdout)
                self.assertFalse(self.log.exists(), result.stdout)

    def test_remote_dependency_install_changes_only_temporary_clone(self):
        self.env["TEST_PACKAGES"] = json.dumps([{"name": "vendor/library", "version": "1"}])
        before = self.snapshot()
        result = self.run_cli("repo:https://example.test/repo", "8.1", "--check-deps=full", "--show-deps")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("vendor/library", result.stdout)
        self.assertTrue(any(c["args"][0] == "install" for c in self.calls("composer")))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
