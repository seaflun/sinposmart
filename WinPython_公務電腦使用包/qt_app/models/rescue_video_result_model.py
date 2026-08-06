# -*- coding: utf-8 -*-
"""QML list model for rescue-video classification results."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt


class RescueVideoResultModel(QAbstractListModel):
    SourceTextRole = Qt.UserRole + 1
    TimeTextRole = Qt.UserRole + 2
    CaseTextRole = Qt.UserRole + 3
    StatusTextRole = Qt.UserRole + 4
    DestinationTextRole = Qt.UserRole + 5
    NoteTextRole = Qt.UserRole + 6
    ToneRole = Qt.UserRole + 7

    _ROLE_NAMES = {
        SourceTextRole: QByteArray(b"sourceText"),
        TimeTextRole: QByteArray(b"timeText"),
        CaseTextRole: QByteArray(b"caseText"),
        StatusTextRole: QByteArray(b"statusText"),
        DestinationTextRole: QByteArray(b"destinationText"),
        NoteTextRole: QByteArray(b"noteText"),
        ToneRole: QByteArray(b"tone"),
    }
    _ROLE_KEYS = {
        SourceTextRole: "sourceText",
        TimeTextRole: "timeText",
        CaseTextRole: "caseText",
        StatusTextRole: "statusText",
        DestinationTextRole: "destinationText",
        NoteTextRole: "noteText",
        ToneRole: "tone",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = self._ROLE_KEYS.get(role)
        return self._rows[index.row()].get(key, "") if key else None

    def replace_rows(self, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()
