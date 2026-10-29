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
    if args[0] == "build":
        print("Docker build output")
        print("Docker build progress", file=sys.stderr)
        sys.exit(int(os.environ.get("TEST_DOCKER_BUILD_EXIT", "0")))
    if args[:2] == ["image", "inspect"]:
        sys.exit(int(os.environ.get("TEST_DOCKER_IMAGE_EXIT", "0")))
    if args[0] == "pull":
        print("Docker pull output")
        print("Docker pull progress", file=sys.stderr)
        sys.exit(int(os.environ.get("TEST_DOCKER_PULL_EXIT", "0")))
    if args[0] == "run":
        sys.exit(int(os.environ.get("TEST_DOCKER_EXIT", "0")))
elif name == "composer":
    if args == ["config", "--global", "home"]:
        print(os.environ["TEST_COMPOSER_HOME"])
    elif args[0] == "install":
        failure = int(os.environ.get("TEST_COMPOSER_EXIT", "0"))
        if failure:
            print("Dependency resolution failed" if failure == 2 else "Network unavailable")
            sys.exit(failure)
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
    output = os.environ.get("TEST_SCANNER_OUTPUT", "valid")
    if output != "valid":
        print({"empty": "", "garbage": "bad report", "incomplete": "{}"}[output])
        sys.exit(1)
    failures = os.environ.get("TEST_FAILURE_VERSIONS")
    errors = int(target in failures.split(",")) if failures is not None else int(tuple(map(int, target.split("."))) < (8, 1))
    warnings = int(os.environ.get("TEST_WARNINGS", "0"))
    files = {}
    if os.environ.get("TEST_FINDINGS") == "1":
        messages = [{"type": kind, "line": 3, "column": 5, "severity": 5,
                     "source": "PHPCompatibility.Test.Feature", "message": 'Feature "quoted"\nneeds attention'}
                    for kind, count in (("ERROR", errors), ("WARNING", warnings)) for _ in range(count)]
        files = {str(pathlib.Path.cwd() / 'src/uncommitted.php'): {
            "errors": errors, "warnings": warnings, "messages": messages}}
    print(json.dumps({"totals": {"errors": errors, "warnings": warnings}, "files": files}))
    sys.exit(int(os.environ.get("TEST_SCANNER_EXIT", str(errors))))
