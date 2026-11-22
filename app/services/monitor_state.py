"""The monitor state machine as a pure function (no database, no network).

A single failed check does not mean a site is down: the network can have a
short glitch. A monitor only becomes DOWN after `threshold` failures in a row.

| Current       | Check result | Result                                              |
|---------------|--------------|-----------------------------------------------------|
| UNKNOWN / UP  | success      | UP, failures = 0                                    |
| UNKNOWN / UP  | failure      | failures + 1; at threshold: DOWN + open incident    |
| DOWN          | failure      | failures + 1, nothing else (no repeated alert)      |
| DOWN          | success      | UP, failures = 0, resolve incident                  |
"""

import enum
from dataclasses import dataclass

from app.models.monitor import MonitorStatus


class IncidentAction(enum.StrEnum):
    NONE = "none"
    OPEN = "open"
    RESOLVE = "resolve"


@dataclass(frozen=True)
class Transition:
    status: MonitorStatus
    consecutive_failures: int
    incident_action: IncidentAction

    @property
    def status_changed_to_down(self) -> bool:
        return self.incident_action is IncidentAction.OPEN

    @property
    def status_changed_to_up(self) -> bool:
        return self.incident_action is IncidentAction.RESOLVE


def next_state(
    status: MonitorStatus, consecutive_failures: int, is_up: bool, threshold: int
) -> Transition:
    """Return the new state and what to do with incidents after one check."""
    if threshold < 1:
        raise ValueError("threshold must be at least 1")

    if status is MonitorStatus.DOWN:
        if is_up:
            return Transition(MonitorStatus.UP, 0, IncidentAction.RESOLVE)
        return Transition(MonitorStatus.DOWN, consecutive_failures + 1, IncidentAction.NONE)

    # UNKNOWN or UP
    if is_up:
        return Transition(MonitorStatus.UP, 0, IncidentAction.NONE)
    failures = consecutive_failures + 1
    if failures >= threshold:
        return Transition(MonitorStatus.DOWN, failures, IncidentAction.OPEN)
    return Transition(status, failures, IncidentAction.NONE)
