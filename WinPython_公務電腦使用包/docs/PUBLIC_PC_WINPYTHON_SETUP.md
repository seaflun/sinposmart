# 公務電腦 WinPython 使用方式

這份包裝方式是給已安裝 WinPython 的公務電腦使用，不需要安裝系統版 Python，也不需要系統管理員權限。

## 第一次使用

1. 確認公務電腦可以看到本專案資料夾。
2. 確認電腦有 Google Chrome。
3. 確認 WinPython 資料夾存在。
4. 雙擊 `SETUP_WINPYTHON.bat`。
5. 看到 `[OK] Setup completed` 代表安裝完成。

## 平常啟動

雙擊：

```text
RUN_DUTY_GUI_WINPYTHON.vbs
```

這個啟動方式會用 `pythonw.exe`，正常情況不會出現小黑窗。

## WinPython 放哪裡

程式會自動尋找以下位置：

- 本專案資料夾內的 `WinPython*`
- 本專案上一層資料夾內的 `WinPython*`
- 桌面或下載資料夾內的 `WinPython*`
- `C:\WinPython*`
- `D:\WinPython*`
- `G:\WinPython*`

如果找不到，可以手動設定環境變數 `WINPYTHON_DIR` 指到 WinPython 資料夾。

範例：

```bat
set WINPYTHON_DIR=D:\WinPython-3.11.9
SETUP_WINPYTHON.bat
```

## 檔案用途

- `find_winpython.ps1`：尋找 WinPython 的 `python.exe` 或 `pythonw.exe`。
- `SETUP_WINPYTHON.bat`：安裝 Selenium 並檢查環境。
- `RUN_DUTY_GUI_WINPYTHON.bat`：用 WinPython 啟動 GUI，除錯時可直接執行。
- `RUN_DUTY_GUI_WINPYTHON.vbs`：正式啟動，隱藏小黑窗。

## 注意事項

- 帳號清單存在各電腦本機，不會跟著 Google Drive 共用。
- 勤務表與比對資料仍會留在專案資料夾內，兩台電腦可透過 Google Drive 同步。
- 如果公務電腦不能連外網，`SETUP_WINPYTHON.bat` 可能無法下載 Selenium；這時需要先在可連網電腦準備離線 wheel。
