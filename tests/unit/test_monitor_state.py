"""One test per row of the state machine table (ROADMAP 3.3)."""

import pytest

from app.models.monitor import MonitorStatus
from app.services.monitor_state import IncidentAction, Transition, next_state

UNKNOWN, UP, DOWN = MonitorStatus.UNKNOWN, MonitorStatus.UP, MonitorStatus.DOWN
THRESHOLD = 3


@pytest.mark.parametrize("status", [UNKNOWN, UP])
def test_success_from_unknown_or_up_is_up(status: MonitorStatus) -> None:
    result = next_state(status, consecutive_failures=2, is_up=True, threshold=THRESHOLD)

    assert result == Transition(UP, 0, IncidentAction.NONE)


@pytest.mark.parametrize("status", [UNKNOWN, UP])
def test_failure_below_threshold_only_counts(status: MonitorStatus) -> None:
    result = next_state(status, consecutive_failures=0, is_up=False, threshold=THRESHOLD)

    assert result == Transition(status, 1, IncidentAction.NONE)


@pytest.mark.parametrize("status", [UNKNOWN, UP])
def test_failure_reaching_threshold_goes_down_and_opens_incident(status: MonitorStatus) -> None:
    result = next_state(status, consecutive_failures=2, is_up=False, threshold=THRESHOLD)

    assert result == Transition(DOWN, 3, IncidentAction.OPEN)
    assert result.status_changed_to_down


def test_failure_while_down_does_nothing_else() -> None:
    result = next_state(DOWN, consecutive_failures=3, is_up=False, threshold=THRESHOLD)

    assert result == Transition(DOWN, 4, IncidentAction.NONE)


def test_success_while_down_recovers_and_resolves_incident() -> None:
    result = next_state(DOWN, consecutive_failures=7, is_up=True, threshold=THRESHOLD)

    assert result == Transition(UP, 0, IncidentAction.RESOLVE)
    assert result.status_changed_to_up


def test_threshold_of_one_goes_down_immediately() -> None:
    assert next_state(UP, 0, is_up=False, threshold=1).incident_action is IncidentAction.OPEN


def test_flapping_is_filtered() -> None:
    """fail, fail, success, fail, fail: never DOWN, because failures are not in a row."""
    status, failures = UP, 0
    actions = []
    for is_up in [False, False, True, False, False]:
        t = next_state(status, failures, is_up, THRESHOLD)
        status, failures = t.status, t.consecutive_failures
        actions.append(t.incident_action)

    assert status is UP
    assert IncidentAction.OPEN not in actions


def test_full_outage_cycle_alerts_once_each_way() -> None:
    status, failures = UNKNOWN, 0
    actions = []
    for is_up in [True, False, False, False, False, False, True, True]:
        t = next_state(status, failures, is_up, THRESHOLD)
        status, failures = t.status, t.consecutive_failures
        actions.append(t.incident_action)

    assert actions.count(IncidentAction.OPEN) == 1
    assert actions.count(IncidentAction.RESOLVE) == 1
    assert status is UP


def test_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        next_state(UP, 0, is_up=False, threshold=0)
