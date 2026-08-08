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
    TransferPercentRole = Qt.UserRole + 8
    TransferTextRole = Qt.UserRole + 9

    _ROLE_NAMES = {
        SourceTextRole: QByteArray(b"sourceText"),
        TimeTextRole: QByteArray(b"timeText"),
        CaseTextRole: QByteArray(b"caseText"),
        StatusTextRole: QByteArray(b"statusText"),
        DestinationTextRole: QByteArray(b"destinationText"),
        NoteTextRole: QByteArray(b"noteText"),
        ToneRole: QByteArray(b"tone"),
        TransferPercentRole: QByteArray(b"transferPercent"),
        TransferTextRole: QByteArray(b"transferText"),
    }
    _ROLE_KEYS = {
        SourceTextRole: "sourceText",
        TimeTextRole: "timeText",
        CaseTextRole: "caseText",
        StatusTextRole: "statusText",
        DestinationTextRole: "destinationText",
        NoteTextRole: "noteText",
        ToneRole: "tone",
        TransferPercentRole: "transferPercent",
        TransferTextRole: "transferText",
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

    def prepare_transfer(self) -> None:
        for row in self._rows:
            if row.get("statusText") == "預計複製":
                row["transferPercent"] = 0
                row["transferText"] = "等待傳輸"
                row["statusText"] = "等待傳輸"
            elif str(row.get("statusText") or "").startswith("已完成"):
                row["transferPercent"] = 100
                row["transferText"] = "等待驗證"
            else:
                row["transferPercent"] = 0
                row["transferText"] = "不需傳輸"
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, 0),
                [self.StatusTextRole, self.TransferPercentRole, self.TransferTextRole],
            )

    def update_transfer(self, source_path: str, copied: int, total: int, state: str) -> None:
        for row_number, row in enumerate(self._rows):
            if str(row.get("sourcePath") or "") != source_path:
                continue
            percent = 100 if total <= 0 else max(0, min(100, round(copied * 100 / total)))
            row["transferPercent"] = percent
            row["transferText"] = state
            row["statusText"] = state
            index = self.index(row_number, 0)
            self.dataChanged.emit(
                index,
                index,
                [self.StatusTextRole, self.TransferPercentRole, self.TransferTextRole],
            )
            return
