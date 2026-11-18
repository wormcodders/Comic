# Project review — 18 November 2026

The initial regression run reproduced 79 failures across 29 tests. The review
also checked the browser flows and a private copy of the existing database.

## Security fixes

| Finding | Result |
| --- | --- |
| Predictable session secret and automatically created administrator credentials | Random persistent development secrets; production secrets required; explicit administrator creation; legacy default login blocked. |
| Debug server exposed on every interface | Development binds to localhost; production configuration is selected from the environment; production rejects debug mode. |
| Private, draft, and unpublished comics exposed through direct URLs and APIs | Shared access checks cover details, reading, chapters, comments, ratings, bookmarks, library actions, uploaded files, related content, and public activity. |
| Private tags or collection items exposed in public suggestions and lists | Public suggestions and collection responses filter their associated content. |
| Drafts sent to public hosting services | Draft and private assets stay local; cloud migration selects published public comics. |
| SSRF through redirects or DNS changes | Outbound HTTP pins vetted destination addresses, validates redirects, verifies TLS against the original hostname, rejects credential-bearing redirects, and bounds response size and duration. |
| Arbitrary cover uploads and misleading file extensions | PDF/image bytes are validated; covers are re-encoded; uploaded active-content extensions are denied; PDF page counts and rendered pixel allocations are limited. |
| Stored or DOM-based HTML injection | Notifications use text nodes; HTML escaping protects attributes; tags do not enter inline JavaScript; structured data and charts use JSON serialization. |
| CSRF tokens sent to unrelated origins and logout through GET | Fetch protection targets the same origin and supports Request objects; logout uses a protected POST form. |
| Personal API data retained in browser caches | Dynamic and uploaded responses use no-store; the service worker caches public application assets and removes its older caches. |
| Encryption using a global/default key or falling back to plaintext on failure | Encryption uses the active app key; encryption and decryption failures are handled without exposing plaintext. |
| Password recovery guessing across multiple IPs | Recovery is limited by account as well as IP; administrator recovery uses a local command; password changes invalidate sessions and reset links. |
| Malformed JSON, numeric values, or unrelated resource IDs | Requests receive validation errors; IDs and numeric bounds are checked; parent comments and chapters must belong to the target comic. |
| Password-reset tokens and request details written into debug logs | Error logging records stack locations without query strings, passwords, tokens, or SQL parameter values. |
| Root container and world-writable storage | The container uses an app user, restricted storage permissions, and initialization before Gunicorn workers start. |
| Private files present in the Git index or Docker build context | Ignore rules cover databases, logs, submissions, scratch files, and environment files. The database, debug log, and scratch scripts were removed from Git tracking; their local copies were preserved. |

The package advisory scan identified vulnerabilities in pip (CVE-2026-13346)
and the unused PyPDF2 installation (CVE-2023-36464). Pip was upgraded, PyPDF2 was
removed, and dependency minimums reflect the tested environment. The final
advisory scan reported no known vulnerabilities.

## Functional fixes

Fixed bookmark imports and URLs, chapter numbering and navigation, random and
similar-comic APIs, initial reading-progress calculations, collection renaming,
linked activity creation, comment replies and like counts, user-deletion
cascades, missing template context, chapter pagination, publication flags, and
tag clearing.

Fixed the JavaScript exports used by library and comment controls, library-button
feedback, accessible card and rating labels, and the member upload form.
API timestamps now include UTC offsets so a new comment is not shown as hours old.

Cloud migration keeps local assets until its database commit succeeds and retains
files still referenced by another comic. Failed page extraction does not return
an incomplete or shifted page sequence.

## Validation

Final results: 84 Python tests passed, one Windows symlink test was skipped, and
all 11 JavaScript tests passed. Syntax and Git whitespace checks passed.

- Python regression tests cover authentication, CSRF, privacy, request validation,
  uploads, PDF rendering, encryption, rate limits, bookmarks, progress, collections,
  comments, and migration failures.
- JavaScript tests cover fetch protection, browser caching, output escaping,
  exported callbacks, and accessible control state.
- A private copy of the existing database rendered the home, discovery, search,
  categories, and trending pages successfully.
- Browser checks verified sign-in, library updates, ratings, comment creation,
  two rendered PDF pages, private-comic denial, and protected logout.
- Package consistency and the final dependency advisory scan passed.
- SHA-256 checks confirmed the original database and debug log were unchanged.
- Docker Compose configuration validated. Docker was not running, so the local
  container build and runtime were not tested.

One Windows symlink test is skipped when the host does not permit symlink
creation; CI exercises it on Linux. External hosting and AI provider calls were
mocked rather than used to publish test files.

The isolated browser servers and temporary database/media copies were cleaned up.

See [verification/dependency-audit.json](verification/dependency-audit.json) and
[README.md](README.md) for evidence and setup instructions.

## Operator actions

Reset any legacy administrator password locally, configure a generated production
secret and shared rate-limit storage, and rotate previously committed credentials.
Re-enter encrypted provider settings after replacing their legacy encryption key.
Earlier Git history still needs review before distributing the repository.
