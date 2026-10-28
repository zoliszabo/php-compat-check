# php-compat-check

A CLI tool for detecting the minimum and target PHP version compatibility of Composer-based projects.

It uses PHPCompatibility (PHP_CodeSniffer) and can optionally install dependencies to provide more realistic results.

## Features

- Check compatibility against a specific PHP version
- Automatically detect the minimum supported PHP version
- Optional dependency-aware analysis using Composer
- Accepts a local directory, Git repository URL, or Packagist package name (`vendor/package[:version]`)
- Checks local working files and installed dependencies without modifying the project
- Automatically resolves scan directories from `composer.json` autoload configuration
- Auto-detects polyfill libraries and suppresses false positives accordingly
- Runs in a Docker container for consistent results
- Simple CLI interface

## Usage

### Basic compatibility check

```bash
php-compat-check <source> <php-version>
```

The `<source>` argument is resolved automatically, or can have an explicit prefix:

| Source | Interpretation |
|--------|----------------|
| `.`, `..`, `./path`, `../path`, `/absolute/path` | Local directory |
| `vendor/package[:version]` | Packagist package, optionally with a version constraint |
| `http://...`, `https://...`, Git SSH URLs | Git repository |
| `local:<path>` | Explicit local directory |
| `package:vendor/package[:version]` | Explicit Packagist package |
| `repo:<url>`, `repository:<url>` | Explicit Git repository |

Explicit prefixes take precedence. An unprefixed `vendor/package` always means a Packagist package, even if that directory exists locally. Use `./vendor/package` or `local:vendor/package` to select the directory.

Existing package and repository commands continue to work:

```bash
php-compat-check https://github.com/vendor/package 8.1
php-compat-check vendor/package 8.1
php-compat-check vendor/package:^6.0 8.1
php-compat-check vendor/package:dev-main 8.1
php-compat-check https://github.com/vendor/package 8.1 --source-version=v6.0.2
```

### Check a local project

```bash
# Current directory
php-compat-check . 8.1

# Relative or absolute directory (quote paths containing spaces)
php-compat-check ../my-project 8.1
php-compat-check "local:/path/to/my project" 8.1

# Find the minimum version using the current working files
php-compat-check . --min-php-version

# Include dependencies already installed in vendor/
php-compat-check . 8.1 --check-deps=full --show-deps
```

Local projects are mounted read-only and scanned directly, including uncommitted and untracked files within the scan directories. No Git repository is required. The tool never installs or updates local dependencies, and leaves `composer.json`, `composer.lock`, and `vendor/` unchanged. `--source-version` applies only to remote sources; local checks always use the current files.

Without `--check-deps`, `vendor/` is excluded. With `--check-deps`, installed production dependencies are read from `vendor/composer/installed.json`; development-only packages are excluded. Shallow mode trusts compatible PHP requirements; full mode scans every installed production package. Installed dependencies whose PHP requirement excludes the target make the check fail, including during minimum-version detection. Missing dependencies produce an error asking you to run Composer install in the project first. Local dependency checks inspect the installed set; they do not resolve alternative dependency versions for each PHP target.

### Find minimum supported PHP version

```bash
php-compat-check <source> --min-php-version
```

Scans versions that satisfy the `require.php` constraint declared in `composer.json`. Defaults to scanning from `5.6` if no constraint is found.

If the found minimum equals the constraint's own minimum (or the explicitly provided `--from-php-version`), a note will suggest retrying with `--ignore-composer-php-version` to scan without filtering.

### Scanning dependencies

```bash
php-compat-check <source> <php-version> --check-deps
```

For remote sources, installs non-dev Composer dependencies and includes them in the scan. For local sources, checks already-installed production dependencies without running Composer install. Accepts an optional mode:

| Value | Behaviour |
|-------|-----------|
| *(no value)* / `shallow` | Trust packages that declare a `require.php` compatible with the target — only scan packages without a declared constraint. **Default when `--check-deps` is used.** |
| `full` | Scan all vendor packages regardless of their declared PHP constraint. |

```bash
# Shallow scan — trust packages that declare compatibility
php-compat-check vendor/package 8.1 --check-deps

# Equivalent explicit form
php-compat-check vendor/package 8.1 --check-deps=shallow

# Full scan — check every vendor package
php-compat-check vendor/package 8.1 --check-deps=full
```

