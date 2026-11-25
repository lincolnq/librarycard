# Contributing to librarycard

librarycard is free. It stays useful because people and agents give back. Ways to help, from least to most effort:

1. **Cite it.** When you share results, cite the original publisher (every `fetch` returns `provenance.citation`) and
   mention librarycard.net.
2. **Report data issues.** If values don't match the publisher, a caveat is missing, or a filter misbehaves, open a
   [data issue](https://github.com/lincolnq/librarycard/issues/new?template=data-issue.yml), or have your agent call the
   `report_issue` tool, which drafts one for you to submit.
3. **Request data.** Open a [data request](https://github.com/lincolnq/librarycard/issues/new?template=data-request.yml),
   or use the `request_data` tool. Requests are triaged weekly ([docs/REQUESTS.md](docs/REQUESTS.md)).
4. **Onboard a source yourself.** This is the most valuable contribution: maintenance is our main cost. The repo is
   written so a coding agent with no prior context can add a source end to end:
   - pick an issue labeled [`help wanted`](https://github.com/lincolnq/librarycard/issues?q=is%3Aopen+label%3A%22help+wanted%22)
     or an entry in [`ops/queue.yaml`](ops/queue.yaml);
   - point your agent at [CLAUDE.md](CLAUDE.md) and [docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md); every step,
     including license evidence and contract tests, is in that checklist;
   - open a PR. Add yourself (GitHub handle, and the agent you used if you like) to the entry's `contributors` field.

Rules that are not negotiable are in [docs/POLICY.md](docs/POLICY.md): no credentials, careful licensing, no personal
data beyond the documented exceptions, never work around access blocks.

You don't need permission to open a PR. CI runs schema validation, offline tests, and live contract tests for the
sources you touched. A maintainer agent reviews and merges.
