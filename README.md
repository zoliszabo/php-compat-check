# php-compat-check

A CLI tool for checking PHP version compatibility, finding compatible version bounds, and reporting compatibility matrices for Composer-based projects.

It uses PHPCompatibility (PHP_CodeSniffer) and can optionally install dependencies to provide more realistic results.

## Features

- Check compatibility against a specific PHP version
- Automatically detect the minimum supported PHP version
- Find the highest compatible PHP version within a bounded search
- Report compatibility per PHP version, including gaps and Composer exclusions
- Emit structured JSON reports and consistent CI exit codes
- Optional dependency-aware analysis using Composer
- Accepts a local directory, Git repository URL, or Packagist package name (`vendor/package[:version]`)
- Checks local working files and installed dependencies without modifying the project
- Automatically resolves scan directories from `composer.json` autoload configuration
- Auto-detects polyfill libraries and suppresses false positives accordingly
- Runs in a Docker container for consistent results
- Simple CLI interface

## Usage

Run `php-compat-check --help` (or `-h`) for a description, supported sources, options, and examples. Help works without Docker or Composer. Running without arguments also displays help and exits with status 2.

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

Scans known versions that satisfy the `require.php` constraint declared in `composer.json`, starting at PHP 5.6 unless a lower bound is supplied. Use `--from-php-version` and `--to-php-version` to bound the search.

If the found minimum equals the constraint's own minimum (or the explicitly provided `--from-php-version`), a note will suggest retrying with `--ignore-composer-php-version` to scan without filtering.

### Find the highest compatible PHP version checked

```bash
php-compat-check . --max-php-version
php-compat-check . --max-php-version --from-php-version=8.0 --to-php-version=8.4
php-compat-check . --max-php-version --check-deps=full
```

Checks known PHP versions from newest to oldest and stops at the first passing version. The tool currently knows PHP 5.6, 7.0–7.4, and 8.0–8.5. Both search modes accept bounds from that list; reversed bounds, conflicting search modes, and a target version combined with a search are rejected.

The result is the **highest compatible version checked**, rather than a promise about future PHP releases or every version below it. When the search ceiling passes, the output explicitly says that no upper incompatibility was found within the checked versions. Composer constraints filter the search by default, and the output explains their effect; use `--ignore-composer-php-version` to investigate source compatibility beyond the declared constraints. Dependency modes behave as described below. Static analysis can miss runtime issues and does not cover every PHP change.

### Compatibility matrix

```bash
php-compat-check . --matrix --from-php-version=8.0 --to-php-version=8.5
php-compat-check . --matrix --check-deps=full
```

Checks every known version in the bounded range independently, then prints `PASS`, `FAIL`, or `EXCLUDED` for each version. Composer exclusions are shown explicitly and are not counted as checked versions; use `--ignore-composer-php-version` to scan them too. A matrix succeeds when at least one version was checked and every checked version passes. Compatibility gaps remain visible, so passing endpoints never imply support for all intervening versions. Choose one of minimum search, maximum search, or matrix mode per invocation.

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
| `--help`, `-h` | Describe the command and show usage, supported sources, options, and examples |
| `--check-deps[=shallow\|full]` | Check production dependencies: install them for remote sources, or use the installed set for local sources. Defaults to `shallow`. |
| `--min-php-version` | Find the minimum compatible PHP version |
| `--max-php-version` | Find the highest compatible PHP version within the checked range |
| `--matrix` | Check every version in the selected range and show PASS/FAIL/EXCLUDED |
| `--format=text\|json` | Output format; JSON includes per-version findings and scan metadata |
| `--from-php-version=<version>` | Set the lower bound for a version search or matrix |
| `--to-php-version=<version>` | Set the upper bound for a version search or matrix |
| `--ignore-composer-php-version` | Ignore the root project's `require.php` when filtering or validating targets; dependency checks still use the target PHP platform |
| `--scan-dirs=<dirs>` | Comma-separated list of directories/files to scan (default: resolved from `composer.json` autoload) |
| `--show-deps` | With `--check-deps`, print installed production dependencies and their scan status (`checked`, `trusted`, `ignored`, or locally `incompatible`) |
| `--show-warnings` | Display PHPCompatibility warnings in addition to errors (warnings are hidden by default) |
| `--source-version=<version>` | Select a remote package/repository version (package constraint, tag, branch, or `dev-main` style); unavailable for local sources |
| `--version` | Print the executable's version and exit; works without Docker, Composer, or a source argument |
| `--version=<ref>` | Deprecated alias for `--source-version=<version>`; emits a warning |

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

### JSON reports

```bash
php-compat-check . 8.1 --format=json
php-compat-check . --max-php-version --check-deps=full --format=json
php-compat-check . --matrix --from-php-version=8.0 --format=json > compatibility.json
```

