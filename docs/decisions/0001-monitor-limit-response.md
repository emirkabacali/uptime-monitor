# ADR 0001: Respond with 409 Conflict when the monitor limit is reached

- Status: Accepted
- Date: 2026-11-22

## Context

Each user may create at most `MAX_MONITORS_PER_USER` monitors (default 20). The limit
protects the worker capacity and keeps the free service fair. When a user tries to
create one more monitor, the API must return an error. The two common choices are
`422 Unprocessable Entity` and `409 Conflict`.

## Decision

Return **409 Conflict** with the body:

```json
{"detail": "Monitor limit reached (20)", "code": "monitor_limit_reached"}
```

## Reasons

- `422` means the request body itself is invalid. Here the body is perfectly valid:
  the same request would succeed for a user with fewer monitors, or after deleting one.
- `409` means the request conflicts with the **current state** of the resource (the
  user's account). This describes the situation exactly, and the client can fix it
  by changing that state (deleting a monitor).
- Clients can tell the two cases apart: `422` = "fix your input", `409` = "fix your
  account state". The machine-readable `code` makes it explicit.

## Consequences

- API clients must handle 409 on `POST /api/v1/monitors` in addition to 422.
- The check counts existing monitors before inserting. Two parallel requests could
  in theory both pass the check and exceed the limit by one. This is acceptable for a
  soft business limit; a strict guarantee would need a row lock on the user.
