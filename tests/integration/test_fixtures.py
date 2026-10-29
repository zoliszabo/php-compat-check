"""Real Docker/PHPCompatibility tests. Run with make test-integration."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures"
IMAGE = os.environ.get("PHP_COMPAT_CHECK_IMAGE", "php-compat-check:dev")


class FixtureTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        result = subprocess.run(["docker", "image", "inspect", IMAGE],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if result.returncode:
            raise RuntimeError(f"Cannot access test image {IMAGE}. Run make build first.\n{result.stderr}")


    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="php-compat-check-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project with spaces"


    def use_fixture(self, name):
        shutil.copytree(FIXTURES / name, self.project)
        self.before = self.snapshot()


    def snapshot(self):
        return {str(path.relative_to(self.project)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.project.rglob("*") if path.is_file()}


    def tearDown(self):
        if hasattr(self, "before"):
            self.assertEqual(self.snapshot(), self.before, "The local project was modified")


    def check(self, *args, status=0, contains=(), excludes=()):
        result = subprocess.run(["bash", str(ROOT / "bin/php-compat-check"), *args],
                                cwd=self.project,
                                env=dict(os.environ, PHP_COMPAT_CHECK_IMAGE=IMAGE),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, status, result.stdout)
        for text in contains:
            self.assertIn(text, result.stdout)
        for text in excludes:
            self.assertNotIn(text, result.stdout)


    def test_image_reports_the_shared_version(self):
        result = subprocess.run(
            ["docker", "run", "--rm", IMAGE, "php-compat-check", "--version"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         f"php-compat-check {(ROOT / 'VERSION').read_text().strip()}\n")


    def test_image_displays_command_help(self):
        result = subprocess.run(
            ["docker", "run", "--rm", IMAGE, "php-compat-check", "--help"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (ROOT / "HELP").read_text())


    def test_local_paths_and_prefixes(self):
        self.use_fixture("php81")
        for source in (".", "local:.", "../project with spaces", str(self.project)):
            with self.subTest(source=source):
                self.check(source, "8.1", contains=["Compatible with PHP 8.1"])


    def test_enum_fails_on_php80(self):
        self.use_fixture("php81")
        self.check(".", "8.0", status=1,
                   contains=["Status.php", "Not compatible with PHP 8.0"])


    def test_minimum_php_version_from_actual_source(self):
        self.use_fixture("php81")
        self.check(".", "--min-php-version", contains=["Minimum supported PHP version: 8.1"])


    def test_dependencies_are_excluded_without_flag_in_root_scan(self):
        self.use_fixture("installed-dependencies")
        self.check(".", "7.4", contains=["Compatible with PHP 7.4"])


    def test_shallow_scan_trusts_declared_compatibility(self):
        self.use_fixture("installed-dependencies")
        self.check(".", "8.0", "--check-deps", "--show-deps",
                   contains=["Compatible with PHP 8.0", "fixture/runtime", "trusted"],
                   excludes=["fixture/dev"])


    def test_full_scan_detects_dependency_source_incompatibility(self):
        self.use_fixture("installed-dependencies")
        self.check(".", "8.0", "--check-deps=full", status=1,
                   contains=["RuntimeStatus.php", "Not compatible with PHP 8.0"],
                   excludes=["DevOnly.php"])


    def test_dev_dependencies_are_excluded_from_full_scan(self):
        self.use_fixture("installed-dependencies")
        self.check(".", "8.1", "--check-deps=full", "--show-deps",
                   contains=["Dependencies (1 packages)", "fixture/runtime", "checked",
                             "Compatible with PHP 8.1"],
                   excludes=["fixture/dev", "DevOnly.php"])


    def test_installed_dependency_requirement_is_enforced(self):
        self.use_fixture("installed-dependencies")
        self.check(".", "7.4", "--check-deps", status=1,
                   contains=["Installed dependency fixture/runtime requires PHP >=8.0"])


    def test_dependency_modes_have_different_minimums(self):
        self.use_fixture("installed-dependencies")
        for mode, minimum in (("shallow", "8.0"), ("full", "8.1")):
            with self.subTest(mode=mode):
                self.check(".", "--min-php-version", f"--check-deps={mode}",
                           contains=[f"Minimum supported PHP version: {minimum}"])


    def test_missing_dependencies_are_reported_without_installing(self):
        self.use_fixture("missing-dependencies")
        self.check(".", "7.4", contains=["Compatible with PHP 7.4"])
        self.check(".", "7.4", "--check-deps", status=1,
                   contains=["Installed dependency metadata not found", "Run Composer install"])


    def test_maximum_php_version_detects_removed_function(self):
        self.use_fixture("removed-in-php80")
        self.check(".", "--max-php-version", contains=["Highest compatible PHP version checked: 7.4"])


    def test_maximum_at_search_ceiling_is_bounded(self):
        self.use_fixture("php81")
        self.check(".", "--max-php-version", "--to-php-version=8.2",
                   contains=["Highest compatible PHP version checked: 8.2", "No upper incompatibility found"])



if __name__ == "__main__":
    unittest.main()