`--format=json` writes one JSON document to stdout and sends progress and human diagnostics to stderr. It supports checks, both searches, and matrices. Exit codes keep the meaning below, including when a valid JSON report describes incompatibility or an analysis error. `--format=text` is the default. Help and version requests remain plain text.

Reports use `schema_version: 1` with these fields:

| Field | Contents |
|-------|----------|
| `tool_version`, `mode`, `source` | Checker version, `check`/`min`/`max`/`matrix`, and source input/type/version/commit |
| `scan` | Requested bounds, known PHP versions, Composer constraint and whether it was ignored, dependency mode, and static-analysis coverage limits |
| `results` | Rows with `php_version`, `status`, `reason`, error/warning counts, findings, and dependency versions/statuses |
| `summary` | Overall status, selected version for successful checks/searches, and whether a maximum search found an incompatible newer version |
| `diagnostics`, `exit_code` | Diagnostic messages with levels, and the same code returned by the command |

Row statuses are `compatible`, `incompatible`, `excluded`, and `error`. Reasons distinguish source findings, Composer constraints, dependency requirements/resolution, and scanner failures. Counts are `null` when the scanner did not run; excluded versions are never reported as passing. Findings include relative file paths, locations, messages, sniff identifiers, and severity. JSON always includes scanner warnings, independently of `--show-warnings`, which controls text display only. Dependency details exclude development-only packages and identify trusted versus scanned packages.

For maximum searches, `summary.version` is the highest passing version checked. `summary.upper_incompatibility_found` is false when no newer checked version failed; inspect the scan bounds and Composer constraint before inferring an upper limit. Matrix reports preserve every row, including gaps. `scan.coverage_complete` is false because static analysis does not establish complete runtime compatibility. Early startup failures may have `null` metadata and no result rows, while still returning a structured error report.

### Exit codes for automation

| Code | Meaning |
|------|---------|
| `0` | Compatible target, a successful minimum/maximum search, or a matrix whose checked versions all pass |
| `1` | Incompatible target, no compatible version found, or a matrix with failures/no eligible versions |
| `2` | Invalid input or incomplete analysis, such as missing local dependencies, a network failure, or a failed scanner |

Local directories, repository URLs, and Packagist packages use the same exit codes. **Migration note:** older versions returned `0` for completed remote-source checks even when incompatibilities were found. CI scripts should now handle a failing check explicitly. Deprecation warnings remain informational, including with `--show-warnings`.

Version searches stop on operational failures instead of presenting an unreliable bound. A Composer dependency-solving failure counts as an incompatible target; other Composer failures prevent analysis. Unknown target versions are rejected because scanner coverage cannot be inferred for them.

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

### Option 1: Download a release archive (recommended)