'''


class HelpTest(unittest.TestCase):
    def check_help(self, script):
        for args, status in ((("--help",), 0), (("-h",), 0),
                             ((".", "8.1", "--help"), 0), ((), 2)):
            with self.subTest(script=script, args=args):
                result = subprocess.run(
                    [shutil.which("bash"), str(script), *args],
                    cwd=script.parent, env=dict(os.environ, PATH=""), text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, (ROOT / "HELP").read_text())
                self.assertIn("Check PHP compatibility", result.stdout)
                self.assertIn("Usage:", result.stdout)
                self.assertIn("Examples:", result.stdout)

    def test_checkout_help_works_without_external_dependencies(self):
        for script in (WRAPPER, CHECKER):
            self.check_help(script)

    def test_installed_help_is_packaged_for_both_executables(self):
        with tempfile.TemporaryDirectory(prefix="php-compat-check help ") as directory:
            prefix = Path(directory)
            result = subprocess.run(
                ["make", "install", f"INSTALL_DIR={prefix / 'bin'}"],
                cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = prefix / "bin/php-compat-check"
            self.check_help(installed)
            shutil.copyfile(CHECKER, installed)
            self.check_help(installed)


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

    def run_json(self, *args, wrapper=False):
        result = subprocess.run(["bash", str(WRAPPER if wrapper else CHECKER), *args, "--format=json"],
                                cwd=self.project, env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            self.fail(result.stdout + result.stderr)
        self.assertEqual(report["exit_code"], result.returncode, result.stderr)
        self.assertEqual(report["schema_version"], 1)
        self.assertNotIn("\033", result.stdout)
        return result, report

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
            for option in ("--source-version", "--upgrade", "--unknown", "--unknown=value", "-v"):
                for args in ((option,), ("--show-warnings", option, ".", "8.1"),
                             ("vendor/package", option),
                             ("https://example.test/repo", "8.1", option)):
                    with self.subTest(wrapper=wrapper, args=args):
                        result = self.run_cli(*args, wrapper=wrapper)
                        self.assertEqual(result.returncode, 2, result.stdout)
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

    def test_installed_wrapper_selects_matching_image_for_checks(self):
        launcher = self.base / "installed/bin/php-compat-check"
        launcher.parent.mkdir(parents=True)
        shutil.copyfile(WRAPPER, launcher)
        version_file = self.base / "installed/share/php-compat-check/VERSION"
        version_file.parent.mkdir(parents=True)
        self.env.pop("PHP_COMPAT_CHECK_IMAGE", None)
        for version in ("3.3.0", "4.0.0-rc.1"):
            image = f"zoliszabo/php-compat-check:{version}"
            version_file.write_text(version + "\n")
            with self.subTest(version=version):
                self.log.write_text("")
                result = subprocess.run(
                    ["bash", str(launcher), ".", "7.4"], cwd=self.project, env=self.env,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(result.returncode, 0, result.stdout)
                calls = self.calls("docker")
                self.assertEqual(calls[0]["args"], ["image", "inspect", image])
                self.assertEqual(calls[-1]["args"][-4:],
                                 [image, "php-compat-check", "local:/project", "7.4"])

    def test_wrapper_pulls_missing_matching_image_without_fallback(self):
        launcher = self.base / "release/bin/php-compat-check"
        launcher.parent.mkdir(parents=True)
        shutil.copyfile(WRAPPER, launcher)
        (launcher.parent.parent / "VERSION").write_text("3.3.0\n")
        self.env.pop("PHP_COMPAT_CHECK_IMAGE", None)
        self.env["TEST_DOCKER_IMAGE_EXIT"] = "1"
        image = "zoliszabo/php-compat-check:3.3.0"
        for pull_status in (0, 1):
            with self.subTest(pull_status=pull_status):
                self.log.write_text("")
                self.env["TEST_DOCKER_PULL_EXIT"] = str(pull_status)
                result = subprocess.run(
                    ["bash", str(launcher), ".", "7.4"], cwd=self.project, env=self.env,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 0 if pull_status == 0 else 2,
                                 result.stdout + result.stderr)
                self.assertIn(f"Pulling required image {image} ...", result.stdout)
                self.assertNotIn("Docker pull", result.stdout)
                if pull_status == 0:
                    self.assertEqual(result.stderr, "")
                else:
                    self.assertIn("Docker pull output", result.stderr)
                    self.assertIn("Docker pull progress", result.stderr)
                calls = self.calls("docker")
                self.assertEqual(calls[0]["args"], ["image", "inspect", image])
                self.assertEqual(calls[1]["args"], ["pull", image])
                self.assertEqual(len(calls), 3 if pull_status == 0 else 2)
        result = subprocess.run(
            ["bash", str(launcher), ".", "7.4", "--format=json"],
            cwd=self.project, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["exit_code"], 2)
        self.assertIn(f"Pulling required image {image} ...", result.stderr)
        self.assertIn("Docker pull output", result.stderr)
        self.assertIn("Docker pull progress", result.stderr)

    def development_launcher(self, installed=False):
        checkout = self.base / "development checkout"
        for name in ("Makefile", "VERSION", "HELP", "bin/php-compat-check",
                     "docker/Dockerfile", "docker/report.php", "docker/bin/php-compat-check"):
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (checkout / "VERSION").write_text("9.8.7-dev\n")
        self.env.pop("PHP_COMPAT_CHECK_IMAGE", None)
        if not installed:
            return checkout / "bin/php-compat-check", checkout
        prefix = self.base / "installed development"
        result = subprocess.run(["make", "install", f"INSTALL_DIR={prefix / 'bin'}"],
                                cwd=checkout, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        context = prefix / "share/php-compat-check/source"
        for name in ("VERSION", "HELP", "docker/Dockerfile", "docker/report.php",
                     "docker/bin/php-compat-check"):
            self.assertEqual((context / name).read_bytes(), (checkout / name).read_bytes())
        return prefix / "bin/php-compat-check", context

    def test_development_launcher_rebuilds_on_each_check(self):
        for installed in (False, True):
            with self.subTest(installed=installed):
                launcher, context = self.development_launcher(installed)
                for args in ((".", "7.4"), (".", "7.4")):
                    self.log.write_text("")
                    result = subprocess.run(
                        ["bash", str(launcher), *args], cwd=self.project, env=self.env,
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("Building development image", result.stdout)
                    self.assertNotIn("Docker build output", result.stdout + result.stderr)
                    self.assertNotIn("Docker build progress", result.stdout + result.stderr)
                    calls = self.calls("docker")
                    self.assertEqual(calls[0]["args"],
                                     ["build", "-t", "zoliszabo/php-compat-check:9.8.7-dev",
                                      "-f", str(context / "docker/Dockerfile"), str(context)])
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(calls[1]["args"][0], "run")

    def test_development_build_failure_preserves_json_output(self):
        launcher, _ = self.development_launcher()
        self.env["TEST_DOCKER_BUILD_EXIT"] = "1"
        result = subprocess.run(
            ["bash", str(launcher), ".", "7.4", "--format=json"],
            cwd=self.project, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["exit_code"], 2)
        self.assertIn("Docker build output", result.stderr)
        self.assertIn("Docker build progress", result.stderr)
        self.assertEqual([c["args"][0] for c in self.calls("docker")], ["build"])

    def test_development_install_requires_complete_matching_build_sources(self):
        launcher, context = self.development_launcher(installed=True)
        for mismatch in (True, False):
            with self.subTest(mismatch=mismatch):
                if mismatch:
                    (context / "VERSION").write_text("9.8.6-dev\n")
                else:
                    (context / "docker/Dockerfile").unlink()
                result = subprocess.run(
                    ["bash", str(launcher), ".", "7.4"], cwd=self.project, env=self.env,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("Reinstall", result.stdout)
                self.assertEqual(self.calls("docker"), [])

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
                self.assertEqual(result.returncode, 2, result.stdout)
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

    def test_maximum_scans_downwards_and_stops_at_highest_pass(self):
        self.env["TEST_FAILURE_VERSIONS"] = "8.5,8.4"
        result = self.run_cli(".", "--max-php-version")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Highest compatible PHP version checked: 8.3", result.stdout)
        calls = self.calls("phpcs")
        self.assertEqual([c["args"][c["args"].index("testVersion") + 1] for c in calls],
                         ["8.5", "8.4", "8.3"])

    def test_maximum_passing_ceiling_is_explicitly_bounded(self):
        result = self.run_cli(".", "--max-php-version", "--to-php-version=8.4")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Highest compatible PHP version checked: 8.4", result.stdout)
        self.assertIn("No upper incompatibility found within the checked versions", result.stdout)
        self.assertIn("higher versions were not checked", result.stdout)
        self.assertEqual(len(self.calls("phpcs")), 1)

    def test_shared_scan_bounds_and_no_compatible_version(self):
        self.env["TEST_FAILURE_VERSIONS"] = "8.2"
        result = self.run_cli(".", "--max-php-version", "--from-php-version=8.1", "--to-php-version=8.2")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Highest compatible PHP version checked: 8.1", result.stdout)
        result = self.run_cli(".", "--min-php-version", "--from-php-version=8.1", "--to-php-version=8.2")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Minimum supported PHP version: 8.1", result.stdout)
        self.env["TEST_FAILURE_VERSIONS"] = "8.1,8.2"
        result = self.run_cli(".", "--max-php-version", "--from-php-version=8.1", "--to-php-version=8.2")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("No compatible PHP version found", result.stdout)

    def test_search_rejects_invalid_bounds_and_conflicting_modes_before_scanning(self):
        for args in (("--max-php-version", "--min-php-version"),
                     ("--max-php-version", "8.1"), ("--to-php-version=8.2",),
                     ("--max-php-version", "--to-php-version="),
                     ("--max-php-version", "--from-php-version=8.3", "--to-php-version=8.2"),
                     ("--max-php-version", "--from-php-version=9.0")):
            with self.subTest(args=args):
                result = self.run_cli(".", *args)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertFalse(self.log.exists(), result.stdout)

    def test_maximum_explains_composer_bound_and_allows_ignoring_it(self):
        self.write("composer.json", {"require": {"php": ">=8.0 <8.3"}})
        result = self.run_cli(".", "--max-php-version")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Highest compatible PHP version checked: 8.2", result.stdout)
        self.assertIn("Versions outside Composer requirement >=8.0 <8.3 were excluded", result.stdout)
        result = self.run_cli(".", "--max-php-version", "--ignore-composer-php-version")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Highest compatible PHP version checked: 8.5", result.stdout)

    def test_maximum_dependency_checks_preserve_local_files(self):
        self.install([{"name": "vendor/older", "version": "1", "require": {"php": ">=8.0 <8.4"}}])
        before = self.snapshot()
        result = self.run_cli(".", "--max-php-version", "--check-deps=full")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Highest compatible PHP version checked: 8.3", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_wrapper_forwards_maximum_and_scan_bounds(self):
        result = self.run_cli(".", "--max-php-version", "--from-php-version=8.0", "--to-php-version=8.4", wrapper=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.calls("docker")[-1]["args"][-4:],
                         ["local:/project", "--max-php-version", "--from-php-version=8.0", "--to-php-version=8.4"])

    def test_matrix_reports_gaps_in_ascending_order(self):
        self.env["TEST_FAILURE_VERSIONS"] = "8.0,8.2"
        result = self.run_cli(".", "--matrix", "--from-php-version=8.0", "--to-php-version=8.3")
        self.assertEqual(result.returncode, 1, result.stdout)
        rows = [line for line in result.stdout.splitlines() if line.startswith("PHP ")]
        self.assertEqual(rows, ["PHP 8.0  FAIL", "PHP 8.1  PASS", "PHP 8.2  FAIL", "PHP 8.3  PASS"])
        self.assertEqual(len(self.calls("phpcs")), 4)

    def test_matrix_shows_composer_exclusions_without_scanning_them(self):
        self.write("composer.json", {"require": {"php": ">=8.1 <8.3"}})
        result = self.run_cli(".", "--matrix", "--from-php-version=8.0", "--to-php-version=8.3")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PHP 8.0  EXCLUDED (Composer requirement: >=8.1 <8.3)", result.stdout)
        self.assertIn("PHP 8.3  EXCLUDED", result.stdout)
        self.assertEqual(len(self.calls("phpcs")), 2)
        result = self.run_cli(".", "--matrix", "--from-php-version=8.0", "--to-php-version=8.3", "--ignore-composer-php-version")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("PHP 8.0  FAIL", result.stdout)

    def test_matrix_without_eligible_versions_is_not_a_success(self):
        self.write("composer.json", {"require": {"php": ">=9.0"}})
        result = self.run_cli(".", "--matrix", "--from-php-version=8.0")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("No eligible PHP versions", result.stdout)
        self.assertEqual(self.calls("phpcs"), [])

    def test_matrix_rejects_conflicting_mode_and_is_forwarded_by_wrapper(self):
        result = self.run_cli(".", "--matrix", "--max-php-version")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertFalse(self.log.exists())
        result = self.run_cli(".", "--matrix", "--from-php-version=8.0", wrapper=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.calls("docker")[-1]["args"][-3:],
                         ["local:/project", "--matrix", "--from-php-version=8.0"])

    def test_remote_incompatibility_returns_failure_for_every_source_syntax(self):
        for source in ("https://example.test/repo", "repo:https://example.test/repo", "vendor/package"):
            with self.subTest(source=source):
                result = self.run_cli(source, "8.0")
                self.assertEqual(result.returncode, 1, result.stdout)

    def test_unreliable_scanner_output_aborts_every_mode(self):
        modes = (("8.1",), ("--min-php-version",), ("--max-php-version",), ("--matrix",))
        for output in ("empty", "garbage", "incomplete"):
            self.env["TEST_SCANNER_OUTPUT"] = output
            for mode in modes:
                with self.subTest(output=output, mode=mode):
                    before = len(self.calls("phpcs"))
                    args = () if mode == ("8.1",) else ("--from-php-version=8.1", "--to-php-version=8.2")
                    result = self.run_cli(".", *mode, *args)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn("invalid report", result.stdout)
                    self.assertEqual(len(self.calls("phpcs")) - before, 1)

    def test_scanner_runtime_failures_are_not_compatibility_findings(self):
        self.env["TEST_SCANNER_EXIT"] = "16"
        result = self.run_cli(".", "8.1")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.env["TEST_SCANNER_EXIT"] = "1"
        result = self.run_cli(".", "8.1")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("failed without reporting findings", result.stdout)

    def test_deprecation_warnings_alone_do_not_fail_checks(self):
        self.env["TEST_WARNINGS"] = "2"
        self.env["TEST_SCANNER_EXIT"] = "2"
        for flags in ((), ("--show-warnings",)):
            result = self.run_cli(".", "8.1", *flags)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_composer_solver_and_operational_errors_have_distinct_exit_codes(self):
        for composer_exit, expected in (("2", 1), ("1", 2)):
            self.env["TEST_COMPOSER_EXIT"] = composer_exit
            result = self.run_cli("repo:https://example.test/repo", "8.1", "--check-deps=full")
            self.assertEqual(result.returncode, expected, result.stdout)

    def test_invalid_project_metadata_cannot_be_reported_as_compatible(self):
        for contents in ("", "bad json", "[]", '{"require":{"php":"not a constraint"}}'):
            (self.project / "composer.json").write_text(contents)
            result = self.run_cli(".", "8.1")
            self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(self.calls("phpcs"), [])

    def test_wrapper_normalizes_docker_failures_and_preserves_check_status(self):
        for docker_exit, expected in (("1", 1), ("2", 2), ("125", 2)):
            self.env["TEST_DOCKER_EXIT"] = docker_exit
            result = self.run_cli(".", "8.1", wrapper=True)
            self.assertEqual(result.returncode, expected, result.stdout)

    def test_unknown_target_and_extra_positionals_fail_before_external_commands(self):
        for args in ((".", "9.0"), (".", "8.1", "extra")):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertFalse(self.log.exists())

    def test_json_check_has_metadata_and_separate_diagnostics(self):
        result, report = self.run_json(".", "8.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["mode"], "check")
        self.assertEqual(report["source"]["input"], ".")
        self.assertEqual(report["source"]["type"], "local")
        self.assertEqual(report["summary"]["version"], "8.1")
        self.assertEqual(report["results"][0]["errors"], 0)
        self.assertEqual(report["scan"]["from"], "8.1")
        self.assertFalse(report["scan"]["coverage_complete"])
        self.assertIn("Testing PHP 8.1", result.stderr)

    def test_json_findings_preserve_locations_and_escaped_messages(self):
        self.env["TEST_FINDINGS"] = "1"
        self.env["TEST_WARNINGS"] = "1"
        result, report = self.run_json(".", "8.0")
        self.assertEqual(result.returncode, 1, result.stderr)
        row = report["results"][0]
        self.assertEqual((row["status"], row["reason"], row["errors"], row["warnings"]),
                         ("incompatible", "source", 1, 1))
        self.assertEqual([finding["type"] for finding in row["findings"]], ["error", "warning"])
        self.assertEqual(row["findings"][0]["file"], "src/uncommitted.php")
        self.assertEqual(row["findings"][0]["message"], 'Feature "quoted"\nneeds attention')

    def test_json_minimum_and_maximum_have_explicit_result_versions(self):
        result, report = self.run_json(".", "--min-php-version", "--from-php-version=8.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["summary"]["version"], "8.1")
        self.assertEqual([row["status"] for row in report["results"]], ["incompatible", "compatible"])
        self.env["TEST_FAILURE_VERSIONS"] = "8.5,8.4"
        result, report = self.run_json(".", "--max-php-version")
        self.assertEqual(report["summary"]["version"], "8.3")
        self.assertTrue(report["summary"]["upper_incompatibility_found"])
        self.env["TEST_FAILURE_VERSIONS"] = ""
        result, report = self.run_json(".", "--max-php-version")
        self.assertFalse(report["summary"]["upper_incompatibility_found"])

    def test_json_matrix_includes_exclusions_and_gaps(self):
        self.write("composer.json", {"require": {"php": ">=8.1"}})
        self.env["TEST_FAILURE_VERSIONS"] = "8.2"
        result, report = self.run_json(".", "--matrix", "--from-php-version=8.0", "--to-php-version=8.3")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual([row["status"] for row in report["results"]],
                         ["excluded", "compatible", "incompatible", "compatible"])
        self.assertIsNone(report["results"][0]["errors"])
        self.assertEqual(report["scan"]["composer_constraint"], ">=8.1")
        self.assertIsNone(report["summary"]["version"])

    def test_json_errors_are_structured_for_parser_and_scanner_failures(self):
        result, report = self.run_json(".", "8.1", "--unknown")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(report["summary"]["status"], "error")
        self.assertIn("Unknown option", report["diagnostics"][0]["message"])
        self.env["TEST_SCANNER_OUTPUT"] = "garbage"
        result, report = self.run_json(".", "--max-php-version")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(report["results"][0]["status"], "error")
        self.assertEqual(report["results"][0]["reason"], "scanner_error")
        self.assertIsNone(report["summary"]["version"])

    def test_json_missing_dependencies_and_wrapper_failures_are_not_successes(self):
        self.write("composer.json", {"require": {"vendor/missing": "*"}})
        result, report = self.run_json(".", "8.1", "--check-deps")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(report["diagnostics"])
        for args in ((".", "8.1", "--unknown"), ("local:missing", "8.1")):
            result, report = self.run_json(*args, wrapper=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(report["summary"]["status"], "error")
        self.env["TEST_DOCKER_EXIT"] = "125"
        result, report = self.run_json(".", "8.1", wrapper=True)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_json_dependencies_avoid_argument_limits_and_exclude_development_packages(self):
        self.install([{"name": "vendor/runtime", "version": "1", "require": {"php": "^8.0"},
                       "description": "x" * 200000}, {"name": "vendor/dev", "version": "2"}], dev=["vendor/dev"])
        before = self.snapshot()
        result, report = self.run_json(".", "8.1", "--check-deps")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["results"][0]["dependencies"], [{"name": "vendor/runtime", "version": "1",
                         "php_constraint": "^8.0", "status": "trusted"}])
        self.assertEqual(self.snapshot(), before)

    def test_json_constraint_failure_does_not_claim_dependencies_were_scanned(self):
        self.install([{"name": "vendor/newer", "version": "1", "require": {"php": ">=8.2"}},
                      {"name": "vendor/eligible", "version": "2", "require": {"php": "^8.0"}}])
        result, report = self.run_json(".", "8.1", "--check-deps=full")
        self.assertEqual(result.returncode, 1, result.stderr)
        row = report["results"][0]
        self.assertEqual(row["reason"], "dependency_constraint")
        self.assertIsNone(row["errors"])
        self.assertEqual([dependency["status"] for dependency in row["dependencies"]],
                         ["incompatible", "not_checked"])
        self.assertEqual(self.calls("phpcs"), [])

    def test_help_and_version_ignore_json_format_without_external_dependencies(self):
        for script in (CHECKER, WRAPPER):
            for option, output in (("--help", (ROOT / "HELP").read_text()),
                                   ("--version", "php-compat-check " + (ROOT / "VERSION").read_text())):
                result = subprocess.run([shutil.which("bash"), str(script), option, "--format=json"],
                                        env=dict(os.environ, PATH=""), text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, output)


if __name__ == "__main__":
    unittest.main()
