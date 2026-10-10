# Design decisions

Each entry: the decision, why, and the alternative that was considered.

## D1. Dependency management: `pip` + `requirements.txt`
`requirements.txt` (runtime) and `requirements-dev.txt` (tooling) work with plain pip in Docker and CI.
`uv` is used only as a fast installer locally (`make install`); it reads the same files.
*Alternative:* uv lockfile. Rejected to keep one universally understood format.

## D2. Python 3.11 via uv-managed interpreter
The prompt requires 3.11+. The dev VM ships 3.10, so `uv python install 3.11` is used; Docker uses `python:3.11-slim`.

## D3. Structured JSON logging (stdlib only)
A small `JsonFormatter` avoids an extra dependency (structlog) and emits one JSON object per line,
with any `extra={...}` fields included. Easy to grep and to ship to a log store.
