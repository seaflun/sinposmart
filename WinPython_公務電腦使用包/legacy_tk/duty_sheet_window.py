# -*- coding: utf-8 -*-
"""Standalone Tk fallback window for the duty-sheet automation core."""

from __future__ import annotations

import threading
import sys
from pathlib import Path
from types import ModuleType


def run(core: ModuleType) -> int:
    convert_to_minguo = core.convert_to_minguo
    get_default_config = core.get_default_config
    load_config = core.load_config
    save_config = core.save_config
    start_automation = core.start_automation
    def browse_file():
        f = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsm")])
        entry_file.delete(0, tk.END); entry_file.insert(0, f)

    def on_submit():
        uid, pwd, f_path = entry_id.get(), entry_pwd.get(), entry_file.get()
        m_date = convert_to_minguo(cal.get_date())

        login_config = {
            "user_id": uid,
            "user_pwd": pwd
        }
        notification_config = load_config().get("notification", get_default_config()["notification"]).copy()
        notification_config["enabled"] = bool(send_group_var.get())
        cars_config = {
            'attack': attack_car_var.get(),
            'stop': stop_car_var.get(),
            'amb1': amb1_car_var.get(),
            'amb2': amb2_car_var.get()
        }
        # 按下啟動時，自動記憶這次選了什麼
        save_config(
            cars_config,
            login_settings=login_config,
            notification_settings=notification_config,
            car_options=opts,
            hidden_car_options=hidden_opts
        )

        if not f_path:
            messagebox.showwarning("提示", "請選擇 Excel 檔案！")
            return

        #  防止連點，在執行期間鎖死按鈕
        btn_submit.config(state="disabled", text="⏳ 執行中，請稍候...")

        def report_status(message):
            def update_status():
                status_var.set(f"狀態: {core.clean_status_message(message)}")
                log_text.insert(tk.END, f"{message}\n")
                log_text.see(tk.END)

            root.after(0, update_status)

        def report_success(message):
            root.after(0, lambda: messagebox.showinfo("成功", message, parent=root))

        def report_error(message):
            root.after(0, lambda: messagebox.showerror("勤務表登打失敗", message, parent=root))

        #  建立一個背景執行緒來跑主流程，避免視窗卡死
        def run_task():
            try:
                start_automation(
                    uid,
                    pwd,
                    m_date,
                    f_path,
                    cars_config,
                    status_callback=report_status,
                    success_callback=report_success,
                    error_callback=report_error,
                    show_dialogs=False,
                )
            finally:
                # 結束後把按鈕恢復原狀
                root.after(0, lambda: btn_submit.config(state="normal", text="⚡ 啟動全自動流程"))

        # 啟動執行緒 (daemon=True 代表關閉視窗時背景也會強制結束)
        threading.Thread(target=run_task, daemon=True).start()

    # 7-2. GUI 初始化與畫面配置
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    from tkcalendar import DateEntry

    # 🌟 1. 先讀取設定檔
    current_config = load_config()
    login = current_config["login"]
    last = current_config["last_selection"]
    opts = current_config["car_options"]
    hidden_opts = current_config["hidden_car_options"]

    root = tk.Tk()
    root.title("🚒 新坡全自動勤務分配表及救災任務編組表V2.0")
    # 稍微加寬拉長，給予元件足夠的呼吸空間
    root.geometry("450x800")
    # 禁止使用者隨意縮放視窗導致跑版
    root.resizable(False, False)

    # 設定全局字體，讓中文字體顯示更美觀
    default_font = ("微軟正黑體", 10)
    title_font = ("微軟正黑體", 14, "bold")
    root.option_add("*Font", default_font)

    # 設定按鈕的進階樣式
    style = ttk.Style()
    style.configure("TButton", font=("微軟正黑體", 10), padding=3)
    style.configure("Action.TButton", font=("微軟正黑體", 12, "bold"), padding=10)

    # 主容器：給予邊界留白
    main_frame = ttk.Frame(root, padding="20 15 20 15")
    main_frame.pack(fill="both", expand=True)

    # --- 頂部大標題 ---
    ttk.Label(main_frame, text="🚒 新坡分隊關心您的眼睛", font=title_font, anchor="center").pack(fill="x", pady=(0, 15))

    # ==========================================
    # 區塊 1：系統登入資訊
    # ==========================================
    frame_login = ttk.LabelFrame(main_frame, text="👤 登入資訊", padding="10 10 10 10")
    frame_login.pack(fill="x", pady=5)

    # 使用 grid 排版：標籤靠右 (sticky="e")，輸入框靠左 (sticky="w")
    ttk.Label(frame_login, text="系統帳號:").grid(row=0, column=0, sticky="e", padx=5, pady=6)
    entry_id = ttk.Entry(frame_login, width=32)
    entry_id.insert(0, login.get("user_id", ""))
    entry_id.grid(row=0, column=1, sticky="w", padx=5, pady=6)

    ttk.Label(frame_login, text="系統密碼:").grid(row=1, column=0, sticky="e", padx=5, pady=6)
    entry_pwd = ttk.Entry(frame_login, width=32, show="*")
    entry_pwd.insert(0, login.get("user_pwd", ""))
    entry_pwd.grid(row=1, column=1, sticky="w", padx=5, pady=6)

    # ==========================================
    # 區塊 2：班表與日期設定
    # ==========================================
    frame_file = ttk.LabelFrame(main_frame, text="📅 班表資料", padding="10 10 10 10")
    frame_file.pack(fill="x", pady=10)

    ttk.Label(frame_file, text="Excel 路徑:").grid(row=0, column=0, sticky="e", padx=5, pady=6)

    # 將輸入框與瀏覽按鈕包在一個子框架內，讓它們並排
    file_subframe = ttk.Frame(frame_file)
    file_subframe.grid(row=0, column=1, sticky="w", padx=5, pady=6)
    entry_file = ttk.Entry(file_subframe, width=22)
    entry_file.pack(side="left", padx=(0, 5))
    ttk.Button(file_subframe, text="📁 瀏覽", command=browse_file, width=8).pack(side="left")

    ttk.Label(frame_file, text="班表日期:").grid(row=1, column=0, sticky="e", padx=5, pady=6)

    tomorrow = datetime.now() + timedelta(days=1)
    cal = DateEntry(frame_file, width=30, background='darkblue', foreground='white', borderwidth=2,
                    year=tomorrow.year, month=tomorrow.month, day=tomorrow.day,
                    date_pattern='yyyy/mm/dd')
    cal.grid(row=1, column=1, sticky="w", padx=5, pady=6)

    send_group_var = tk.BooleanVar(value=current_config.get("notification", {}).get("enabled", True))
    ttk.Checkbutton(
        frame_file,
        text="是否傳送勤務表截圖至值班台",
        variable=send_group_var
    ).grid(row=2, column=1, sticky="w", padx=5, pady=6)

    # ==========================================
    # 區塊 3：主力車設定
    # ==========================================
    frame_car = ttk.LabelFrame(main_frame, text="🚚 主力車設定", padding="10 10 10 10")
    frame_car.pack(fill="x", pady=5)

    # 統一寬度為 32，確保上下對齊
    combo_width = 30

    # 🌟 2. 修改 Combobox 的預設值與選項清單
    tk.Label(frame_car, text="攻擊車:").grid(row=0, column=0, sticky="e", padx=5, pady=6)
    attack_car_var = tk.StringVar(value=last['attack']) # 預設選上次的
    attack_combo = ttk.Combobox(frame_car, textvariable=attack_car_var, values=opts['attack'], width=combo_width)
    attack_combo.grid(row=0, column=1, sticky="w", padx=5, pady=6)

    tk.Label(frame_car, text="中繼車:").grid(row=1, column=0, sticky="e", padx=5, pady=6)
    stop_car_var = tk.StringVar(value=last['stop'])
    stop_combo = ttk.Combobox(frame_car, textvariable=stop_car_var, values=opts['stop'], width=combo_width)
    stop_combo.grid(row=1, column=1, sticky="w", padx=5, pady=6)

    tk.Label(frame_car, text="救護 1 車:").grid(row=2, column=0, sticky="e", padx=5, pady=6)
    amb1_car_var = tk.StringVar(value=last['amb1'])
    amb1_combo = ttk.Combobox(frame_car, textvariable=amb1_car_var, values=opts['amb'], width=combo_width)
    amb1_combo.grid(row=2, column=1, sticky="w", padx=5, pady=6)

    tk.Label(frame_car, text="救護 2 車:").grid(row=3, column=0, sticky="e", padx=5, pady=6)
    amb2_car_var = tk.StringVar(value=last['amb2'])
    amb2_combo = ttk.Combobox(frame_car, textvariable=amb2_car_var, values=opts['amb'], width=combo_width)
    amb2_combo.grid(row=3, column=1, sticky="w", padx=5, pady=6)

    def persist_car_options():
        login_config = {
            "user_id": entry_user.get().strip(),
            "user_pwd": entry_pwd.get()
        }
        notification_config = load_config().get("notification", get_default_config()["notification"]).copy()
        notification_config["enabled"] = bool(send_group_var.get())
        cars_config = {
            'attack': attack_car_var.get(),
            'stop': stop_car_var.get(),
            'amb1': amb1_car_var.get(),
            'amb2': amb2_car_var.get()
        }
        save_config(
            cars_config,
            login_settings=login_config,
            notification_settings=notification_config,
            car_options=opts,
            hidden_car_options=hidden_opts
        )

    vehicle_groups = {
        "消防車": "attack",
        "救護車": "amb"
    }

    def refresh_vehicle_options():
        attack_combo["values"] = opts.get("attack", [])
        amb_values = opts.get("amb", [])
        amb1_combo["values"] = amb_values
        amb2_combo["values"] = amb_values

    def open_add_vehicle_dialog():
        result = {}
        dialog = tk.Toplevel(root)
        dialog.title("新增車輛")
        dialog.transient(root)
        dialog.grab_set()
        dialog.resizable(False, False)

        vehicle_type_var = tk.StringVar(value="救護車")
        code_var = tk.StringVar()
        plate_var = tk.StringVar()

        ttk.Label(dialog, text="車輛類型").grid(row=0, column=0, sticky="e", padx=10, pady=(12, 6))
        type_combo = ttk.Combobox(dialog, textvariable=vehicle_type_var, values=list(vehicle_groups.keys()), state="readonly", width=18)
        type_combo.grid(row=0, column=1, sticky="w", padx=10, pady=(12, 6))

        ttk.Label(dialog, text="車輛代號").grid(row=1, column=0, sticky="e", padx=10, pady=6)
        code_entry = ttk.Entry(dialog, textvariable=code_var, width=22)
        code_entry.grid(row=1, column=1, sticky="w", padx=10, pady=6)

        ttk.Label(dialog, text="車牌號碼").grid(row=2, column=0, sticky="e", padx=10, pady=6)
        plate_entry = ttk.Entry(dialog, textvariable=plate_var, width=22)
        plate_entry.grid(row=2, column=1, sticky="w", padx=10, pady=6)

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="e", padx=10, pady=(8, 12))

        def confirm():
            vehicle_type = vehicle_type_var.get().strip()
            code = code_var.get().strip()
            plate = plate_var.get().strip()
            if not code or not plate:
                messagebox.showwarning("資料不足", "請輸入車輛代號與車牌號碼。", parent=dialog)
                return
            result["type"] = vehicle_type
            result["value"] = f"{code}/{plate}"
            dialog.destroy()

        ttk.Button(button_frame, text="確定", command=confirm).pack(side="left", padx=(0, 6))
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side="left")
        code_entry.focus_set()
        root.wait_window(dialog)
        return result

    def add_vehicle_option():
        result = open_add_vehicle_dialog()
        if not result:
            return
        group = vehicle_groups[result["type"]]
        value = result["value"]
        options = opts.setdefault(group, [])
        hidden_values = hidden_opts.setdefault(group, [])
        if value in hidden_values:
            hidden_values.remove(value)
        if value not in options:
            options.append(value)
        refresh_vehicle_options()
        persist_car_options()
        messagebox.showinfo("已新增", f"已加入{result['type']}選項：{value}", parent=root)

    def open_remove_vehicle_dialog():
        choices = []
        choice_map = {}
        for vehicle_type, group in vehicle_groups.items():
            for value in opts.get(group, []):
                label = f"{vehicle_type} {value}"
                choices.append(label)
                choice_map[label] = (vehicle_type, group, value)
        if not choices:
            messagebox.showwarning("沒有車輛", "目前沒有可移除的車輛。", parent=root)
            return None

        result = {}
        dialog = tk.Toplevel(root)
        dialog.title("移除車輛")
        dialog.transient(root)
        dialog.grab_set()
        dialog.resizable(False, False)

        selected_var = tk.StringVar(value=choices[0])
        ttk.Label(dialog, text="車輛代號/車牌號碼").grid(row=0, column=0, sticky="e", padx=10, pady=(12, 6))
        select_combo = ttk.Combobox(dialog, textvariable=selected_var, values=choices, state="readonly", width=34)
        select_combo.grid(row=0, column=1, sticky="w", padx=10, pady=(12, 6))

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=1, column=0, columnspan=2, sticky="e", padx=10, pady=(8, 12))

        def confirm():
            selected = selected_var.get()
            if selected in choice_map:
                result["vehicle"] = choice_map[selected]
            dialog.destroy()

        ttk.Button(button_frame, text="確定", command=confirm).pack(side="left", padx=(0, 6))
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side="left")
        select_combo.focus_set()
        root.wait_window(dialog)
        return result.get("vehicle")

    def remove_vehicle_option():
        selected = open_remove_vehicle_dialog()
        if not selected:
            return
        vehicle_type, group, value = selected
        options = opts.setdefault(group, [])
        if value not in options:
            messagebox.showwarning("找不到車輛", f"車輛清單中沒有：{value}", parent=root)
            return
        options.remove(value)
        hidden_values = hidden_opts.setdefault(group, [])
        if value not in hidden_values:
            hidden_values.append(value)
        fallback = options[0] if options else ""
        if group == "attack" and attack_car_var.get().strip() == value:
            attack_car_var.set(fallback)
        if group == "amb":
            if amb1_car_var.get().strip() == value:
                amb1_car_var.set(fallback)
            if amb2_car_var.get().strip() == value:
                amb2_car_var.set(fallback)
        refresh_vehicle_options()
        persist_car_options()
        messagebox.showinfo("已移除", f"已從{vehicle_type}選項移除：{value}", parent=root)

    vehicle_button_frame = ttk.Frame(frame_car)
    vehicle_button_frame.grid(row=4, column=1, sticky="w", padx=5, pady=(0, 6))
    ttk.Button(vehicle_button_frame, text="新增車輛", command=add_vehicle_option).pack(side="left", padx=(0, 6))
    ttk.Button(vehicle_button_frame, text="移除車輛", command=remove_vehicle_option).pack(side="left")

    # ==========================================
    # 區塊 4：執行
    # ==========================================
    action_frame = ttk.Frame(main_frame)
    action_frame.pack(fill="x", pady=(20, 0), padx=15)

    # fill="x" 讓按鈕填滿寬度，更有視覺焦點
    btn_submit = ttk.Button(action_frame, text="⚡ 啟動全自動流程", command=on_submit, style="Action.TButton")
    btn_submit.pack(fill="x")

    log_frame = ttk.LabelFrame(main_frame, text="執行紀錄", padding="10 10 10 10")
    log_frame.pack(fill="both", expand=True, pady=(15, 0))

    log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap="word", state="normal")
    log_text.pack(fill="both", expand=True)
    log_text.insert(tk.END, "準備就緒\n")

    # ==========================================
    # 底部狀態列 (Status Bar)
    # ==========================================
    status_var = tk.StringVar(value="狀態: 準備就緒")
    status_bar = ttk.Label(root, textvariable=status_var, relief="sunken", anchor="w", padding=5)
    status_bar.pack(side="bottom", fill="x")

    root.mainloop()
    return 0


def main() -> int:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

    from duty_sheet_legacy import sinposmart_1

    return run(sinposmart_1)


if __name__ == "__main__":
    raise SystemExit(main())
