# php-compat-check

A CLI tool for detecting the minimum and target PHP version compatibility of Composer-based projects.

It uses PHPCompatibility (PHP_CodeSniffer) and can optionally install dependencies to provide more realistic results.

## Features

- Check compatibility against a specific PHP version
- Automatically detect the minimum supported PHP version
- Optional dependency-aware analysis using Composer
- Accepts a Git repository URL or a Packagist package name (`vendor/package[:version]`)
- Automatically resolves scan directories from `composer.json` autoload configuration
- Auto-detects polyfill libraries and suppresses false positives accordingly
- Runs in a Docker container for consistent results
- Simple CLI interface

## Usage

### Basic compatibility check

```bash
php-compat-check <repo> <php-version>
```

The `<repo>` argument accepts a Git URL or a Packagist package name, with an optional version:

```bash
php-compat-check https://github.com/vendor/package 8.1
php-compat-check vendor/package 8.1
php-compat-check vendor/package:^6.0 8.1
php-compat-check vendor/package:dev-main 8.1
php-compat-check https://github.com/vendor/package 8.1 --version=v6.0.2
```

### Find minimum supported PHP version

```bash
php-compat-check <repo> --min-php-version
```

Scans versions that satisfy the `require.php` constraint declared in `composer.json`. Defaults to scanning from `5.6` if no constraint is found.

If the found minimum equals the constraint's own minimum (or the explicitly provided `--from-php-version`), a note will suggest retrying with `--ignore-composer-php-version` to scan without filtering.

### Scanning dependencies

```bash
php-compat-check <repo> <php-version> --check-deps
```

Installs non-dev Composer dependencies and includes them in the scan. Accepts an optional mode:

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

In shallow mode, packages that declare an incompatible `require.php` are always excluded from the scan (they wouldn't be installed by Composer either). Packages with no `require.php` are always scanned.

### Options

| Flag | Description |
|------|-------------|
| `--check-deps[=shallow\|full]` | Install and scan Composer dependencies (non-dev only). Defaults to `shallow` when no value is given. |
| `--min-php-version` | Find the minimum compatible PHP version |
| `--from-php-version=<version>` | Override the lower bound when using `--min-php-version` |
| `--ignore-composer-php-version` | Ignore `require.php` from `composer.json` when determining the scan range, filtering versions, or setting the platform version |
| `--scan-dirs=<dirs>` | Comma-separated list of directories/files to scan (default: resolved from `composer.json` autoload) |
| `--show-deps` | Print a table of installed dependencies and their scan status (`checked`, `trusted`, or `ignored`) |
| `--show-warnings` | Display PHPCompatibility warnings in addition to errors (warnings are hidden by default) |
| `--version=<ref>` | Check out a specific version for URL repos (tag, branch, or `dev-main` style) |

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

1. Resolves a Packagist package name to its repository URL if needed
2. Clones the repository
3. Detects scan directories from `composer.json` autoload (`psr-4`, `psr-0`, `classmap`, `files`); falls back to `.`
4. When `--check-deps` is set: strips `require-dev` and `autoload-dev`, simulates the target PHP platform version, and installs non-dev dependencies
5. Validates the requested version (or scanned range) against `composer.json`'s `require.php` constraint using Composer's semver library, unless `--ignore-composer-php-version` is set
6. Auto-detects polyfill libraries and applies the appropriate PHPCompatibility companion standards to suppress false positives:
   - Without `--check-deps`: reads `require` from `composer.json`
   - With `--check-deps`: reads `composer.lock` after install to catch transitive polyfill dependencies
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
cp bin/php-compat-check /usr/local/bin/php-compat-check
chmod +x /usr/local/bin/php-compat-check
```

### Option 3: Use Docker directly

```bash
docker run --rm zoliszabo/php-compat-check <repo> <php-version>
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
```

`make run` always rebuilds the image before running, so you never test stale code.

## Requirements

- Docker
