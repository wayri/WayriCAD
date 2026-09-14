"""Grouped board mutations with recoverable failures and IPC transactions."""


class RecoveryError(RuntimeError):
    """Carries object references so the caller can recover a partial mutation."""
    def __init__(self, message, group, items):
        super().__init__(message)
        self.group, self.items = group, list(items)


def add_group(board, items, name, group_factory):
    raw = getattr(board, 'raw', None)
    transaction = raw.begin_commit() if raw is not None else None
    added, group, grouped = [], None, False
    try:
        for item in items:
            board.Add(item)
            added.append(item)
        group = group_factory(board)
        group.SetName(name)
        for item in items:
            group.AddItem(item)
        board.Add(group)
        grouped = True
        if transaction is not None:
            raw.push_commit(transaction, name)
        return group
    except Exception as exc:
        errors = []
        if transaction is not None:
            try:
                raw.drop_commit(transaction)
            except Exception as rollback:
                errors.append(str(rollback))
        else:
            if group is not None:
                for item in added:
                    try:
                        group.RemoveItem(item)
                    except Exception as rollback:
                        errors.append(str(rollback))
            if grouped:
                try:
                    board.Remove(group)
                except Exception as rollback:
                    errors.append(str(rollback))
            for item in reversed(added):
                try:
                    board.Remove(item)
                except Exception as rollback:
                    errors.append(str(rollback))
        if errors:
            raise RecoveryError('Board operation failed; recovery needs attention: ' + '; '.join(errors), group, added) from exc
        raise


def remove_group(board, group, items):
    raw = getattr(board, 'raw', None)
    transaction = raw.begin_commit() if raw is not None else None
    removed, detached = [], []
    name = group.GetName()
    try:
        for item in items:
            group.RemoveItem(item)
            detached.append(item)
            board.Remove(item)
            removed.append(item)
        board.Remove(group)
        if transaction is not None:
            raw.push_commit(transaction, 'Undo ' + name)
    except Exception as exc:
        errors = []
        if transaction is not None:
            try:
                raw.drop_commit(transaction)
            except Exception as rollback:
                errors.append(str(rollback))
        else:
            for item in removed:
                try:
                    board.Add(item)
                except Exception as rollback:
                    errors.append(str(rollback))
            for item in detached:
                try:
                    group.AddItem(item)
                except Exception as rollback:
                    errors.append(str(rollback))
        if errors:
            raise RecoveryError('Undo failed; recovery needs attention: ' + '; '.join(errors), group, items) from exc
        raise
