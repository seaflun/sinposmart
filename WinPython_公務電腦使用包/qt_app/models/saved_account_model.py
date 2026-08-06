# -*- coding: utf-8 -*-
"""Password-free saved-account model exposed to QML."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt


class SavedAccountListModel(QAbstractListModel):
    IdentityRole = Qt.UserRole + 1
    ActorNoRole = Qt.UserRole + 2
    UserIdRole = Qt.UserRole + 3
    LabelRole = Qt.UserRole + 4
    HasPasswordRole = Qt.UserRole + 5

    _ROLE_NAMES = {
        IdentityRole: QByteArray(b"identity"),
        ActorNoRole: QByteArray(b"actorNo"),
        UserIdRole: QByteArray(b"userId"),
        LabelRole: QByteArray(b"label"),
        HasPasswordRole: QByteArray(b"hasPassword"),
    }
    _ROLE_KEYS = {
        IdentityRole: "identity",
        ActorNoRole: "actorNo",
        UserIdRole: "userId",
        LabelRole: "label",
        HasPasswordRole: "hasPassword",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._accounts: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._accounts)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._accounts):
            return None
        key = self._ROLE_KEYS.get(role)
        return self._accounts[index.row()].get(key) if key else None

    def replace_accounts(self, accounts: list[dict[str, str]]) -> None:
        rows = []
        for account in accounts:
            actor_no = str(account.get("actor_no", "") or "").strip()
            user_id = str(account.get("user_id", "") or "").strip()
            identity = user_id or actor_no
            label = f"{user_id} / {actor_no}番" if user_id and actor_no else user_id or f"{actor_no}番"
            rows.append(
                {
                    "identity": identity,
                    "actorNo": actor_no,
                    "userId": user_id,
                    "label": label,
                    "hasPassword": bool(account.get("password")),
                }
            )
        self.beginResetModel()
        self._accounts = rows
        self.endResetModel()
