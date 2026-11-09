# Lessons

One line each, added through PRs by pipeline runs and curated by a maintainer. Workers read this before every run.

- wporg-theme-directory: run `TEXTDOMAIN=wporg-themes composer exec update-configs` before `composer lint`.
- wordpress.org: the plugin-directory test env maps the wporg-plugins-2024 theme, so its template parts can be tested from `plugin-directory/tests` via `WP_CONTENT_DIR . '/themes/wporg-plugins-2024/...'`; `wp_kses()` output lowercases and re-quotes attributes, so assert with `WP_HTML_Tag_Processor`, not raw strings.
