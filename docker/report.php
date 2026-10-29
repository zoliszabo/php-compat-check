<?php

// JSON reporting for the container's checker; project code is never loaded.
function encode($value): string
{
    return json_encode($value, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE | JSON_THROW_ON_ERROR);
}

function readRecords(string $path): array
{
    $lines = is_file($path) ? file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) : [];
    return array_map(static fn ($line) => json_decode($line, true, 512, JSON_THROW_ON_ERROR), $lines);
}

[$script, $action, $directory] = $argv;
if ($action === 'diagnostic') {
    file_put_contents($directory . '/diagnostics.jsonl', encode([
        'level' => $argv[3], 'message' => $argv[4],
    ]) . "\n", FILE_APPEND);
    exit;
}

if ($action === 'result') {
    [, , , $version, $status, $reason, $project, $dependencyMode, $sourceType, $composerHome] = $argv;
    $report = json_decode(file_get_contents($directory . '/current.json'), true, 512, JSON_THROW_ON_ERROR);
    $findings = [];
    foreach ($report['files'] ?? [] as $path => $file) {
        if (str_starts_with($path, $project . '/')) {
            $path = substr($path, strlen($project) + 1);
        }
        foreach ($file['messages'] ?? [] as $message) {
            $findings[] = [
                'file' => $path, 'line' => $message['line'], 'column' => $message['column'],
                'type' => strtolower($message['type']), 'message' => $message['message'],
                'source' => $message['source'], 'severity' => $message['severity'],
            ];
        }
    }
    $dependencies = [];
    if ($dependencyMode !== '' && $status !== 'excluded') {
        require $composerHome . '/vendor/autoload.php';
        foreach (json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR) as $package) {
            $constraint = $package['require']['php'] ?? '';
            $dependencyStatus = isset($report['totals']) ? 'checked' : 'not_checked';
            if ($status === 'error' || in_array($reason, ['composer_constraint', 'dependency_resolution'], true)) {
                $dependencyStatus = 'not_checked';
            } elseif ($constraint !== '' && !Composer\Semver\Semver::satisfies($version, $constraint)) {
                $dependencyStatus = $sourceType === 'local' ? 'incompatible' : 'ignored';
            } elseif (isset($report['totals']) && $constraint !== '' && $dependencyMode === 'shallow') {
                $dependencyStatus = 'trusted';
            }
            $dependencies[] = [
                'name' => $package['name'], 'version' => $package['version'],
                'php_constraint' => $constraint ?: null, 'status' => $dependencyStatus,
            ];
        }
    }
    file_put_contents($directory . '/results.jsonl', encode([
        'php_version' => $version, 'status' => $status, 'reason' => $reason ?: null,
        'errors' => $report['totals']['errors'] ?? null,
        'warnings' => $report['totals']['warnings'] ?? null,
        'findings' => $findings, 'dependencies' => $dependencies,
    ]) . "\n", FILE_APPEND);
    exit;
}

if ($action !== 'finish') {
    throw new InvalidArgumentException('Unknown report action');
}
[, , , $exitCode, $toolVersion, $mode, $input, $sourceType, $sourceVersion, $commit,
    $from, $to, $constraint, $ignoreConstraint, $dependencyMode, $selectedVersion] = $argv;
$knownVersions = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$results = readRecords($directory . '/results.jsonl');
$diagnostics = readRecords($directory . '/diagnostics.jsonl');
if ((int) $exitCode === 2 && $diagnostics === []) {
    $diagnostics[] = ['level' => 'error', 'message' => 'Analysis could not be completed; see stderr.'];
}
$upperIncompatibility = false;
if ($mode === 'max' && $selectedVersion !== '') {
    foreach ($results as $result) {
        if ($result['status'] === 'incompatible' && version_compare($result['php_version'], $selectedVersion, '>')) {
            $upperIncompatibility = true;
        }
    }
}
echo encode([
    'schema_version' => 1, 'tool_version' => $toolVersion, 'mode' => $mode,
    'source' => ['input' => $input ?: null, 'type' => $sourceType ?: null,
        'version' => $sourceVersion ?: null, 'commit' => $commit ?: null],
    'scan' => ['from' => $from ?: null, 'to' => $to ?: null,
        'known_php_versions' => $knownVersions, 'composer_constraint' => $constraint ?: null,
        'constraint_ignored' => $ignoreConstraint === '1', 'dependency_mode' => $dependencyMode ?: null,
        'analysis' => 'static', 'coverage_complete' => false],
    'results' => $results,
    'summary' => ['status' => ['compatible', 'incompatible', 'error'][(int) $exitCode],
        'version' => (int) $exitCode === 0 && $selectedVersion !== '' ? $selectedVersion : null,
        'upper_incompatibility_found' => $mode === 'max' && (int) $exitCode === 0 ? $upperIncompatibility : null],
    'diagnostics' => $diagnostics, 'exit_code' => (int) $exitCode,
]) . "\n";
