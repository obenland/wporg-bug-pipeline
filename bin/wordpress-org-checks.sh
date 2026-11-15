#!/usr/bin/env bash
#
# wordpress-org-checks.sh — what CI's phpcs and Unit Tests workflows decide on a WordPress/wordpress.org PR.
# Sourced, not executed, by bin/test-wordpress-org here and by the dotorg skill's wporg-test, so both
# select the same suites and lint the same lines. Running the suites stays with each caller.
#

# wporg_phpcs <checkout> — phpcs on the lines the checkout's HEAD changed since its merge-base with
# origin/trunk, with the same script the PHPCS workflow uses. Returns phpcs's status.
wporg_phpcs() {
	local wt=$1 rc=0
	# The CI script only takes a name under remotes/origin/; point one at the merge-base so trunk's own changes
	# don't count. Refs are shared by every worktree, so the name carries this run's pid: concurrent runs must not collide.
	local base_ref="wporg-test-base-$$"
	git -C "$wt" update-ref "refs/remotes/origin/$base_ref" "$(git -C "$wt" merge-base origin/trunk HEAD)"
	# shellcheck disable=SC2064
	trap "git -C '$wt' update-ref -d 'refs/remotes/origin/$base_ref' 2>/dev/null" EXIT
	(cd "$wt" && BASE_REF=$base_ref php .github/bin/phpcs-branch.php < /dev/null) || rc=1
	git -C "$wt" update-ref -d "refs/remotes/origin/$base_ref"
	return $rc
}

# wporg_select_suites <checkout> <changed files, one per line> <all: 1 or empty> [<suite key>...] — the suites
# CI would run, one per line: type, key, name, script, working directory, phpunit args, bootstrap, separated
# by the unit separator (bash collapses runs of tabs, which would shift empty fields).
# Mirrors the workflow's `changes` job: suite paths + shared paths for the type + the plugins a WordPress
# suite's environment activates. With suite keys, only those run; with all, every suite does.
wporg_select_suites() {
	local wt=$1 changed=$2 all=$3
	shift 3
	CHANGED="$changed" python3 -I - "$wt" "$all" "$@" <<'PY'
import sys, json, re, fnmatch, os, subprocess
wt, all_flag, *only = sys.argv[1:]
changed = [l for l in os.environ.get('CHANGED', '').splitlines() if l]

# A dedicated parser for this file's shape: two map levels, lists of quoted scalars, comments.
def parse_suites_file(text):
    shared = {}; suites = {}; section = None; curkey = None; listkey = None
    for raw in text.splitlines():
        if raw.lstrip().startswith('#') or not raw.strip(): continue
        line = re.sub(r'\s+#.*$', '', raw.rstrip())
        indent = len(line) - len(line.lstrip()); body = line.strip()
        if indent == 0:
            section = body.rstrip(':'); continue
        if section == 'shared-paths':
            if indent == 2: curkey = body.rstrip(':'); shared[curkey] = []
            elif body.startswith('- '): shared[curkey].append(body[2:].strip("'\""))
        elif section == 'suites':
            if indent == 2: curkey = body.rstrip(':'); suites[curkey] = {}; listkey = None
            elif indent == 4:
                k, _, v = body.partition(':'); v = v.strip().strip("'\"")
                if v == '': suites[curkey][k] = []; listkey = k
                else: suites[curkey][k] = v
            elif body.startswith('- ') and listkey: suites[curkey][listkey].append(body[2:].strip("'\""))
    return shared, suites

# CI tests the branch merged with trunk, so a branch older than the suite definitions still gets trunk's.
suites_path = os.path.join(wt, '.github/unit-tests-suites.yml')
if os.path.exists(suites_path):
    suites_text = open(suites_path).read()
else:
    suites_text = subprocess.run(['git', '-C', wt, 'show', 'origin/trunk:.github/unit-tests-suites.yml'], capture_output=True, text=True, check=True).stdout
shared, suites = parse_suites_file(suites_text)

def matches(path, pattern):
    # dorny/paths-filter globs: ** spans directories; fnmatch's * also spans '/', which is what we want for '**'.
    return fnmatch.fnmatch(path, pattern.replace('**', '*'))

for key, s in suites.items():
    if only and key not in only: continue
    paths = list(shared.get(s['type'], [])) + list(s.get('paths', []))
    if s['type'] == 'wordpress':
        cfg = os.path.join(wt, 'environments', key, '.wp-env.test.json')
        try:
            cfg_text = open(cfg).read()
        except FileNotFoundError:
            r = subprocess.run(['git', '-C', wt, 'show', f'origin/trunk:environments/{key}/.wp-env.test.json'], capture_output=True, text=True)
            cfg_text = r.stdout if r.returncode == 0 else '{}'
        for p in json.loads(cfg_text or '{}').get('plugins', []):
            if p.startswith('../'): paths.append(p[3:] + '/**')
    hit = all_flag or bool(only) or any(matches(c, p) for c in changed for p in paths)
    if hit:
        print('\x1f'.join([s['type'], key, s.get('name', key), s.get('script', ''), s.get('working-directory', ''), s.get('phpunit-args', ''), s.get('bootstrap', '')]))
PY
}
