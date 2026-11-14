# Lessons

One line each, added through PRs by pipeline runs and curated by a maintainer. Workers read this before every run.

- wporg-theme-directory: run `TEXTDOMAIN=wporg-themes composer exec update-configs` before `composer lint`.
- wordpress.org: the plugin-directory test env maps the wporg-plugins-2024 theme, so its template parts can be tested from `plugin-directory/tests` via `WP_CONTENT_DIR . '/themes/wporg-plugins-2024/...'`; `wp_kses()` output lowercases and re-quotes attributes, so assert with `WP_HTML_Tag_Processor`, not raw strings.
- wordpress.org: Trac config/templates (`trac.wordpress.org/`) can be checked locally: `pip install` the Trac 1.6 sdist into a venv, `trac-admin <env> initenv`, add `file = <repo>/trac.wordpress.org/conf/common.ini` under `[inherit]`, then run `tracd` and curl a page; note `initenv` writes every default into the env's own `trac.ini`, which overrides inherited values.
- wordcamp.org: to run PHPUnit here, start `mariadb:lts` in docker on 3306, run `.docker/bin/install-wp-tests.sh wcorg_test root root 127.0.0.1:3306 latest true`, unzip the GatherPress release CI pins into `plugins/`, build `wporg-groups-frontend`, and `composer update` from a temp copy of `composer-dev.json` without `wporg-profiles-wp-activity-notifier` (meta.svn is blocked); set phpcs `installed_paths` by hand since Composer plugins are disabled. The "WordCamp Groups Network" suite (`mu-plugins/groups/tests`) holds the groups-site theme tests.
