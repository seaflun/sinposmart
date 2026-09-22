"""Native attendance form state; all network and browser work runs off the UI thread."""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import QObject, Property, QThread, Signal, Slot
from app_core.civilpower_service import AttendanceRequest, CivilpowerError


class _CivilpowerJob(QThread):
    progress = Signal(str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, service, request=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.request = request

    def run(self):
        try:
            result = (self.service.load_roster() if self.request is None
                      else self.service.execute(self.request, self.progress.emit))
            self.result.emit(result)
        except CivilpowerError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("民力作業未完成，請確認連線與網站狀態。")
        finally:
            self.request = None


class CivilpowerController(QObject):
    stateChanged = Signal()
    confirmationRequested = Signal()
    defaultsLoaded = Signal()
    rosterChanged = Signal()
    runStarted = Signal()
    runSucceeded = Signal(str)
    runFailed = Signal(str)
    errorOccurred = Signal(str)

    def __init__(self, session_state, service, parent=None, *, read_only_acceptance=False):
        super().__init__(parent)
        self._session_state = session_state
        self._service = service
        self._read_only = read_only_acceptance
        self._closing = False
        self._job = None
        self._pending = None
        self._generation = -1
        self._members = []
        self._status = "請選擇人員及到退勤時間。"
        self._roster_status = "尚未讀取名冊"
        self._summary = ""
        self._date = ""
        self._time = ""
        self.run_actor = {}

    @Property(bool, notify=stateChanged)
    def isRunning(self):
        return self._job is not None

    @Property(bool, notify=stateChanged)
    def isAwaitingConfirmation(self):
        return self._pending is not None

    @Property("QVariantList", notify=rosterChanged)
    def members(self):
        return self._members

    @Property(str, notify=stateChanged)
    def statusText(self):
        return self._status

    @Property(str, notify=stateChanged)
    def rosterStatus(self):
        return self._roster_status

    @Property(str, notify=stateChanged)
    def confirmationSummary(self):
        return self._summary

    @Property(str, notify=stateChanged)
    def dateText(self):
        return self._date

    @Property(str, notify=stateChanged)
    def timeText(self):
        return self._time

    @Slot()
    def loadDefaults(self):
        if self.isRunning or self._closing:
            return
        now = datetime.now()
        self._date, self._time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
        self.cancelPendingRun()
        self.defaultsLoaded.emit()
        if not self._read_only:
            self.refreshRoster()

    @Slot()
    def refreshRoster(self):
        if self.isRunning or self._closing or self._read_only:
            return
        self._status = "讀取救護台名冊與常用人員…"
        self._start_job(None)

    @Slot(str, str, str, str)
    def prepareRun(self, date_text, time_text, member_id, action):
        if self.isRunning or self._closing or self._read_only:
            return
        self._pending = None
        self._summary = ""
        session = self._session_state.session
        if session is None or not session.verified:
            self._error("請先完成值班人員登入。")
            return
        member = next((m for m in self._members if m["member_id"] == member_id), None)
        if member is None:
            self._error("請從名冊選擇一位義消。")
            return
        request = AttendanceRequest(session.user_id, session.password, session.actor_no, session.actor_name,
                                    dict(member), date_text, time_text, action)
        try:
            self._summary = self._service.confirmation_summary(request)
        except CivilpowerError as exc:
            self._error(str(exc))
            return
        self._pending = request
        self._generation = self._session_state.generation
        self._status = "等待確認正式登打。"
        self.stateChanged.emit()
        self.confirmationRequested.emit()

    @Slot()
    def confirmRun(self):
        if self._read_only or self._closing or self.isRunning or self._pending is None:
            return
        session = self._session_state.session
        if (self._generation != self._session_state.generation or session is None or not session.verified
                or session.user_id != self._pending.user_id or session.password != self._pending.password
                or session.actor_no != self._pending.actor_no):
            self.cancelPendingRun()
            self._error("值班登入身分已變更，請重新確認登打內容。")
            return
        request, self._pending = self._pending, None
        self._summary = ""
        self._status = "準備登入民力系統…"
        self.run_actor = {"actor_no": request.actor_no, "user_id": request.user_id,
                          "display_name": request.actor_name}
        self.runStarted.emit()
        self._start_job(request)

    @Slot()
    def cancelPendingRun(self):
        self._pending = None
        self._summary = ""
        self.stateChanged.emit()

    def _start_job(self, request):
        job = _CivilpowerJob(self._service, request, self)
        job.progress.connect(self._progress)
        job.result.connect(self._roster_loaded if request is None else self._run_finished)
        job.failed.connect(self._roster_failed if request is None else self._run_failed)
        job.finished.connect(self._job_finished)
        self._job = job
        self.stateChanged.emit()
        job.start()

    @Slot(str)
    def _progress(self, message):
        self._status = message
        self.stateChanged.emit()

    @Slot(object)
    def _roster_loaded(self, result):
        self._members = result["members"]
        self._roster_status = ("離線快取" if result["cached"] else "救護台名冊") + " · " + (result["last_success_at"] or "更新時間未提供")
        self._status = "常用人員以 ★ 置頂；請選擇一位義消。"
        self.rosterChanged.emit()
        self.stateChanged.emit()

    @Slot(str)
    def _roster_failed(self, message):
        self._members = []
        self._roster_status = "名冊不可用"
        self.rosterChanged.emit()
        self._error(message)

    @Slot(object)
    def _run_finished(self, message):
        self._progress(str(message))
        self.runSucceeded.emit(str(message))

    @Slot(str)
    def _run_failed(self, message):
        self.runFailed.emit(message)
        self._error(message)

    @Slot()
    def _job_finished(self):
        job = self._job
        self._job = None
        if job is not None:
            job.deleteLater()
        self.stateChanged.emit()

    def _error(self, message):
        self._progress(message)
        self.errorOccurred.emit(message)

    def prepare_shutdown_admission(self):
        self._closing = True
        self.cancelPendingRun()

    def shutdown(self):
        self.prepare_shutdown_admission()
        if self._job is not None:
            self._job.wait()
