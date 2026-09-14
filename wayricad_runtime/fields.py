"""Apply reviewed text changes with stale-value checks and rollback."""


def apply_fields(changes, reverse=False):
    """Each change is (object with getter/setter, old value, reviewed value)."""
    steps = [(item, new if reverse else old, old if reverse else new)
             for item, old, new in changes]
    for item, expected, _ in steps:
        if item.getter() != expected:
            raise ValueError("Text changed since review. Refresh and review the changes again.")
    completed = []
    try:
        for item, expected, value in steps:
            # Include the current setter in recovery in case it mutates then fails.
            completed.append((item, expected))
            item.setter(value)
    except Exception as cause:
        failures = []
        for item, value in reversed(completed):
            try:
                item.setter(value)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError(f"Edit failed: {cause}. Recovery incomplete: {'; '.join(failures)}") from cause
        raise
