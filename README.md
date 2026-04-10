# php-compat-check

A CLI tool for detecting the minimum and target PHP version compatibility of Composer-based projects.

It uses PHPCompatibility (PHP_CodeSniffer) and can optionally install dependencies to provide more realistic results.

## Features

- Check compatibility against a specific PHP version
- Automatically detect the minimum supported PHP version
- Optional dependency-aware analysis using Composer
- Accepts a Git repository URL or a Packagist package name (`vendor/package`)
- Automatically resolves scan directories from `composer.json` autoload configuration
- Runs in a Docker container for consistent results
- Simple CLI interface

## Usage

### Basic compatibility check

```bash
php-compat-check <repo> <php-version>
```

The `<repo>` argument accepts either a Git URL or a Packagist package name:

```bash
php-compat-check https://github.com/vendor/package 8.1
php-compat-check vendor/package 8.1
```

### Find minimum supported PHP version

```bash
php-compat-check <repo> --min-php-version
```

Scans versions that satisfy the `require.php` constraint declared in `composer.json`. Defaults to scanning from `5.6` if no constraint is found.

If the found minimum equals the constraint's own minimum (or the explicitly provided `--from-php-version`), a note will suggest retrying with `--ignore-composer-php-version` to scan without filtering.

### Options

| Flag | Description |
|------|-------------|
| `--with-deps` | Install and scan Composer dependencies (non-dev only) |
| `--min-php-version` | Find the minimum compatible PHP version |
| `--from-php-version=<version>` | Override the lower bound when using `--min-php-version` |
| `--ignore-composer-php-version` | Ignore `require.php` from `composer.json` when determining the scan range, filtering versions, or setting the platform version |
| `--scan-dirs=<dirs>` | Comma-separated list of directories/files to scan (default: resolved from `composer.json` autoload) |

### Examples

```bash
# Check against a specific version
php-compat-check sebastian/diff 8.1

# Find minimum supported version
php-compat-check sebastian/diff --min-php-version

# Find minimum, starting from a specific version
php-compat-check sebastian/diff --min-php-version --from-php-version=7.4

# Include dependencies in analysis
php-compat-check sebastian/diff 8.1 --with-deps

# Scan specific directories
php-compat-check sebastian/diff 8.1 --scan-dirs=src,lib
```

## How it works

1. Resolves a Packagist package name to its repository URL if needed
2. Clones the repository
3. Detects scan directories from `composer.json` autoload (`psr-4`, `psr-0`, `classmap`, `files`); falls back to `.`
4. When `--with-deps` is set: strips `require-dev` and `autoload-dev`, simulates the target PHP platform version, and installs non-dev dependencies
5. Validates the requested version (or scanned range) against `composer.json`'s `require.php` constraint using Composer's semver library, unless `--ignore-composer-php-version` is set
6. Runs PHPCompatibility via PHP_CodeSniffer against the resolved directories, ignoring `vendor/composer/` and `vendor/autoload.php`

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
make run ARGS="sebastian/diff 8.1 --with-deps"
```

`make run` always rebuilds the image before running, so you never test stale code.

## Requirements

- Docker
