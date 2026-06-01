# SinpoSmart Deployment Handoff - 2026-05-21

Use this file when moving to the duty computer tomorrow.

## Current Project Folder

Main project:

```text
I:\我的雲端硬碟\專案\值班勤務系統自動化
```

Duty computer package:

```text
I:\我的雲端硬碟\專案\值班勤務系統自動化\WinPython_公務電腦使用包
```

## What Was Updated Today

Core files updated:

- `duty_gui.py`
- `duty_rehearsal.py`
- `compare_rehearsal_records.py`
- `check_environment.py`
- `requirements.txt`

Portable package updated:

- `WinPython_公務電腦使用包\duty_gui.py`
- `WinPython_公務電腦使用包\duty_rehearsal.py`
- `WinPython_公務電腦使用包\compare_rehearsal_records.py`
- `WinPython_公務電腦使用包\check_environment.py`
- `WinPython_公務電腦使用包\requirements.txt`
- `WinPython_公務電腦使用包\duty_tray_icon.png`
- `WinPython_公務電腦使用包\duty_tray_icon.ico`
- `WinPython_公務電腦使用包\install_startup_shortcut.ps1`
- `WinPython_公務電腦使用包\remove_startup_shortcut.ps1`

## Important Behavior Changes

- App display name is `SinpoSmart`.
- Tray icon appears when the app starts.
- Close button hides the app to the tray instead of exiting.
- Windows notification title uses `SinpoSmart`.
- General rest actions are manual only in duty mode.
- Rest sign-out writes `休息`.
- Rest sign-in writes `休息返隊`.
- Review mode checks actual rest records:
  - `出 / 休息`
  - `入 / 休息返隊`
- Rest return no longer matches unrelated `入 / 返隊` case or external records.
- Before official submit, the app checks the current system page for duplicates.
- If a matching record exists, submit is skipped and marked `已存在`.
- On submit failure, an issue zip is created under `issue_reports`.
- Review mode has an `匯出問題包` button.

## First Run on Duty Computer

Open:

```text
WinPython_公務電腦使用包
```

Run once:

```text
SETUP_WINPYTHON.bat
```

Expected result:

```text
[OK] Environment check passed.
[OK] Setup completed.
```

Then start the app with:

```text
RUN_DUTY_GUI_WINPYTHON.vbs
```

This uses `pythonw.exe`, so there should be no console window.

## Add Startup on Duty Computer

After setup succeeds, run this from the package folder if startup is needed:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\install_startup_shortcut.ps1
```

To remove startup:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\remove_startup_shortcut.ps1
```

## Duty Computer Requirements

- Google Chrome installed.
- WinPython available and discoverable by `find_winpython.ps1`.
- Internet access for first `SETUP_WINPYTHON.bat`, unless packages are already installed.
- LINE desktop is not required for the current release.
- Old `勤務表自動化` integration is not enabled yet.

## If Tomorrow Has a Bug

Use review mode and click:

```text
匯出問題包
```

Or, after an automatic submit failure, find the newest zip in:

```text
issue_reports
```

Send or inspect that zip. It contains the key JSON files and recent submit logs needed for debugging.

## Notes for Codex on the Other Computer

When continuing work, first read:

1. `DEPLOYMENT_HANDOFF_20260521.md`
2. `FUTURE_IDEAS.md`
3. `CODE_MAP.md`

Then run:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\sync_project_skills_before_use.ps1
```

Use `karpathy-guidelines` before code changes.
