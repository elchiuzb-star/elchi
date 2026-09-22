"""Shared stage-2 contract primitives.

This package is the single source of truth for values that several stage-2
modules and clients must agree on: enums, money arithmetic, error codes, time
handling, public identifiers, cursors, idempotency hashing, event envelopes and
allowed state transitions.

Rules (see docs/architecture/adr/ and AGENTS.md):

* No database models, no routers, no settings access, no I/O.
* Only the standard library and pydantic (already a runtime dependency).
* Must run on Python 3.12 (Docker image) as well as newer local interpreters.
* Changing a public string value is a contract change: it needs an ADR update
  and the integrator's approval, because DB CHECK constraints and generated
  TypeScript types depend on it.
"""
