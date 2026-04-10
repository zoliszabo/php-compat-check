# php-compat-check

A CLI tool for detecting the minimum and target PHP version compatibility of Composer-based projects.

It uses PHPCompatibility (PHP_CodeSniffer) and can optionally install dependencies to provide more realistic results.

## Features
- Check compatibility against a specific PHP version
- Automatically detect the minimum supported PHP version
- Optional dependency-aware analysis using Composer
- Runs in a Docker container for consistent results
- Simple CLI interface

## Usage

### Basic compatibility check

```bash
php-compat-check <repo> <php-version>
```

Example:

```bash
php-compat-check https://github.com/vendor/package 8.1
```

### Find minimum supported PHP version

```bash
php-compat-check <repo> <php-version> --min-php-version
```

### Optionally define a lower bound:

```bash
php-compat-check <repo> <php-version> --min-php-version --from-php-version=7.4
```

### Include dependencies in analysis

```bash
php-compat-check <repo> <php-version> --with-deps
```

## Installation

### Option 1: Use Docker directly

```bash
docker run --rm zoliszabo/php-compat-check <repo> <php-version>
```

### Option 2: Wrapper script (recommended)

Install the wrapper:

```bash
cp bin/php-compat-check /usr/local/bin/php-compat-check
chmod +x /usr/local/bin/php-compat-check
```

Then use it like a native CLI:

```bash
php-compat-check <repo> <php-version>
```

## How it works
1. Clones the target repository
1. Runs PHPCompatibility via PHP_CodeSniffer
1. Optionally installs dependencies using Composer with a simulated PHP platform version
1. Iterates across PHP versions when using --min-php-version

## Requirements
- Docker
