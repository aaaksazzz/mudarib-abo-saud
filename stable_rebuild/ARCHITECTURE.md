# Stable architecture

Web and worker are separate processes.

- FastAPI: HTTP/API only.
- PostgreSQL: persistent data.
- Redis: cache and job coordination.
- Worker: market scanner and trade lifecycle updates.
- Existing HTML/CSS/JS: retained and migrated gradually.

The production branch is not changed by this rebuild.
