# Architecture

The project is being shaped for a larger daily maintainer, not just a one-off sign-in script. Code should stay separated by responsibility so future reading, reporting, and browser automation work can be added without turning the project into a pile of cross-imports.

## Layers

`nodeloc_maintainer/` is split into four main layers.

### `domain/`

Pure project concepts. This layer should not perform I/O.

- `site.py`: NodeLoc URLs, response marker text, and default user agent.
- `models.py`: data models such as accounts, settings, check-in results, stats, and topic candidates.

### `infrastructure/`

Adapters for external systems and local files.

- `config.py`: loads and validates `accounts.json`.
- `http_client.py`: all protocol-level HTTP calls to NodeLoc and Discourse endpoints.
- `state.py`: local same-day completion state.
- `browser.py`: shared Playwright/browser helper functions.
- `playwright_reader.py`: real browser reading sessions for Discourse frontend metrics.
- `report_store.py`: local report persistence.
- `schedule.py`: daemon run-time parsing and sleep scheduling.

### `application/`

Business rules and use-case orchestration.

- `ports.py`: protocols that describe external capabilities needed by application services.
- `checkin.py`: check-in classification, retry rules, and account-level check-in.
- `daily_sign.py`: account loop and same-day skip orchestration.
- `stats.py`: account statistics collection.
- `topics.py`: topic discovery for reading sessions.
- `reader.py`: reading-session decision rules.
- `maintainer.py`: full daily workflow across sign-in, stats, reading, and reports.
- `reporting.py`: formatting output without owning collection logic.

### `interfaces/`

External entry points.

- `cli.py`: command-line argument parsing and process wiring.

## Top-Level Files

- `nodeloc_daily_sign.py`: compatibility entry point only.
- `tools/`: operational helpers that reuse package modules.
- `tests/`: behavior and boundary tests.
- `DAILY_MAINTAINER_PLAN.md`: high-level product direction.

## Dependency Direction

Prefer this direction:

```text
interfaces -> application -> domain
interfaces -> infrastructure -> domain
infrastructure -> application ports
application -> domain
```

Application services should depend on `application/ports.py`, not concrete infrastructure classes. `interfaces/cli.py` wires concrete implementations together.

As a quick sanity rule, `domain/` and `application/` should not import `requests`, `playwright`, `pathlib.Path`, or concrete infrastructure modules. They should be testable with in-memory fakes.

Avoid these:

- Domain importing infrastructure or application code.
- HTTP details leaking into CLI, tests, or browser helpers.
- Playwright code inside protocol HTTP clients.
- Future reader/like/reporting modules reaching into private details of check-in logic.

## Request Boundary

All plain HTTP request code belongs in `infrastructure/http_client.py` or a future infrastructure client module. Application services may call client methods, but they should not build raw URLs, headers, or payloads unless the request belongs to that service's explicit boundary.

Concrete clients should be provided through factories or ports, not constructed directly in application services.

## Future Extension Points

Likely future additions:

- `application/likes.py`: low-frequency, non-coordinated like policy.
- `infrastructure/notifier.py`: optional failure notifications.

## Boundaries

The project must not implement automatic replies, automatic posting, coordinated likes, or fake large reading-time submissions.