For remote sources, packages that declare an incompatible `require.php` are always excluded from the scan (they wouldn't be installed by Composer either). For local sources, incompatible installed dependencies are reported as errors. Packages with no `require.php` are always scanned.

### Options

| Flag | Description |
|------|-------------|
| `--check-deps[=shallow\|full]` | Check production dependencies: install them for remote sources, or use the installed set for local sources. Defaults to `shallow`. |
| `--min-php-version` | Find the minimum compatible PHP version |
| `--from-php-version=<version>` | Override the lower bound when using `--min-php-version` |
| `--ignore-composer-php-version` | Ignore `require.php` from `composer.json` when determining the scan range, filtering versions, or setting the platform version |
| `--scan-dirs=<dirs>` | Comma-separated list of directories/files to scan (default: resolved from `composer.json` autoload) |
| `--show-deps` | With `--check-deps`, print installed production dependencies and their scan status (`checked`, `trusted`, `ignored`, or locally `incompatible`) |
| `--show-warnings` | Display PHPCompatibility warnings in addition to errors (warnings are hidden by default) |
| `--source-version=<version>` | Select a remote package/repository version (package constraint, tag, branch, or `dev-main` style); unavailable for local sources |
| `--version` | Print the executable's version and exit; works without Docker, Composer, or a source argument |
| `--version=<ref>` | Deprecated alias for `--source-version=<version>`; emits a warning |
| `--upgrade` | Pull the configured Docker image (default: `latest`); updates the checker image, while the local wrapper and version file are updated with `make install` |

Unknown flags are rejected with an error. The Docker wrapper reports its own installed version with `--version`; when running the command directly inside an image, it reports that image's executable version.

### Examples

```bash
# Check against a specific version
php-compat-check sebastian/diff 8.1

# Check a specific release
php-compat-check sebastian/diff:^6.0 8.1

# Check the dev-main branch
php-compat-check sebastian/diff:dev-main 8.1

# Find minimum supported version
php-compat-check sebastian/diff --min-php-version

# Find minimum, starting from a specific version
php-compat-check sebastian/diff --min-php-version --from-php-version=7.4

# Include dependencies (shallow — trust declared constraints)
php-compat-check sebastian/diff 8.1 --check-deps

# Include dependencies (full — scan everything)
php-compat-check sebastian/diff 8.1 --check-deps=full

# Show dependency table
php-compat-check sebastian/diff 8.1 --check-deps --show-deps

# Scan specific directories
php-compat-check sebastian/diff 8.1 --scan-dirs=src,lib
```

## How it works

1. Resolves the source type from an explicit prefix or the package/URL/path syntax
2. Resolves Packagist packages to Git URLs and clones remote repositories into a temporary directory; local directories are mounted read-only instead
3. Detects scan directories from `composer.json` autoload (`psr-4`, `psr-0`, `classmap`, `files`); falls back to `.`
4. When `--check-deps` is set: for remote sources, strips `require-dev` and `autoload-dev`, simulates the target PHP platform version, and installs non-dev dependencies; for local sources, reads installed production dependency metadata
5. Validates the requested version (or scanned range) against `composer.json`'s `require.php` constraint using Composer's semver library, unless `--ignore-composer-php-version` is set
6. Auto-detects polyfill libraries and applies the appropriate PHPCompatibility companion standards to suppress false positives:
   - Without `--check-deps`: reads `require` from `composer.json`
   - With `--check-deps`: reads `composer.lock` after remote installation, or local installed metadata, to catch transitive polyfill dependencies
   - Supported: `symfony/polyfill-php*`, `paragonie/random_compat`, `paragonie/sodium_compat`, `ircmaxell/password-compat`
7. In shallow mode, vendor packages whose `require.php` satisfies the target are trusted and excluded from the scan; packages with no `require.php` are always scanned
8. Runs PHPCompatibility via PHP_CodeSniffer against the resolved directories, ignoring `vendor/composer/`, `vendor/autoload.php`, and polyfill version-gated bootstrap files (e.g. `bootstrap80.php`)

## Installation

### Option 1: Use Make (recommended)

```bash
make install
```

If you get permission denied errors, use `sudo`:

```bash
sudo make install
```

You can customize the installation directory:

```bash
make install INSTALL_DIR=$HOME/.local/bin
```

To uninstall:

```bash
make uninstall
```

### Option 2: Manual installation

```bash
install -D -m 644 VERSION /usr/local/share/php-compat-check/VERSION
cp bin/php-compat-check /usr/local/bin/php-compat-check
chmod +x /usr/local/bin/php-compat-check
```

### Option 3: Use Docker directly

```bash
docker run --rm zoliszabo/php-compat-check php-compat-check <source> <php-version>
```

For a local project, mount it read-only and pass the container path:

```bash
docker run --rm -v "$PWD:/project:ro" zoliszabo/php-compat-check php-compat-check local:/project 8.1
```

## Development

To test changes locally without pushing to Docker Hub:

```bash
# Build the image locally
make build

# Run against a package (rebuilds automatically)
make run ARGS="sebastian/diff 8.1"
make run ARGS="sebastian/diff --min-php-version"
make run ARGS="sebastian/diff 8.1 --check-deps"
make run ARGS=". 8.1"
```

`make run` always rebuilds the image before running, so you never test stale code.

To run CLI regression tests (requires Python 3, Bash, PHP, jq, and a Composer PHAR on `PATH`):

```bash
python3 -m unittest discover -s tests -v
```

The tests stub Docker, network access, and PHP_CodeSniffer while using real PHP and Composer semver. If Composer is not installed as a PHAR, set `COMPOSER_AUTOLOAD` to an autoloader that provides `Composer\Semver\Semver`.

Permanent minimal projects in [tests/fixtures](tests/fixtures/README.md) also exercise the real Docker image and PHPCompatibility:

```bash
make test-integration
```

This builds the current image and runs the fixture tests using Python 3, Bash, and Docker. The tests cover actual PHP syntax compatibility, minimum-version detection, shallow/full dependency scans, development dependency exclusion, missing dependencies, and local paths with spaces. Fixture dependencies and Composer metadata are hand-written and included in the repository, so the fixture checks need no dependency downloads. Each fixture is copied into a temporary directory, mounted read-only through the real CLI wrapper, and checked for file changes after each test.

To reuse an image already built from the current source:

```bash
PHP_COMPAT_CHECK_IMAGE=php-compat-check:dev python3 -m unittest discover -s tests/integration -v
```

## Requirements

- Docker
