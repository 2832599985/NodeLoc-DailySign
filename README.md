# NodeLoc Daily Sign

NodeLoc Daily Sign is a small Python maintainer for NodeLoc accounts. It can run daily check-in, verify account cookies, collect Discourse account stats, and optionally use Playwright to open real topic pages so normal frontend reading progress can be recorded.

It does not auto-reply, create posts, submit fake large reading-time payloads, or coordinate multiple accounts to boost the same content.

## Features

- Daily check-in for one or more accounts.
- Local same-day skip state, so repeated runs do not keep hitting the check-in API.
- Cookie validity checks through the current-user endpoint.
- Optional browser reading with Playwright.
- Before/after reports for reading time, topics entered, posts read, and visit days.
- Rescue attempts that switch topic candidates when reading finishes but stats do not change.
- Local Web console with task buttons, live events, reports, and editable sanitized config.
- Optional daemon mode for once-per-day runs.

## Install

Use Python 3.11 or newer.

```bash
python -m pip install -r requirements.txt
```

Install Chromium for Playwright if you want browser reading:

```bash
python -m playwright install chromium
```

## Create Your Account Config

Copy the sample config:

```bash
copy accounts.example.json accounts.json
```

On Linux or macOS:

```bash
cp accounts.example.json accounts.json
```

Edit `accounts.json` and add your own accounts:

```json
{
  "accounts": [
    {
      "name": "account-1",
      "cookie": "_t=...; _forum_session=...",
      "csrf_token": ""
    }
  ]
}
```

`accounts.json` contains login secrets. Keep it private. The repository ignores it by default.

## How To Get Your Cookie

Use a browser where you are already logged in to NodeLoc. Chrome and Edge have almost the same DevTools flow.

1. Open [https://www.nodeloc.com/](https://www.nodeloc.com/) and log in.
2. Press `F12` to open DevTools.
3. Open the `Network` tab.
4. Refresh the NodeLoc page.
5. Click any request whose domain is `www.nodeloc.com`.
6. Open the request's `Headers` panel.
7. Find `Request Headers`.
8. Copy the full value of the `Cookie` header.
9. Paste that value into the account's `cookie` field in `accounts.json`.

The cookie value is usually a long string with parts like `_t=...` and `_forum_session=...`. Copy the whole header value, not just one part.

If you do not see the `Cookie` header, make sure DevTools was open before refreshing the page. You can also try clicking a logged-in request such as `/session/current.json`, `/latest.json`, or a topic page request.

## CSRF Token

Leave `csrf_token` empty first. The script tries to fetch `/session/csrf.json` automatically with your cookie.

Only fill `csrf_token` manually if automatic CSRF fetching fails. To get it:

1. Keep DevTools open on the `Network` tab.
2. Click the NodeLoc check-in button manually once, or inspect a request that includes `x-csrf-token`.
3. Open that request's `Headers`.
4. Copy the `x-csrf-token` request header.
5. Paste it into `csrf_token`.

Most users should not need this field.

## Check Your Config

Run a dry-run first:

```bash
python nodeloc_daily_sign.py --dry-run --once
```

For the full maintainer dry-run:

```bash
python nodeloc_daily_sign.py --maintain --dry-run --once --max-accounts 1
```

Dry-run loads the config and checks the flow without real check-in or browser reading.

## Run Daily Check-In

Run a real check-in once:

```bash
python nodeloc_daily_sign.py --once
```

The script stores same-day completion in `.nodeloc_state.json`. If an account already checked in today, another run skips that account locally.

Use `--force` only when you intentionally want to request check-in again:

```bash
python nodeloc_daily_sign.py --once --force
```

## Run The Daily Maintainer

Run check-in and stats collection with browser reading disabled:

```bash
python nodeloc_daily_sign.py --maintain --no-reading --once
```

Run a short browser-reading smoke test for one account:

```bash
python nodeloc_daily_sign.py --maintain --reading --force-reading --reading-minutes 0.05 --topics-per-account 1 --once --max-accounts 1
```

Run the full maintainer with configured browser reading:

```bash
python nodeloc_daily_sign.py --maintain --reading --once
```

Reports are written to `reports/` by default. Use `--report-file path/to/report.txt` to write a specific report file.

## Reading Settings

Configure reading in `accounts.json`:

```json
{
  "reading": {
    "enabled": false,
    "minutes_per_account": 5,
    "topics_per_account": 3,
    "min_stay_seconds": 30,
    "max_stay_seconds": 75,
    "scrolls_per_topic": 8,
    "headless": true,
    "target_time_read_minutes": 0,
    "target_topics_entered": 0,
    "target_posts_read_count": 0,
    "rescue_attempts": 2,
    "rescue_topic_multiplier": 3
  }
}
```

If any target is set, the maintainer reads only when the account is below that target. If no targets are set and reading is enabled, it performs the configured reading session.

Reading progress is verified against real NodeLoc stats after the browser session. If all deltas are zero, the report marks `metrics_not_changed`.

## Web Console

Start a local Web console:

```bash
python nodeloc_daily_sign.py --web --host 127.0.0.1 --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

The console includes:

- `总览`: account status and recent metrics.
- `运行任务`: dry-run, check-in only, and full maintenance actions.
- `实时日志`: task events as they happen.
- `历史报告`: recent text reports.
- `配置`: sanitized config view and editor.

For LAN or public access, set a token:

```bash
python nodeloc_daily_sign.py --web --host 0.0.0.0 --port 8787 --web-token CHANGE_ME
```

You can also use the environment variable:

```bash
set NODELOC_WEB_TOKEN=CHANGE_ME
python nodeloc_daily_sign.py --web --host 0.0.0.0 --port 8787
```

The Web console does not display full cookies or CSRF tokens. It preserves existing secret fields when saving sanitized config.

## Daily Schedule

Run as a long-lived daily process:

```bash
python nodeloc_daily_sign.py --daemon --run-at 08:10
```

Add `--run-now` if you want one immediate run before waiting for the next scheduled time:

```bash
python nodeloc_daily_sign.py --daemon --run-at 08:10 --run-now
```

Cron example:

```cron
10 8 * * * cd /path/to/NodeLoc-DailySign && /usr/bin/python3 nodeloc_daily_sign.py --once >> sign.log 2>&1
```

`--run-at` and cron both use the server's local time.

## Proxy

If your server needs a proxy, set it in `accounts.json`:

```json
{
  "proxy": "http://127.0.0.1:10808"
}
```

## Files That Must Stay Private

Do not upload these files:

- `accounts.json`
- `.nodeloc_state.json`
- `cok.txt`
- `*.har`
- `reports/`
- `output/`
- `.env`

These are ignored by `.gitignore`. Still, check before pushing. Secrets in Git history are a bad afternoon.

## Tests

Run the test suite:

```bash
python -m pytest -q
```

## Project Layout

- `nodeloc_daily_sign.py`: command entry point.
- `nodeloc_maintainer/domain/`: data models and site constants.
- `nodeloc_maintainer/application/`: check-in, stats, reading decisions, reports, and maintainer orchestration.
- `nodeloc_maintainer/infrastructure/`: HTTP client, config loading, state files, Playwright reader, reports, and schedule helpers.
- `nodeloc_maintainer/interfaces/`: CLI and Web console.
- `tools/`: helper scripts.
- `tests/`: behavior tests.
