# Fixture projects

These are intentionally tiny local projects for the Docker integration tests.
All PHP code and package metadata are maintained here; no fixture dependency
downloads or Composer install step are needed. The `vendor/` directory and
`composer.lock` in `installed-dependencies` are hand-written test data, not
third-party dependencies or a lock file intended for installation.

| Project | Expected behavior |
|---------|-------------------|
| `php81` | The enum requires PHP 8.1 despite the declared `>=7.4` minimum. PHP 8.0 fails; minimum-version detection finds 8.1. |
| `installed-dependencies` | Root code requires PHP 7.4 and uses the fallback `.` scan directory. The production dependency declares `>=8.0` but contains a PHP 8.1 enum: shallow mode trusts it on 8.0, full mode catches it. Its PHP 8.2 development dependency must be excluded. |
| `missing-dependencies` | Source-only scans pass on 7.4; dependency checks fail because the declared package is not installed. |

The runner copies each fixture to a temporary directory with spaces in its path,
uses the real host wrapper and Docker image, and verifies that every fixture file
is unchanged after each test. The temporary copies have no Git metadata.

Run from the repository root with `make test-integration`.
