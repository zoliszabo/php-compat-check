# Compatibility reporting tasks

Work through these in order, verifying each item before starting the next.

1. [x] Add `--max-php-version` and `--to-php-version`, with shared scan bounds,
   Composer constraint handling, dependency checks, and bounded result wording.
2. [x] Add `--matrix` to report every known version within the requested bounds,
   including compatibility gaps and versions excluded by Composer constraints.
3. [x] Make exit codes consistent for local and remote sources and distinguish
   incompatibility from invalid input or failed analysis for CI.
4. [x] Add `--format=json` for checks, minimum/maximum searches, and matrices,
   including structured results, diagnostics, and coverage metadata.

Each item includes CLI help, README updates, regression tests, and relevant
Docker/PHPCompatibility fixture checks. Commits and releases are separate steps.

Verification completed: regression tests, focused JSON regressions, all 20 real
Docker/PHPCompatibility fixture tests, Bash/PHP syntax checks, and diff checks.
