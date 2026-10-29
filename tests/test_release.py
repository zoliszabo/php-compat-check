"""Release orchestration using real temporary Git repositories and a stubbed gh."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")
STUB = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['RELEASE_TEST_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
if name == 'make':
    assert args == ['test'], args
    sys.exit(int(os.environ.get('RELEASE_TEST_TESTS_FAIL', '0')))
if args[:2] == ['auth', 'status']:
    sys.exit(int(os.environ.get('RELEASE_TEST_AUTH_FAIL', '0')))
if args[:2] == ['repo', 'view']:
    print('example/php-compat-check')
    sys.exit(0)
state_path = pathlib.Path(os.environ['RELEASE_TEST_STATE'])
state = json.loads(state_path.read_text())
operation, tag = args[1:3]
if operation == 'view':
    if tag not in state:
        sys.exit(1)
    if '--json' in args:
        print(str(state[tag]['draft']).lower())
elif operation == 'create':
    if tag in state or os.environ.get('RELEASE_TEST_CREATE_FAIL') == '1':
        sys.exit(1)
    commit = subprocess.check_output(['git', '--git-dir', os.environ['RELEASE_TEST_REMOTE'],
                                      'rev-parse', tag + '^{commit}'], text=True).strip()
    version = subprocess.check_output(['git', '--git-dir', os.environ['RELEASE_TEST_REMOTE'],
                                       'show', commit + ':VERSION'], text=True).strip()
    assert version == tag.lstrip('v'), (version, tag)
    state[tag] = {'draft': '--draft' in args, 'prerelease': '--prerelease' in args}
elif operation == 'upload':
    assert tag in state
    assert any(arg.endswith('.tar.gz') for arg in args), args
    if os.environ.get('RELEASE_TEST_UPLOAD_FAIL') == '1':
        sys.exit(1)
elif operation == 'edit':
    assert '--draft=false' in args
    state[tag]['draft'] = False
else:
    raise AssertionError(args)
state_path.write_text(json.dumps(state))
if operation == 'create' and os.environ.get('RELEASE_TEST_CREATE_RACE') == '1':
    sys.exit(1)
'''


class ReleaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="php-compat-check release ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "checkout"
        self.remote = self.base / "remote.git"
        self.repo.mkdir()
        self.git("init", "--bare", "-q", "--initial-branch=main", str(self.remote))
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        for name in ("Makefile", "scripts/release.sh", "bin/php-compat-check",
                     "docker/bin/php-compat-check", "HELP"):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (self.repo / "VERSION").write_text("3.2.1-dev\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Initial development version")
        self.initial = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-qu", "origin", "main")
        stubs = self.base / "stubs"
        stubs.mkdir()
        for name in ("gh", "make"):
            script = stubs / name
            script.write_text(STUB)
            script.chmod(0o755)
        self.log = self.base / "commands.jsonl"
        self.state = self.base / "releases.json"
        self.state.write_text("{}")
        self.env = dict(os.environ, PATH=str(stubs) + os.pathsep + os.environ["PATH"],
                        RELEASE_VERSION="", NEXT_VERSION="", RELEASE_REMOTE="origin",
                        RELEASE_TEST_REMOTE=str(self.remote), RELEASE_TEST_LOG=str(self.log),
                        RELEASE_TEST_STATE=str(self.state))
        for name in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS"):
            self.env.pop(name, None)

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def release(self, success=True, make_args=None, stdin="\n", **env):
        command = ["bash", "scripts/release.sh"] if make_args is None else [MAKE, "release", *make_args]
        result = subprocess.run(command, cwd=self.repo, env=dict(self.env, **env),
                                input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_unchanged(self):
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial)
        self.assertEqual((self.repo / "VERSION").read_text(), "3.2.1-dev\n")
        self.assertEqual(self.git("tag"), "")


class ReleaseTest(ReleaseFixture):
    def test_default_cycle_preserves_release_tag_and_pushes_development_commit(self):
        result = self.release(make_args=[])
        self.assertIn("Release version [3.2.1]: ", result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("cat-file", "-t", "3.2.1"), "tag")
        self.assertEqual(self.git("show", "3.2.1:VERSION"), "3.2.1")
        self.assertEqual(self.git("show", "HEAD:VERSION"), "3.2.2-dev")
        self.assertEqual(self.git("rev-parse", "3.2.1^{commit}"), self.git("rev-parse", "HEAD^"))
        self.assertEqual(self.git("rev-parse", "origin/main"), self.git("rev-parse", "HEAD"))
        self.assertEqual(json.loads(self.state.read_text())["3.2.1"], {"draft": True, "prerelease": False})
        events = self.events()
        self.assertLess(events.index(["make", "test"]), next(i for i, event in enumerate(events) if event[:3] == ["gh", "release", "create"]))
        for event in events:
            if event[:2] == ["gh", "release"]:
                self.assertIn("--repo", event)
                self.assertIn("example/php-compat-check", event)

    def test_make_passes_version_and_remote_overrides(self):
        self.git("remote", "rename", "origin", "upstream")
        result = self.release(stdin="", make_args=["RELEASE_VERSION=4.0.0", "NEXT_VERSION=4.1.0-dev", "RELEASE_REMOTE=upstream"])
        self.assertNotIn("Release version [", result.stderr)
        self.assertEqual(self.git("show", "4.0.0:VERSION"), "4.0.0")
        self.assertEqual(self.git("show", "HEAD:VERSION"), "4.1.0-dev")
        self.assertEqual(self.git("rev-parse", "upstream/main"), self.git("rev-parse", "HEAD"))

    def test_prompt_accepts_release_version_and_derives_next_version(self):
        result = self.release(make_args=[], stdin="4.0.0\n")
        self.assertIn("Release version [3.2.1]: ", result.stderr)
        self.assertEqual(self.git("show", "4.0.0:VERSION"), "4.0.0")
        self.assertEqual(self.git("show", "HEAD:VERSION"), "4.0.1-dev")

    def test_prompt_rejects_invalid_or_lower_versions_before_changes(self):
        for version in ("v3.2.1", "3.2.0", "3.02.1", "3.2.1-rc.1"):
            with self.subTest(version=version):
                self.release(success=False, stdin=version + "\n")
                self.assert_unchanged()
        self.assertNotIn(["make", "test"], self.events())

    def test_closed_stdin_aborts_before_changes(self):
        result = self.release(success=False, stdin="")
        self.assertIn("Unable to read a release version from stdin", result.stderr)
        self.assert_unchanged()
        self.assertNotIn(["make", "test"], self.events())

    def test_follow_tags_configuration_does_not_push_unrelated_tags(self):
        self.git("config", "push.followTags", "true")
        self.git("tag", "-a", "old-local-tag", "-m", "Keep this tag local")
        self.release()
        self.assertNotIn("old-local-tag", self.git("ls-remote", "--tags", "origin"))

    def test_dirty_worktree_stops_before_tests_or_changes(self):
        (self.repo / "untracked").write_text("work in progress")
        self.release(success=False)
        self.assert_unchanged()
        self.assertEqual(self.events(), [])

    def test_detached_head_is_rejected(self):
        self.git("checkout", "--detach", "-q")
        self.release(success=False)
        self.assert_unchanged()

    def test_invalid_versions_are_rejected(self):
        for env in ({"RELEASE_VERSION": "v3.2.1"}, {"RELEASE_VERSION": "3.2.0"},
                    {"RELEASE_VERSION": "3.02.1"}, {"RELEASE_VERSION": "3.2.1-rc.1"},
                    {"NEXT_VERSION": "3.3.0"}, {"NEXT_VERSION": "3.2.1-dev"}):
            with self.subTest(env=env):
                self.release(success=False, **env)
                self.assert_unchanged()

    def test_existing_local_or_remote_tag_is_rejected(self):
        self.git("tag", "v3.2.1")
        self.release(success=False)
        self.git("push", "-q", "origin", "refs/tags/v3.2.1")
        self.git("tag", "-d", "v3.2.1")
        self.release(success=False)
        self.assert_unchanged()
        self.assertNotIn(["make", "test"], self.events())

    def test_existing_release_is_rejected(self):
        self.state.write_text(json.dumps({"3.2.1": {"draft": True}}))
        self.release(success=False)
        self.assert_unchanged()

    def test_branch_behind_remote_is_rejected(self):
        other = self.base / "other"
        self.git("clone", "-q", str(self.remote), str(other))
        (other / "new-file").write_text("remote change")
        subprocess.run(["git", "-C", str(other), "add", "."], check=True)
        subprocess.run(["git", "-C", str(other), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "Remote change"], check=True)
        subprocess.run(["git", "-C", str(other), "push", "-q"], check=True)
        self.release(success=False)
        self.assert_unchanged()

    def test_authentication_and_test_failures_leave_version_unchanged(self):
        for env in ({"RELEASE_TEST_AUTH_FAIL": "1"}, {"RELEASE_TEST_TESTS_FAIL": "1"}):
            with self.subTest(env=env):
                self.release(success=False, **env)
                self.assert_unchanged()

    def test_atomic_push_failure_preserves_local_release_without_pushing_any_refs(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = self.release(success=False)
        self.assertIn("pushing the release commit and tag", result.stderr)
        self.assertEqual(self.git("show", "3.2.1:VERSION"), "3.2.1")
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", "main"), self.initial)
        self.assertEqual(self.git("ls-remote", "--tags", "origin"), "")
        self.assertEqual(json.loads(self.state.read_text()), {})

    def test_release_creation_failure_stops_before_development_commit(self):
        self.release(success=False, RELEASE_TEST_CREATE_FAIL="1")
        self.assertEqual(self.git("show", "HEAD:VERSION"), "3.2.1")
        self.assertEqual(self.git("rev-parse", "origin/main"), self.git("rev-parse", "3.2.1^{commit}"))

    def test_concurrent_workflow_release_creation_is_accepted(self):
        self.release(RELEASE_TEST_CREATE_RACE="1")
        self.assertEqual(self.git("show", "HEAD:VERSION"), "3.2.2-dev")

    def test_final_push_failure_keeps_development_commit_for_retry(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text('''#!/bin/sh
while read old new ref; do
  case "$(git show "$new:VERSION")" in *-dev) exit 1;; esac
done
''')
        hook.chmod(0o755)
        self.release(success=False)
        self.assertEqual(self.git("show", "HEAD:VERSION"), "3.2.2-dev")
        self.assertEqual(self.git("show", "origin/main:VERSION"), "3.2.1")


class PublishReleaseTest(ReleaseFixture):
    def setUp(self):
        super().setUp()
        self.release()
        (self.repo / "dist").mkdir()
        for name in ("php-compat-check-3.2.1.tar.gz", "php-compat-check-latest.tar.gz", "SHA256SUMS"):
            (self.repo / "dist" / name).write_text("test asset")
        workflow = (ROOT / ".github/workflows/publish-to-docker-hub.yml").read_text()
        block = workflow.split("      - name: Publish GitHub Release\n", 1)[1]
        self.publish_script = textwrap.dedent(block.split("        run: |\n", 1)[1])
        self.log.write_text("")

    def publish(self, success=True, tag="3.2.1", **env):
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", self.publish_script],
                                cwd=self.repo, env=dict(self.env, GITHUB_REF_NAME=tag, **env),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_draft_is_published_only_after_assets_upload(self):
        self.publish()
        events = self.events()
        upload = next(i for i, event in enumerate(events) if event[:3] == ["gh", "release", "upload"])
        edit = next(i for i, event in enumerate(events) if event[:3] == ["gh", "release", "edit"])
        self.assertLess(upload, edit)
        self.assertFalse(json.loads(self.state.read_text())["3.2.1"]["draft"])

    def test_manual_tag_creates_and_publishes_its_own_draft(self):
        self.state.write_text("{}")
        self.publish()
        self.assertFalse(json.loads(self.state.read_text())["3.2.1"]["draft"])

    def test_upload_failure_leaves_release_as_draft(self):
        self.publish(success=False, RELEASE_TEST_UPLOAD_FAIL="1")
        self.assertTrue(json.loads(self.state.read_text())["3.2.1"]["draft"])

    def test_published_release_rerun_does_not_publish_again(self):
        self.state.write_text(json.dumps({"3.2.1": {"draft": False}}))
        self.publish()
        self.assertFalse(any(event[:3] == ["gh", "release", "edit"] for event in self.events()))

    def test_draft_creation_race_is_accepted(self):
        self.state.write_text("{}")
        self.publish(RELEASE_TEST_CREATE_RACE="1")
        self.assertFalse(json.loads(self.state.read_text())["3.2.1"]["draft"])

    def test_manual_prerelease_tag_remains_a_prerelease_when_published(self):
        (self.repo / "VERSION").write_text("3.3.0-rc.1\n")
        self.git("add", "VERSION")
        self.git("commit", "-qm", "Prepare prerelease")
        self.git("tag", "-a", "v3.3.0-rc.1", "-m", "Prerelease")
        self.git("push", "-q", "origin", "refs/tags/v3.3.0-rc.1")
        self.publish(tag="v3.3.0-rc.1")
        self.assertEqual(json.loads(self.state.read_text())["v3.3.0-rc.1"],
                         {"draft": False, "prerelease": True})