Download [php-compat-check-latest.tar.gz](https://github.com/zoliszabo/php-compat-check/releases/latest/download/php-compat-check-latest.tar.gz) to get the latest stable release without looking up a version. Each release also offers `php-compat-check-<version>.tar.gz` for a specific version. Both archives contain the executable and its supporting files; Git and Make are not required. Docker must be installed and running for compatibility checks.

Download, extract, and install the latest stable release for your user:

```bash
curl -fL -o php-compat-check-latest.tar.gz \
  https://github.com/zoliszabo/php-compat-check/releases/latest/download/php-compat-check-latest.tar.gz
tar -xzf php-compat-check-latest.tar.gz
cd php-compat-check-latest
mkdir -p "$HOME/.local"
cp -R bin share "$HOME/.local/"
export PATH="$HOME/.local/bin:$PATH"
php-compat-check --version
php-compat-check --help
```

If `~/.local/bin` is not already on your `PATH`, add the `export` line to your shell's startup file. Keep `share/php-compat-check/` alongside `bin/`; the executable needs its `VERSION` and `HELP` files. The launcher uses `zoliszabo/php-compat-check:<version>`, with the exact version from its packaged `VERSION` file. Release versions automatically pull that image if it is missing locally; versions ending in `-dev` build it locally as described under Development. Set `PHP_COMPAT_CHECK_IMAGE` to select a different image explicitly and bypass automatic development builds.

Each release also includes `SHA256SUMS` covering both archives. To verify a download, place that release's checksum file beside the archive and run `sha256sum --check --ignore-missing SHA256SUMS` before extracting. The latest stable release's checksum file is available at [releases/latest/download/SHA256SUMS](https://github.com/zoliszabo/php-compat-check/releases/latest/download/SHA256SUMS). To move to a newer tool version, install that release's launcher; its next check selects the matching image.

### Option 2: Install from source with Make

```bash
git clone https://github.com/zoliszabo/php-compat-check.git
cd php-compat-check
make install
```

If you get permission denied errors, use `sudo`:

```bash
sudo make install
```

You can customize the installation directory:

```bash
make install INSTALL_DIR="$HOME/.local/bin"
```

To uninstall:

```bash
make uninstall
```

### Option 3: Manual installation from source

```bash
install -D -m 644 VERSION /usr/local/share/php-compat-check/VERSION
install -D -m 644 HELP /usr/local/share/php-compat-check/HELP
cp bin/php-compat-check /usr/local/bin/php-compat-check
chmod +x /usr/local/bin/php-compat-check
```

### Option 4: Use Docker directly

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

For versions ending in `-dev`, running `bin/php-compat-check` directly rebuilds the version-tagged image from the checkout before each check, using Docker's layer cache. Builds use the launcher's sources, regardless of which project is being scanned. The launcher never falls back to `latest`.

`make install` for a development version also installs the required build files under `share/php-compat-check/source/`, so the installed launcher can build without the original checkout. Run `make install` again to include later source changes. An older development installation without these files reports an error asking you to reinstall.

An explicit `PHP_COMPAT_CHECK_IMAGE` bypasses automatic builds and keeps the usual inspect/pull/run behavior. For example, after `make build`, use `PHP_COMPAT_CHECK_IMAGE=php-compat-check:dev php-compat-check . 8.1` to reuse that local image.

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

### Versioning and releases

Use [Semantic Versioning](https://semver.org/): patch releases for compatible fixes, minor releases for compatible features and deprecations, and major releases for breaking changes. Untagged development toward the next release uses a prerelease version such as `3.1.0-dev`.

The root `VERSION` file is the single source of the version number. Both scripts read it directly in a checkout. Installation copies it to `share/php-compat-check/VERSION` beside the installation's `bin` directory, and Docker builds include it at `/usr/local/share/php-compat-check/VERSION`.

The shared `HELP` file is packaged in the same directory so both entry points display the same command documentation.

To release, start from a clean checkout on a branch that already exists on the remote, with Git, Make, an authenticated GitHub CLI (`gh`), and the prerequisites for `make test` installed:

```bash
make release
```

For example, with `VERSION` set to `3.2.1-dev`, this runs the regression tests, commits `VERSION` as `3.2.1`, creates the annotated `3.2.1` tag, and pushes the release commit and tag together to `origin`. It creates a draft GitHub Release with generated notes using `gh`, then commits and pushes `3.2.2-dev` on the same branch. The tag continues to point to the release commit. The command returns after pushing; GitHub Actions finishes building the images and archives, uploads the assets, and publishes the draft when they are ready.

Override the release version, next development version, or remote when needed:

```bash
make release RELEASE_VERSION=3.3.0 NEXT_VERSION=3.4.0-dev
make release RELEASE_REMOTE=upstream
```

When `RELEASE_VERSION` is omitted or empty, the command prompts for a release version on stdin. Press Enter to use the current version without `-dev`. Set `RELEASE_VERSION` explicitly to skip the prompt in unattended runs; closed stdin aborts the release. `NEXT_VERSION` defaults to the next patch version with `-dev`. Release versions must use stable `X.Y.Z` syntax, and the next development version must be greater than the release. The command rejects dirty checkouts, detached HEADs, existing release tags/releases, and branches behind or diverged from the remote. Test or preflight failures stop before changing `VERSION`; later failures keep completed commits, tags, and pushes for inspection. Resolve the failed step before continuing manually; rerunning `make release` is not a resume operation and will reject an existing tag. If only the final development push failed, push the current branch after resolving the failure. If GitHub Actions fails, fix the build or publishing problem and rerun the failed workflow jobs; the draft remains unpublished until assets are ready.

Pushing the tag triggers the release workflow. It verifies that both executable versions match the tag before publishing the versioned Docker image and `latest`. After Docker publishing succeeds, it packages and verifies `php-compat-check-<version>.tar.gz` and `php-compat-check-latest.tar.gz`, then publishes both with `SHA256SUMS` to a GitHub Release with generated release notes. Each archive extracts into a directory matching its filename without `.tar.gz` and includes `bin/php-compat-check`, `share/php-compat-check/{VERSION,HELP}`, `README.md`, and `LICENSE`. Both contain the actual release version in `VERSION`. Tags with a leading `v` are also accepted; prerelease tags create GitHub prereleases and do not replace the stable release selected by GitHub's `/releases/latest/download/` links. Rerunning the workflow uploads replacement assets to an existing release.

Manual tag pushes remain supported; the workflow creates a draft release itself if one does not exist. When releasing manually, also commit and push the next development version after tagging.

## Requirements

- Docker
