# -*- coding: utf-8 -*-
"""Qt list model contract for duty task cards."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt


class DutyTaskListModel(QAbstractListModel):
    TaskIndexRole = Qt.UserRole + 1
    TimeTextRole = Qt.UserRole + 2
    SystemTextRole = Qt.UserRole + 3
    KindTextRole = Qt.UserRole + 4
    DetailTextRole = Qt.UserRole + 5
    PeopleTextRole = Qt.UserRole + 6
    StatusTextRole = Qt.UserRole + 7
    StatusToneRole = Qt.UserRole + 8
    SelectedRole = Qt.UserRole + 9
    ActorTextRole = Qt.UserRole + 10
    TargetTextRole = Qt.UserRole + 11
    ComparisonTextRole = Qt.UserRole + 12
    GroupRole = Qt.UserRole + 13
    FullDetailTextRole = Qt.UserRole + 14

    _ROLE_NAMES = {
        TaskIndexRole: QByteArray(b"taskIndex"),
        TimeTextRole: QByteArray(b"timeText"),
        SystemTextRole: QByteArray(b"systemText"),
        KindTextRole: QByteArray(b"kindText"),
        DetailTextRole: QByteArray(b"detailText"),
        PeopleTextRole: QByteArray(b"peopleText"),
        StatusTextRole: QByteArray(b"statusText"),
        StatusToneRole: QByteArray(b"statusTone"),
        SelectedRole: QByteArray(b"selected"),
        ActorTextRole: QByteArray(b"actorText"),
        TargetTextRole: QByteArray(b"targetText"),
        ComparisonTextRole: QByteArray(b"comparisonText"),
        GroupRole: QByteArray(b"group"),
        FullDetailTextRole: QByteArray(b"fullDetailText"),
    }
    _ROLE_KEYS = {
        TaskIndexRole: "taskIndex",
        TimeTextRole: "timeText",
        SystemTextRole: "systemText",
        KindTextRole: "kindText",
        DetailTextRole: "detailText",
        PeopleTextRole: "peopleText",
        StatusTextRole: "statusText",
        StatusToneRole: "statusTone",
        SelectedRole: "selected",
        ActorTextRole: "actorText",
        TargetTextRole: "targetText",
        ComparisonTextRole: "comparisonText",
        GroupRole: "group",
        FullDetailTextRole: "fullDetailText",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tasks: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tasks)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._tasks):
            return None
        key = self._ROLE_KEYS.get(role)
        if key is None:
            return None
        default: Any = False if role == self.SelectedRole else 0 if role == self.TaskIndexRole else ""
        return self._tasks[index.row()].get(key, default)

    def replace_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Atomically replace rows while keeping the public role contract stable."""

        updated_tasks = [dict(task) for task in tasks]
        same_task_order = (
            len(updated_tasks) == len(self._tasks)
            and all(
                previous.get("taskIndex") == updated.get("taskIndex")
                for previous, updated in zip(self._tasks, updated_tasks)
            )
        )
        if same_task_order:
            changed_rows: list[tuple[int, list[int]]] = []
            for row, (previous, updated) in enumerate(zip(self._tasks, updated_tasks)):
                changed_roles = [
                    role
                    for role, key in self._ROLE_KEYS.items()
                    if previous.get(key) != updated.get(key)
                ]
                if changed_roles:
                    changed_rows.append((row, changed_roles))
            self._tasks = updated_tasks
            for row, changed_roles in changed_rows:
                model_index = self.index(row, 0)
                self.dataChanged.emit(model_index, model_index, changed_roles)
            return

        self.beginResetModel()
        self._tasks = updated_tasks
        self.endResetModel()
