#!/usr/bin/env python3
#
# existing_pr.py <key> — someone else's open PR or patch for an item, so the pipeline never races a contributor's fix.
#
# Trac's linkedPullRequests lags behind GitHub (a PR can be open for hours before the ticket lists
# it), so for a ticket this also searches the WordPress org's open PRs for a reference to it, and
# reads PR links posted in the ticket's comments. A patch on the ticket counts too.
# Prints "<reason>\t<url>" and exits 0 when it finds one; exits 1 otherwise. intake and
# router-intake import it.
#
import json
import os
import re
import subprocess
import sys

BIN = os.path.dirname(os.path.abspath(__file__))
PR_URL = re.compile(r'https://github\.com/(WordPress/[\w.-]+)/pull/(\d+)')


def gh(path):
	out = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
	if out.returncode != 0:
		print(f'existing_pr: {path}: {out.stderr.strip()}', file=sys.stderr)
		return None
	return json.loads(out.stdout)


def pr_state(url):
	"""Return open, merged, or closed for a WordPress PR URL; None when it cannot tell."""
	m = PR_URL.match(url or '')
	pr = m and gh(f'repos/{m.group(1)}/pulls/{m.group(2)}')
	if not pr:
		return None
	if pr['state'] == 'open':
		return 'open'
	return 'merged' if pr.get('merged_at') else 'closed'


def for_ticket(n):
	"""Return (reason, url) for work already under way on Meta Trac ticket n, or None."""
	out = subprocess.run([os.path.join(BIN, 'trac'), 'getTicket', json.dumps({'id': n, 'commentLimit': 50})], capture_output=True, text=True)
	if out.returncode == 0:
		meta = json.loads(out.stdout)['metadata']
		for pr in meta.get('linkedPullRequests', []):
			if pr.get('state') == 'open':
				return ('has an open PR', pr['url'])
		# Description links are usually context (a related feature, a prior attempt); a PR posted in a comment is a fix.
		for c in meta.get('comments', []):
			for url in {m.group(0) for m in PR_URL.finditer(c.get('comment', ''))}:
				if pr_state(url) == 'open':
					return ('has an open PR', url)
		attachments = [a['filename'] for a in meta.get('attachments', [])]
		if 'has-patch' in meta['ticket'].get('keywords', '').split() or any(f.endswith(('.diff', '.patch')) for f in attachments):
			return ('has a patch', f'https://meta.trac.wordpress.org/ticket/{n}')
	else:
		print(f'existing_pr: ticket {n}: {out.stderr.strip()}', file=sys.stderr)

	# A bare number matches PR numbers across the org; only a reference to this ticket counts, and "#N" means a ticket only in wordpress.org.
	url_ref = re.compile(rf'meta\.trac\.wordpress\.org/ticket/{n}\b')
	hash_ref = re.compile(rf'(?<![\w/&])#{n}\b')
	for i in (gh(f'search/issues?q=org:WordPress+is:pr+is:open+{n}&per_page=50') or {}).get('items', []):
		text = f"{i['title']}\n{i.get('body') or ''}"
		if url_ref.search(text) or ('/WordPress/wordpress.org/' in i['html_url'] and hash_ref.search(text)):
			return ('has an open PR', i['html_url'])
	return None


def for_issue(repo, n):
	"""Return (reason, url) for an open PR that references issue n on WordPress/<repo>, or None."""
	for e in gh(f'repos/WordPress/{repo}/issues/{n}/timeline?per_page=100') or []:
		src = (e.get('source') or {}).get('issue') or {}
		if e.get('event') == 'cross-referenced' and src.get('pull_request') and src.get('state') == 'open':
			return ('has an open PR', src['html_url'])
	return None


def for_key(key):
	if key.startswith('trac-'):
		return for_ticket(int(key[5:]))
	repo, n = key[3:].rsplit('-', 1)
	return for_issue(repo, int(n))


if __name__ == '__main__':
	if len(sys.argv) != 2:
		sys.exit('Usage: existing_pr.py <trac-N|gh-<repo>-N>')
	found = for_key(sys.argv[1])
	if found:
		print('\t'.join(found))
	sys.exit(0 if found else 1)
