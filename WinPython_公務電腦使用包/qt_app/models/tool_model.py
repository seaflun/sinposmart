# -*- coding: utf-8 -*-
"""Qt list model for the PySide6 tool catalog."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt


class ToolListModel(QAbstractListModel):
    ToolIdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    DescriptionRole = Qt.UserRole + 3
    StatusTextRole = Qt.UserRole + 4
    ToneRole = Qt.UserRole + 5
    AvailableRole = Qt.UserRole + 6

    _ROLE_NAMES = {
        ToolIdRole: QByteArray(b"toolId"),
        LabelRole: QByteArray(b"label"),
        DescriptionRole: QByteArray(b"description"),
        StatusTextRole: QByteArray(b"statusText"),
        ToneRole: QByteArray(b"tone"),
        AvailableRole: QByteArray(b"available"),
    }
    _ROLE_KEYS = {
        ToolIdRole: "toolId",
        LabelRole: "label",
        DescriptionRole: "description",
        StatusTextRole: "statusText",
        ToneRole: "tone",
        AvailableRole: "available",
    }

    def __init__(self, tools: Sequence[Mapping[str, Any]] = (), parent=None) -> None:
        super().__init__(parent)
        self._tools = [dict(tool) for tool in tools]

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tools)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._tools):
            return None
        key = self._ROLE_KEYS.get(role)
        if key is None:
            return None
        default: Any = False if role == self.AvailableRole else ""
        return self._tools[index.row()].get(key, default)

    def tool(self, tool_id: str) -> dict[str, Any] | None:
        return next((tool for tool in self._tools if tool.get("toolId") == tool_id), None)

    def update_tool(self, tool_id: str, **changes: Any) -> bool:
        for row, tool in enumerate(self._tools):
            if tool.get("toolId") != tool_id:
                continue
            changed_roles = []
            for role, key in self._ROLE_KEYS.items():
                if key in changes and tool.get(key) != changes[key]:
                    tool[key] = changes[key]
                    changed_roles.append(role)
            if changed_roles:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, changed_roles)
            return True
        return False


class ToolUsageListModel(QAbstractListModel):
    """Read-only rows for the side-panel last-use history."""

    TimeRole = Qt.UserRole + 1
    PeopleRole = Qt.UserRole + 2
    ResultRole = Qt.UserRole + 3
    ToneRole = Qt.UserRole + 4

    _ROLE_NAMES = {
        TimeRole: QByteArray(b"timeText"),
        PeopleRole: QByteArray(b"peopleText"),
        ResultRole: QByteArray(b"resultText"),
        ToneRole: QByteArray(b"tone"),
    }
    _ROLE_KEYS = {
        TimeRole: "timeText",
        PeopleRole: "peopleText",
        ResultRole: "resultText",
        ToneRole: "tone",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, str]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = self._ROLE_KEYS.get(role)
        return self._rows[index.row()].get(key, "") if key is not None else None

    def replace_rows(self, rows: Sequence[Mapping[str, Any]]) -> None:
        normalized = [
            {
                "timeText": str(row.get("timeText", "") or ""),
                "peopleText": str(row.get("peopleText", "") or ""),
                "resultText": str(row.get("resultText", "") or ""),
                "tone": str(row.get("tone", "neutral") or "neutral"),
            }
            for row in rows
        ]
        if normalized == self._rows:
            return
        self.beginResetModel()
        self._rows = normalized
        self.endResetModel()
