# SinpoSmart Future Ideas

This file keeps deferred design ideas that should not be implemented until the current duty automation has run in real shifts and the core bugs are fixed.

## 1. Integrate the Old Duty Sheet Automation Project

Source project:

- `I:\我的雲端硬碟\專案\勤務表自動化`
- Main script: `sinposmart_1.py`
- Workbook example: `新坡勤務表115年5月.xlsm`

Goal:

- Bring the old Excel-to-duty-management automation into this project as a separate feature.
- Keep it independent from the current work-log and radio-entry automation.

Proposed structure:

- Add a new module such as `duty_sheet_automation.py`.
- Extract only the reusable parts from `sinposmart_1.py`:
  - Excel duty sheet parsing.
  - Duty management login/navigation.
  - Duty assignment table filling.
  - Vehicle selection logic.
  - Optional Excel range screenshot export.
- Do not import the old script directly, because it mixes GUI globals, login config, LINE/GCS config, Selenium actions, and old UI code.

Proposed GUI surface:

- Add a `勤務表` section or tab in SinpoSmart.
- Fields:
  - Duty date.
  - Excel workbook path.
  - Vehicle selections.
  - Test mode / official save mode.
- Buttons:
  - `預覽`
  - `測試填表`
  - `正式登打`

Implementation order:

1. Extract Excel parsing and generate a preview payload.
2. Fill the duty assignment page in test mode without saving.
3. Add official save only after repeated manual verification.
4. Keep LINE/GCS notification disabled until the core feature is stable.

## 2. Local LINE Desktop Screenshot Posting

Status:

- Deferred.
- Do not implement until SinpoSmart has completed real shift testing.

Goal:

- Capture an Excel duty sheet range and paste it into a selected local LINE desktop group.

Preferred first version:

- Semi-automatic only.
- The program captures the Excel range, opens or focuses LINE desktop, selects the configured group, pastes the image, then stops before sending.
- The user confirms and sends manually.

Possible later version:

- Full automatic send with a group whitelist and visible confirmation warning.

Important constraints:

- Local LINE automation will likely steal keyboard/mouse focus briefly.
- The computer must be unlocked.
- LINE desktop must already be logged in.
- It is less stable than LINE Bot API because it depends on the desktop UI.

Proposed flow:

1. Open the selected Excel workbook.
2. Export the target date's duty sheet range to PNG.
3. Put the PNG into the Windows clipboard.
4. Open/focus LINE desktop.
5. Search or select the configured group.
6. Paste the image.
7. Stop before sending in the first version.

Technical candidates:

- `pywin32` for Excel range export.
- `Pillow` for image handling.
- Windows clipboard APIs for image copy.
- `pywinauto` or `pyautogui` for LINE desktop interaction.

## 3. LINE Bot / GCS Screenshot Posting

Status:

- Also deferred.
- More reliable than local LINE desktop for background sending, but needs setup.

Existing reusable pieces from the old project:

- `export_excel_sheet_to_image(...)`
- `upload_image_to_gcs(...)`
- `send_line_image(...)`
- `send_group_notification(...)`

Requirements:

- LINE Messaging API channel access token.
- LINE group ID.
- GCS bucket with images readable by LINE.
- Google service account JSON.

Design note:

- Keep secrets in config files, not in source code.
- Start with image-only push.
- Do not treat LINE failure as duty automation failure; surface it as a notification-stage error.

## 4. Automatic Submit Host Lock

Status:

- Deferred.
- Add this before running SinpoSmart on two computers with automatic submit enabled.

Goal:

- Allow two computers to open SinpoSmart at the same time, but prevent both from automatically writing duty records.
- Only the computer that holds the submit lock may run automatic work-log or radio-entry submission.
- Other computers may still login, query, review, and manually inspect records.

Proposed behavior:

- On login or when enabling duty mode, try to acquire an automatic-submit host lock.
- The lock records computer name, Windows user, logged-in duty number, acquired time, and last heartbeat time.
- The lock owner refreshes a heartbeat while the app is running.
- If another computer cannot acquire the lock, show a clear status such as `目前由 XXX 電腦執行自動登打，本機只做查詢。`
- If the lock heartbeat is older than about 3 minutes, treat the lock as stale and allow another computer to take over.

Preferred implementation:

- Use a central lock source rather than a Google Drive-only lock file, because Drive sync delay can let two computers believe they both hold the lock.
- Candidate lock backends:
  - Google Sheet / Apps Script endpoint if both computers have internet.
  - Shared folder file lock if both computers are on the same LAN and the share supports real file locking.
  - Temporary manual fallback: an `啟用自動登打` switch, default off on secondary computers.

Required safety checks:

- Keep the existing submit-before-check duplicate detection as the final guard.
- Do not rely only on duplicate detection, because two computers can check at the same time before either one writes.
- When lock is not held, disable automatic due-time submit and queue processing, but leave review mode available.
- Surface lock state in the duty-mode status area so the user can see which computer is active.

Implementation order:

1. Add a local `auto_submit_enabled` gate around automatic submit paths.
2. Add a host-lock interface with acquire, heartbeat, release, and stale-lock handling.
3. Add UI status for lock owner and this computer's mode.
4. Add tests or dry-run checks that prove only one process can hold the lock.
5. Keep manual submit available only with explicit user action and duplicate check.

## 5. Stability Gate Before Adding These Features

Before implementing any of the above, verify the current system through real duty usage:

- Login flow.
- System tray behavior.
- Windows notification behavior.
- Duty mode current-task display.
- Manual rest actions.
- Automatic work-log submission.
- Automatic radio-entry submission.
- Review mode comparison for work and radio entries.

Only add the next feature after the core flow is stable enough that new bugs can be isolated.
