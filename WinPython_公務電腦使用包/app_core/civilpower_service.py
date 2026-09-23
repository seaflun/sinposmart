"""Standalone duty-PC attendance requests and read-only rescue-roster access."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


HOME_UNIT = "大園救護分隊"


class CivilpowerError(RuntimeError):
    """User-facing error without credentials or raw browser diagnostics."""


@dataclass(frozen=True)
class AttendanceRequest:
    user_id: str
    password: str = field(repr=False)
    actor_no: str
    actor_name: str
    member: dict
    date_text: str
    time_text: str
    action: str


@dataclass(frozen=True)
class AttendancePlan:
    member_id: str
    member_name: str
    member_title: str
    home_unit: str
    date_text: str
    time_text: str
    status: str
    reason: str
    serve_unit: str = "新坡分隊"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class CivilpowerService:
    def __init__(self, package_root: Path, *, roster_fetcher=None, runner=None):
        self.package_root = Path(package_root)
        self.cache_path = self.package_root / "runtime_outputs" / "civilpower_roster.json"
        self._roster_fetcher = roster_fetcher or self._fetch_roster
        self._runner = runner

    def validate(self, request: AttendanceRequest) -> AttendancePlan:
        if not request.user_id.strip() or not request.password or not request.actor_no or not request.actor_name:
            raise CivilpowerError("請先完成值班人員登入與身分確認。")
        if request.action not in ("到勤", "退勤"):
            raise CivilpowerError("請選擇到勤或退勤。")
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.date_text):
                raise ValueError()
            if not re.fullmatch(r"\d{2}:\d{2}", request.time_text):
                raise ValueError()
            when = datetime.strptime(request.date_text + " " + request.time_text, "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise CivilpowerError("請輸入有效日期 YYYY-MM-DD 與時間 HH:MM。") from exc
        member = request.member
        if (not isinstance(member, dict) or not member.get("member_id") or not member.get("name")
                or member.get("unit") != HOME_UNIT or "顧問" in str(member.get("title", ""))):
            raise CivilpowerError("請從救護台名冊選擇有效義消。")
        return AttendancePlan(str(member["member_id"]), str(member["name"]),
                              str(member.get("title", "")), HOME_UNIT,
                              when.strftime("%Y/%m/%d"), when.strftime("%H%M"),
                              "服勤" if request.action == "到勤" else "退勤", request.action)

    def confirmation_summary(self, request: AttendanceRequest) -> str:
        plan = self.validate(request)
        return (f"登打人：{request.actor_no}番 {request.actor_name}\n"
                f"義消：{plan.member_name}（{plan.member_title}）\n"
                f"所屬單位：{plan.home_unit}\n服勤單位：{plan.serve_unit}\n"
                f"時間：{request.date_text} {request.time_text}\n"
                f"出入：{plan.status}　事由：{plan.reason}\n\n確認後將正式登打出入登記。")

    def load_roster(self) -> dict:
        try:
            snapshot = self._normalize_roster(self._roster_fetcher())
            _write_json(self.cache_path, snapshot)
            return {**snapshot, "cached": False}
        except Exception:
            try:
                snapshot = self._normalize_roster(json.loads(self.cache_path.read_text(encoding="utf-8")))
                return {**snapshot, "cached": True}
            except Exception as exc:
                raise CivilpowerError("無法讀取救護台名冊，也沒有有效快取；請確認連線及名冊讀取介面。") from exc

    @staticmethod
    def _normalize_roster(payload: dict) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("members"), list):
            raise ValueError("invalid roster")
        frequent = payload.get("frequent_member_ids", [])
        if not isinstance(frequent, list):
            raise ValueError("invalid preferences")
        members = []
        seen = set()
        for raw in payload["members"]:
            if not isinstance(raw, dict):
                continue
            member = {key: str(raw.get(key, "")).strip() for key in ("member_id", "name", "unit", "title")}
            if (not member["member_id"] or not member["name"] or member["member_id"] in seen
                    or member["unit"] != "大園救護分隊" or "顧問" in member["title"]):
                continue
            seen.add(member["member_id"])
            member["frequent"] = member["member_id"] in frequent
            member["label"] = ("★ " if member["frequent"] else "") + member["name"] + "　" + member["title"]
            members.append(member)
        if not members:
            raise ValueError("empty roster")
        members.sort(key=lambda m: (not m["frequent"], m["name"], m["title"]))
        return {"members": members, "frequent_member_ids": frequent,
                "last_success_at": str(payload.get("last_success_at", ""))}

    @staticmethod
    def _fetch_roster() -> dict:
        from app_core.operational_sync_service import DEFAULT_SINPOSMART_BACKEND_EVENT_URL
        base = os.environ.get("SINPOSMART_BACKEND_EVENT_URL", DEFAULT_SINPOSMART_BACKEND_EVENT_URL).strip()
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
            raise CivilpowerError("值班後台位址設定不正確。")
        token = os.environ.get("SINPOSMART_CREDENTIAL_SYNC_TOKEN", "").strip()
        if not token:
            raise CivilpowerError("尚未設定既有值班後台同步授權。")
        url = urlunsplit((parts.scheme, parts.netloc, "/api/sinposmart/civilpower-roster", "", ""))
        req = urllib.request.Request(url, headers={"X-Credential-Sync-Token": token})
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise CivilpowerError("救護台名冊讀取失敗。")
        return payload

    def execute(self, request: AttendanceRequest, progress=lambda _message: None) -> str:
        plan = self.validate(request)
        if self._runner is None:
            from app_core.civilpower_automation import run_attendance
            runner = run_attendance
        else:
            runner = self._runner
        return runner(self.package_root, request, plan, progress)
