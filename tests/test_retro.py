"""Tests for the retro: bin/retro-intake, bin/retro-guard, bin/pre-push, and bin/state put-report.

Run from the repo root: python3 -m unittest discover -s tests
Each test builds its own state branch in a temporary directory, and GitHub calls are stubbed.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, 'bin')
sys.path.insert(0, BIN)
sys.dont_write_bytecode = True


def load(name, file):
	loader = importlib.machinery.SourceFileLoader(name, os.path.join(BIN, file))
	module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
	loader.exec_module(module)
	return module


def ts(s):
	return datetime.fromisoformat(s.replace('Z', '+00:00'))


def git(cwd, *args, date=None, check=True):
	env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
	if date:
		env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
	return subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True, env=env, check=check).stdout


class StateRepo:
	"""A claude/state checkout with a bare origin, written one commit per file version."""

	def __init__(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.origin = os.path.join(self.tmp.name, 'origin.git')
		self.dir = os.path.join(self.tmp.name, 'state')
		subprocess.run(['git', 'init', '-q', '--bare', self.origin], check=True)
		subprocess.run(['git', 'init', '-q', '-b', 'claude/state', self.dir], check=True)
		git(self.dir, 'remote', 'add', 'origin', self.origin)
		self.write('README.md', 'state\n', '2026-11-01T00:00:00Z')

	def write(self, path, content, date):
		full = os.path.join(self.dir, path)
		os.makedirs(os.path.dirname(full), exist_ok=True)
		with open(full, 'w') as f:
			f.write(content if isinstance(content, str) else json.dumps(content))
		git(self.dir, 'add', '-A')
		git(self.dir, 'commit', '-q', '-m', f'Update {path}.', date=date)
		git(self.dir, 'push', '-q', 'origin', 'claude/state')

	def put(self, path, data, updated=None):
		"""Write data as bin/state would, at its updated time (or now, with no updated field)."""
		if updated:
			data = {**data, 'updated': updated}
		self.write(path, data, updated or '2026-11-23T12:00:00Z')

	def cleanup(self):
		self.tmp.cleanup()


class RetroIntakeTest(unittest.TestCase):
	SINCE = ts('2026-11-20T00:00:00Z')
	NOW = ts('2026-11-27T00:00:00Z')

	def setUp(self):
		self.state = StateRepo()
		self.ri = load('retro_intake', 'retro-intake')
		self.ri.STATE_DIR = self.state.dir
		self.ri.OWNER, self.ri.REPO = 'owner', 'wporg-bug-pipeline'
		self.ri.unavailable.clear()
		self.ri.closed_event.cache_clear()
		self.events = {}
		self.lists = {}
		self.objects = {}
		self.ri.existing_pr.gh_list = lambda path: self.lists.get(path.split('?')[0], self.events.get(path.split('?')[0], []))
		self.ri.existing_pr.gh = lambda path: self.objects.get(path.split('?')[0], [])
		self.maintainers = {}
		self.ri.maintainer = lambda owner, repo, login: self.maintainers.get(login, False)

	def tearDown(self):
		self.state.cleanup()

	def signals(self):
		return self.ri.collect(self.SINCE, self.NOW)

	def kinds(self, signals=None):
		return [(s['signal'], s.get('key')) for s in (self.signals() if signals is None else signals)]

	def test_failed_claim_links_item_and_state_commit(self):
		self.state.put('items/trac-1/claim.json', {'status': 'working', 'repo': 'r'}, '2026-11-21T10:00:00Z')
		self.state.put('items/trac-1/claim.json', {'status': 'failed', 'repo': 'r', 'reason': 'tests  would\nnot run'}, '2026-11-21T11:00:00Z')
		[s] = self.signals()
		self.assertEqual(s['signal'], 'failed-claim')
		self.assertEqual(s['url'], 'https://meta.trac.wordpress.org/ticket/1')
		self.assertEqual(s['detail'], 'tests would not run')
		self.assertRegex(s['state'], r'^https://github\.com/owner/wporg-bug-pipeline/commit/[0-9a-f]{40}$')

	def test_released_closed_claim_counts_as_failed(self):
		self.state.put('items/gh-r-2/claim.json', {'status': 'closed', 'repo': 'r', 'reason': 'closed'}, '2026-11-21T11:00:00Z')
		self.assertEqual(self.kinds(), [('failed-claim', 'gh-r-2')])

	def test_failure_before_the_window_is_left_out(self):
		self.state.put('items/trac-1/claim.json', {'status': 'failed', 'reason': 'old'}, '2026-11-19T23:00:00Z')
		self.assertEqual(self.kinds(), [])

	def test_stale_claim_when_nothing_follows_within_the_ttl(self):
		self.state.put('items/trac-3/claim.json', {'status': 'working'}, '2026-11-22T10:00:00Z')
		self.state.put('items/trac-3/claim.json', {'status': 'working'}, '2026-11-22T16:00:00Z')
		self.state.put('items/trac-3/claim.json', {'status': 'pr-open', 'pr': 'https://github.com/WordPress/r/pull/9'}, '2026-11-22T17:00:00Z')
		self.objects['repos/WordPress/r/pulls/9'] = {'user': {'login': 'pipeline'}}
		self.assertEqual(self.kinds(), [('stale-claim', 'trac-3')])

	def test_stale_claim_counts_in_the_window_it_expires_in(self):
		# Claimed two hours before the window; it expired inside it.
		self.state.put('items/trac-4/claim.json', {'status': 'working'}, '2026-11-19T22:00:00Z')
		self.assertEqual(self.kinds(), [('stale-claim', 'trac-4')])

	def test_stale_claim_that_expired_before_the_window_is_left_out(self):
		self.state.put('items/trac-5/claim.json', {'status': 'working'}, '2026-11-19T10:00:00Z')
		self.state.put('items/trac-5/claim.json', {'status': 'failed', 'reason': 'x'}, '2026-11-19T19:00:00Z')
		self.assertEqual(self.kinds(), [])

	def test_working_claim_still_inside_its_ttl_is_not_stale(self):
		self.state.put('items/trac-6/claim.json', {'status': 'working'}, '2026-11-26T22:00:00Z')
		self.assertEqual(self.kinds(), [])

	def test_closed_unmerged_pr(self):
		pr = 'https://github.com/WordPress/r/pull/7'
		self.state.put('items/gh-r-7/claim.json', {'status': 'pr-open', 'pr': pr}, '2026-11-21T10:00:00Z')
		self.state.put('items/gh-r-7/claim.json', {'status': 'done', 'outcome': 'closed', 'pr': pr}, '2026-11-22T10:00:00Z')
		self.events['repos/WordPress/r/issues/7/events'] = [{'event': 'closed', 'actor': {'login': 'm'}, 'commit_id': None}]
		self.objects['repos/WordPress/r/pulls/7'] = {'user': {'login': 'pipeline'}}
		[s] = self.signals()
		self.assertEqual((s['signal'], s['url'], s['by']), ('closed-unmerged', pr, 'm'))

	def test_pr_closed_by_a_commit_is_not_closed_unmerged(self):
		pr = 'https://github.com/WordPress/wordpress.org/pull/8'
		self.state.put('items/trac-8/claim.json', {'status': 'done', 'outcome': 'closed', 'pr': pr}, '2026-11-22T10:00:00Z')
		self.events['repos/WordPress/wordpress.org/issues/8/events'] = [{'event': 'closed', 'actor': {'login': 'm'}, 'commit_id': 'abc'}]
		self.objects['repos/WordPress/wordpress.org/pulls/8'] = {'user': {'login': 'pipeline'}}
		self.assertEqual(self.kinds(), [])

	def test_closed_claim_without_a_pr_does_not_crash(self):
		self.state.put('items/trac-9/claim.json', {'status': 'done', 'outcome': 'closed'}, '2026-11-22T10:00:00Z')
		self.assertEqual(self.kinds(), [])

	def test_version_without_updated_uses_its_commit_time(self):
		self.state.write('items/trac-10/claim.json', {'status': 'failed', 'reason': 'x'}, '2026-11-24T08:00:00Z')
		[s] = self.signals()
		self.assertEqual((s['signal'], s['when']), ('failed-claim', '2026-11-24T08:00:00Z'))

	def test_push_limit_only_when_reached(self):
		self.state.put('items/gh-r-11/claim.json', {'status': 'pr-open', 'pr': 'https://github.com/WordPress/r/pull/11'}, '2026-11-19T00:00:00Z')
		self.objects['repos/WordPress/r/pulls/11'] = {'user': {'login': 'pipeline'}}
		for pushes, when in ((2, '2026-11-21T00:00:00Z'), (3, '2026-11-22T00:00:00Z'), (3, '2026-11-23T00:00:00Z')):
			self.state.put('items/gh-r-11/shepherd.json', {'pushes': pushes}, when)
		self.assertEqual(self.kinds(), [('push-limit', 'gh-r-11')])

	def test_item_closed_needs_a_person_once_and_a_report_line_replaces_it(self):
		pr = 'https://github.com/WordPress/r/pull/12'
		self.state.put('items/gh-r-12/claim.json', {'status': 'pr-open', 'pr': pr}, '2026-11-19T00:00:00Z')
		self.objects['repos/WordPress/r/pulls/12'] = {'user': {'login': 'pipeline'}}
		self.state.put('items/gh-r-12/shepherd.json', {'pushes': 0, 'item_closed': True}, '2026-11-21T00:00:00Z')
		self.state.put('items/gh-r-12/shepherd.json', {'pushes': 0, 'item_closed': True}, '2026-11-22T00:00:00Z')
		[s] = self.signals()
		self.assertEqual((s['signal'], s['url']), ('needs-person', pr))
		self.assertIn('state', s)
		self.state.write('runs/shepherd/reports/20261122T010000Z.md',
			f'## Shepherd run\n- Needs a person:\n  - {pr}: closed as not planned\n  - https://github.com/WordPress/r/pull/13: needs a manual rebase\n',
			'2026-11-22T01:00:00Z')
		got = self.signals()
		self.assertEqual([(s['signal'], s['url']) for s in got], [('needs-person', pr), ('needs-person', 'https://github.com/WordPress/r/pull/13')])
		self.assertTrue(all('report' in s for s in got))

	def test_report_failed_lines_that_a_claim_covers_are_dropped(self):
		self.state.put('items/gh-r-14/claim.json', {'status': 'failed', 'reason': 'x'}, '2026-11-21T00:00:00Z')
		self.state.write('runs/r/reports/20261121T010000Z.md',
			'## r run\n- Failed: gh-r-14: tests would not run\n- Failed: gh-r-15: wp-env did not start\n- Needs a person: none\n',
			'2026-11-21T01:00:00Z')
		got = self.signals()
		self.assertEqual([s['signal'] for s in got], ['failed-claim', 'report-failed'])
		self.assertEqual(got[1]['url'], 'https://github.com/WordPress/r/issues/15')

	def test_reports_saved_before_the_window_are_left_out(self):
		self.state.write('runs/r/reports/20261119T010000Z.md', '## r run\n- Failed: gh-r-16: x\n', '2026-11-19T01:00:00Z')
		self.assertEqual(self.kinds(), [])

	def test_maintainer_comments_only(self):
		pr = 'https://github.com/WordPress/r/pull/20'
		self.state.put('items/gh-r-20/claim.json', {'status': 'pr-open', 'pr': pr}, '2026-11-19T00:00:00Z')
		self.objects['repos/WordPress/r/pulls/20'] = {'user': {'login': 'pipeline'}}
		new, old = '2026-11-22T00:00:00Z', '2026-11-19T00:00:00Z'
		self.lists['repos/WordPress/r/pulls/20/reviews'] = [
			{'user': {'login': 'm', 'type': 'User'}, 'state': 'APPROVED', 'body': '', 'submitted_at': new},
			{'user': {'login': 'm', 'type': 'User'}, 'state': 'CHANGES_REQUESTED', 'body': 'Use the helper.', 'submitted_at': new, 'html_url': f'{pr}#r1'},
		]
		self.lists['repos/WordPress/r/pulls/20/comments'] = [
			{'user': {'login': 'copilot', 'type': 'Bot'}, 'body': 'nit', 'created_at': new},
		]
		self.lists['repos/WordPress/r/issues/20/comments'] = [
			{'user': {'login': 'pipeline', 'type': 'User'}, 'body': 'Done in abc.', 'created_at': new},
			{'user': {'login': 'm', 'type': 'User'}, 'body': 'reply <!-- wporg-bug-pipeline -->', 'created_at': new},
			{'user': {'login': 'm', 'type': 'User'}, 'body': 'too old', 'created_at': old},
			{'user': {'login': 'passerby', 'type': 'User'}, 'body': '+1', 'created_at': new},
			{'user': {'login': 'maybe', 'type': 'User'}, 'body': 'Please move this.', 'created_at': new, 'html_url': f'{pr}#c2'},
		]
		self.maintainers = {'m': True, 'maybe': None}
		got = self.signals()
		self.assertEqual([(s['author'], s['kind'], s.get('maintainer')) for s in got], [('m', 'review', None), ('maybe', 'comment', 'unknown')])
		self.assertEqual(got[0]['state'], 'CHANGES_REQUESTED')

	def test_unreadable_pr_is_reported(self):
		self.state.put('items/gh-r-21/claim.json', {'status': 'pr-open', 'pr': 'https://github.com/WordPress/r/pull/21'}, '2026-11-19T00:00:00Z')
		self.ri.existing_pr.gh = lambda path: None
		self.assertEqual(self.signals(), [])
		self.assertIn('https://github.com/WordPress/r/pull/21', self.ri.unavailable)

	def test_own_lesson_pr_closed_without_merging(self):
		url = 'https://github.com/owner/wporg-bug-pipeline/pull/5'
		self.objects['repos/owner/wporg-bug-pipeline/pulls'] = [
			{'head': {'ref': 'claude/lesson-x'}, 'state': 'closed', 'merged_at': None, 'closed_at': '2026-11-22T00:00:00Z',
				'updated_at': '2026-11-22T00:00:00Z', 'html_url': url, 'title': 'Lessons: x'},
			{'head': {'ref': 'claude/some-session'}, 'state': 'closed', 'merged_at': None, 'closed_at': '2026-11-22T00:00:00Z',
				'updated_at': '2026-11-22T00:00:00Z', 'html_url': url + '0', 'title': 'Not the pipeline'},
		]
		self.objects['repos/owner/wporg-bug-pipeline/pulls/5'] = {'user': {'login': 'owner'}}
		self.events['repos/owner/wporg-bug-pipeline/issues/5/events'] = [{'event': 'closed', 'actor': {'login': 'owner'}}]
		self.assertEqual([(s['signal'], s['url']) for s in self.signals()], [('closed-unmerged', url)])


class RetroIntakeCliTest(unittest.TestCase):
	def setUp(self):
		self.state = StateRepo()
		self.env = {**os.environ, 'WPORG_STATE_DIR': self.state.dir, 'PYTHONDONTWRITEBYTECODE': '1',
			'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}

	def tearDown(self):
		self.state.cleanup()

	def run_intake(self, *args):
		return subprocess.run([os.path.join(BIN, 'retro-intake'), *args], capture_output=True, text=True, env=self.env)

	def last_run(self):
		git(self.state.dir, 'pull', '-q', 'origin', 'claude/state')
		with open(os.path.join(self.state.dir, 'runs/retro.json')) as f:
			return json.load(f)

	def test_bad_arguments_print_usage(self):
		for args in (['--since'], ['--bogus'], ['--since', 'x', 'y']):
			out = self.run_intake(*args)
			self.assertNotEqual(out.returncode, 0)
			self.assertIn('Usage', out.stderr)
			self.assertNotIn('Traceback', out.stderr)
		out = self.run_intake('--since', 'yesterday')
		self.assertIn('ISO 8601', out.stderr)
		self.assertNotIn('Traceback', out.stderr)

	def test_done_advances_a_complete_window(self):
		self.state.put('runs/retro.json', {'last_run': '2026-11-20T00:00:00Z', 'pending': '2026-11-21T00:00:00Z', 'complete': True}, '2026-11-21T00:00:00Z')
		out = self.run_intake('--done')
		self.assertEqual(out.returncode, 0, out.stderr)
		rec = self.last_run()
		self.assertEqual(rec['last_run'], '2026-11-21T00:00:00Z')
		self.assertNotIn('pending', rec)

	def test_done_keeps_the_window_after_a_partial_read(self):
		self.state.put('runs/retro.json', {'last_run': '2026-11-20T00:00:00Z', 'pending': '2026-11-21T00:00:00Z', 'complete': False}, '2026-11-21T00:00:00Z')
		out = self.run_intake('--done')
		self.assertEqual(out.returncode, 0, out.stderr)
		self.assertIn('reads this window again', out.stdout)
		self.assertEqual(self.last_run()['last_run'], '2026-11-20T00:00:00Z')

	def test_done_without_a_pending_window_fails(self):
		self.state.put('runs/retro.json', {'last_run': '2026-11-20T00:00:00Z'}, '2026-11-21T00:00:00Z')
		self.assertNotEqual(self.run_intake('--done').returncode, 0)


class RetroGuardTest(unittest.TestCase):
	OWNER = 'owner'
	CREATE = 'gh api -X POST repos/owner/wporg-bug-pipeline/pulls -f base=trunk -f head=claude/retro-2026-11-27 -f title="Retro: x" -F body=@/home/user/retro-pr.md'

	@classmethod
	def setUpClass(cls):
		cls.g = load('retro_guard', 'retro-guard')

	def denied(self, command):
		return self.g.check(command, self.OWNER) is not None

	def test_reads_pass(self):
		for c in ('gh api repos/WordPress/r/pulls/1/comments --jq ".[].body"',
				'gh api -X GET search/issues -f q=org:WordPress',
				"gh api 'repos/owner/wporg-bug-pipeline/pulls?state=all' | jq .",
				'curl -sSL -A "Mozilla/5.0" https://wordpress.org/',
				'git -C /home/user/retro push -u origin claude/retro-2026-11-27',
				'cat RETRO.md && grep -n x LESSONS.md'):
			self.assertFalse(self.denied(c), c)

	def test_the_retro_pr_passes(self):
		self.assertFalse(self.denied(self.CREATE))

	def test_writes_are_blocked(self):
		for c in ('gh api -X POST repos/WordPress/r/issues/1/comments -f body=hi',
				'gh api repos/WordPress/r/issues/1/comments -f body=hi',
				'gh api --method=PATCH repos/WordPress/r/pulls/1 -f state=closed',
				'gh api -XDELETE repos/owner/wporg-bug-pipeline/git/refs/heads/x',
				'gh api repos/WordPress/r/pulls --input pr.json',
				'gh pr comment 1 -b hi',
				'gh issue close 3',
				'bash -c "gh api -X POST repos/WordPress/r/issues/1/comments -f body=hi"',
				'echo $(gh api -X POST repos/WordPress/r/issues/1/comments -f body=hi)',
				'cd /tmp; gh api -X PUT repos/WordPress/r/pulls/1/merge',
				'curl -X POST https://api.github.com/repos/WordPress/r/issues/1/comments',
				'curl -d @x https://api.github.com/x',
				'curl -sXPOST https://api.github.com/x',
				'wget --post-data=x https://api.github.com/x',
				'git push --no-verify origin claude/retro-x',
				'git -c core.hooksPath=/dev/null push origin claude/x',
				'rm ~/.wporg-pipeline-retro',
				'cp /tmp/x /home/user/wporg-bug-pipeline/.git/hooks/pre-push'):
			self.assertTrue(self.denied(c), c)

	def test_the_pr_is_pinned_to_this_repo_trunk_and_body_file(self):
		for old, new in (('repos/owner/', 'repos/WordPress/'), ('base=trunk', 'base=main'), ('head=claude/retro-', 'head=claude/other-'),
				('body=@/home/user/retro-pr.md', 'body=@/root/.ssh/id_rsa'), ('-f title="Retro: x"', '-F title=@/etc/passwd')):
			self.assertTrue(self.denied(self.CREATE.replace(old, new)), new)

	def hook(self, event, marker):
		with tempfile.TemporaryDirectory() as home:
			if marker:
				open(os.path.join(home, '.wporg-pipeline-retro'), 'w').close()
			return subprocess.run([os.path.join(BIN, 'retro-guard')], input=json.dumps(event), capture_output=True, text=True,
				env={**os.environ, 'HOME': home, 'PYTHONDONTWRITEBYTECODE': '1'})

	def test_hook_is_inert_outside_a_retro_session(self):
		self.assertEqual(self.hook({'tool_name': 'Bash', 'tool_input': {'command': 'gh pr merge 1'}}, False).returncode, 0)

	def test_hook_blocks_in_a_retro_session(self):
		out = self.hook({'tool_name': 'Bash', 'tool_input': {'command': 'gh pr merge 1'}}, True)
		self.assertEqual(out.returncode, 2)
		self.assertIn('retro-guard:', out.stderr)
		write = {'tool_name': 'Write', 'tool_input': {'file_path': '/home/user/wporg-bug-pipeline/.git/hooks/pre-push'}}
		self.assertEqual(self.hook(write, True).returncode, 2)
		ok = {'tool_name': 'Edit', 'tool_input': {'file_path': '/home/user/retro/LESSONS.md'}}
		self.assertEqual(self.hook(ok, True).returncode, 0)


class PrePushTest(unittest.TestCase):
	PIPELINE = 'https://github.com/owner/wporg-bug-pipeline'

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.repo = os.path.join(self.tmp.name, 'repo')
		self.home = os.path.join(self.tmp.name, 'home')
		os.makedirs(self.home)
		subprocess.run(['git', 'init', '-q', '-b', 'trunk', self.repo], check=True)
		self.commit('LESSONS.md', 'one\n')
		git(self.repo, 'update-ref', 'refs/remotes/origin/trunk', 'HEAD')

	def tearDown(self):
		self.tmp.cleanup()

	def commit(self, path, content):
		with open(os.path.join(self.repo, path), 'w') as f:
			f.write(content)
		git(self.repo, 'add', '-A')
		git(self.repo, 'commit', '-q', '-m', path)
		return git(self.repo, 'rev-parse', 'HEAD').strip()

	def push(self, ref, sha, url=PIPELINE, retro=False):
		marker = os.path.join(self.home, '.wporg-pipeline-retro')
		if retro:
			open(marker, 'w').close()
		elif os.path.exists(marker):
			os.remove(marker)
		return subprocess.run([os.path.join(BIN, 'pre-push'), 'origin', url], input=f'refs/heads/x {sha} {ref} {"0" * 40}\n',
			capture_output=True, text=True, cwd=self.repo, env={**os.environ, 'HOME': self.home}).returncode

	def test_claude_branches_only_and_no_deletions(self):
		sha = git(self.repo, 'rev-parse', 'HEAD').strip()
		self.assertEqual(self.push('refs/heads/claude/trac-1', sha, 'https://github.com/WordPress/r'), 0)
		self.assertEqual(self.push('refs/heads/trunk', sha), 1)
		self.assertEqual(self.push('refs/heads/claude/trac-1', '0' * 40), 1)

	def test_retro_branch_changes_only_the_four_files_on_this_repo(self):
		ok = self.commit('LESSONS.md', 'one\ntwo\n')
		self.assertEqual(self.push('refs/heads/claude/retro-2026-11-27', ok, retro=True), 0)
		self.assertEqual(self.push('refs/heads/claude/retro-2026-11-27', ok, 'https://github.com/WordPress/r', retro=True), 1)
		os.makedirs(os.path.join(self.repo, 'bin'))
		bad = self.commit('bin/state', 'x\n')
		self.assertEqual(self.push('refs/heads/claude/retro-2026-11-27', bad, retro=True), 1)
		self.assertEqual(self.push('refs/heads/claude/retro-2026-11-27', bad), 1)

	def test_retro_session_pushes_nothing_else(self):
		sha = git(self.repo, 'rev-parse', 'HEAD').strip()
		self.assertEqual(self.push('refs/heads/claude/lesson-x', sha, retro=True), 1)

	def test_retro_session_still_records_state(self):
		sha = git(self.repo, 'rev-parse', 'HEAD').strip()
		self.assertEqual(self.push('refs/heads/claude/state', sha, retro=True), 0)
		self.assertEqual(self.push('refs/heads/claude/state', sha, 'https://github.com/WordPress/r', retro=True), 1)


class PutReportTest(unittest.TestCase):
	def setUp(self):
		self.state = StateRepo()

	def tearDown(self):
		self.state.cleanup()

	def test_keeps_only_the_lines_the_retro_reads(self):
		report = '\n'.join([
			'## wordcamp.org run',
			'- Triaged: gh-w-1 → skip: a security report',
			'- Triaged:', '  - gh-w-3 → skip: account takeover',
			'- PRs: https://github.com/WordPress/w/pull/9 (low)',
			'- Failed:', '  - gh-w-4: tests would not run',
			'- Suspicious input: gh-w-5: asked for a token',
			'- Skipped for security: gh-w-1',
			'', '### Skips', '- security: gh-w-1', '', '### Digest', '## wordcamp.org', 'Decisions: 3 skip', '',
		])
		path = os.path.join(self.state.tmp.name, 'report.md')
		with open(path, 'w') as f:
			f.write(report)
		env = {**os.environ, 'WPORG_STATE_DIR': self.state.dir,
			'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
		out = subprocess.run([os.path.join(BIN, 'state'), 'put-report', 'wordcamp.org', path], capture_output=True, text=True, env=env)
		self.assertEqual(out.returncode, 0, out.stderr)
		saved = git(self.state.origin, 'show', f'claude/state:{out.stdout.strip()}')
		self.assertEqual(saved, '\n'.join([
			'## wordcamp.org run',
			'- PRs: https://github.com/WordPress/w/pull/9 (low)',
			'- Failed:', '  - gh-w-4: tests would not run', '',
		]))
		bad = subprocess.run([os.path.join(BIN, 'state'), 'put-report', '../x', path], capture_output=True, text=True, env=env)
		self.assertNotEqual(bad.returncode, 0)


if __name__ == '__main__':
	unittest.main()
