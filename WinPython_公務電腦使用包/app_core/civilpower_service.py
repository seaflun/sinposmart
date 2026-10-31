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
CIVILPOWER_LOGIN_MESSAGES = {
    "oa_ocr_unavailable": "民力入口網驗證碼辨識元件未就緒，未送出登入。",
    "oa_captcha_not_ready": "民力入口網驗證碼圖片尚未完整載入，未送出登入。",
    "oa_captcha_unrecognized": "民力入口網驗證碼未能辨識，未送出登入。",
    "oa_captcha_ocr_failed": "民力入口網驗證碼辨識失敗，未送出登入。",
    "oa_captcha_rejected": "民力入口網判定驗證碼不正確，已停止自動重送登入。",
    "oa_credentials_rejected": "民力入口網拒絕本次值班人員的帳號密碼，已停止登入，請確認入口網帳密。",
    "oa_login_page_failed": "民力入口網登入頁載入失敗，請確認網站與連線。",
    "oa_login_form_timeout": "民力入口網登入表單載入逾時，未完成登入。",
    "oa_login_verification_timeout": "民力入口網登入送出後驗證逾時，結果尚未確認，已停止自動重送。",
    "oa_password_warning_blocked": "入口網密碼到期提醒未能關閉，尚未確認登入成功。",
    "oa_password_change_required": "入口網密碼須更新，請手動變更密碼後重新登入。",
    "oa_account_locked": "入口網帳號已鎖定或停用，已停止登入，請人工確認。",
    "oa_login_unconfirmed": "民力入口網登入結果尚未確認，已停止自動重送。",
    "oa_password_expired": "入口網密碼已到停用時間，請更新後重新登入。",
    "oa_login_guard_unavailable": "入口網登入保護紀錄無法確認，未送出登入。",
    "oa_session_expired": "入口網作業逾時，已停止本次民力登入。",
    "oa_login_failed": "民力入口網登入未完成，已停止自動重送，請確認網站狀態。",
    "civilpower_sso_timeout": "入口網登入已成功，但開啟民力系統逾時，未重新送出帳密。",
    "civilpower_sso_failed": "入口網登入已成功，但民力系統尚未開啟，未重新送出帳密。",
}


class CivilpowerError(RuntimeError):
    """User-facing error without credentials or raw browser diagnostics."""

    def __init__(self, message: str, *, failure_stage: str = "unknown", error_code: str = "unknown"):
        super().__init__(message)
        self.failure_stage = failure_stage
        self.error_code = error_code if isinstance(error_code, str) and error_code in CIVILPOWER_LOGIN_MESSAGES else "unknown"


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
        from app_core.credential_sync_service import open_sync_request
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
        with open_sync_request(req, timeout=8) as response:
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
