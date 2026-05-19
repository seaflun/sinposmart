# -*- coding: utf-8 -*-
"""Export rehearsal JSON into human-readable work and entry preview text files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def person_label(staff: dict[str, dict[str, str]], number: str) -> str:
    if not number:
        return "-"
    info = staff.get(str(number), {})
    name = info.get("name", "")
    role = info.get("role", "")
    if name and role:
        return f"{number}番 {name}（{role}）"
    if name:
        return f"{number}番 {name}"
    return f"{number}番"


def people_label(staff: dict[str, dict[str, str]], numbers: list[str]) -> str:
    return "、".join(person_label(staff, no) for no in numbers) if numbers else "-"


def export_preview(json_path: Path, prefix: str | None = None) -> tuple[Path, Path]:
    data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    target_date = prefix or data.get("target_date") or json_path.stem.rsplit("_", 1)[-1]
    staff = {
        **data.get("yesterday", {}).get("staff", {}),
        **data.get("today", {}).get("staff", {}),
    }

    work_lines = [
        f"{target_date} 工作紀錄簿預演確認稿",
        "注意：此檔案由預演模式產生，尚未寫入勤務管理系統。",
        "",
    ]
    for idx, action in enumerate([x for x in data["actions"] if x["kind"] == "work_log"], 1):
        fields = action["fields"]
        work_lines.extend(
            [
                f"===== {idx}. {action['time']} {action['source']} =====",
                f"登打人:{person_label(staff, action['actor'])}",
                f"工作時間:{fields.get('工作時間', action['time'])}",
                f"勤務項目:{fields.get('勤務項目', '')}",
            ]
        )
        if fields.get("事由"):
            work_lines.append(f"事由:{fields['事由']}")
        if fields.get("訓練項目"):
            work_lines.append(f"訓練項目:{fields['訓練項目']}")
        work_lines.extend(
            [
                f"服勤人員:{people_label(staff, fields.get('服勤人員', []))}",
                "工作概述:",
                fields.get("工作概述", ""),
                "處理情形:",
                fields.get("處理情形", ""),
                "",
            ]
        )

    entry_lines = [
        f"{target_date} 出入暨領用無線電機登記簿預演確認稿",
        "注意：此檔案由預演模式產生，尚未寫入勤務管理系統。",
        "",
    ]
    for idx, action in enumerate([x for x in data["actions"] if x["kind"] == "entry_log"], 1):
        fields = action["fields"]
        entry_lines.extend(
            [
                f"{idx:02d}. {fields.get('登打時間', action['time'])} [{action['source']}]",
                f"    登打時間:{fields.get('登打時間', action['time'])}",
                f"    系統寫入時間:{fields.get('系統寫入時間', action['time'])}",
                f"    登打人:{person_label(staff, action['actor'])}",
                f"    對象:{person_label(staff, action['target'])}",
                f"    出或入:{fields.get('出或入', '')}",
                f"    領用事由及地點:{fields.get('領用事由及地點', '')}",
                f"    手提無線電編號:{fields.get('手提無線電編號') or '-'}",
                f"    是否歸還:{fields.get('是否歸還') or '-'}",
                "",
            ]
        )

    out_dir = json_path.parent
    work_path = out_dir / f"{target_date}_work_log_preview.txt"
    entry_path = out_dir / f"{target_date}_radio_entry_preview.txt"
    work_path.write_text("\n".join(work_lines), encoding="utf-8")
    entry_path.write_text("\n".join(entry_lines), encoding="utf-8")
    return work_path, entry_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export rehearsal JSON to text previews.")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--prefix", default=None)
    args = parser.parse_args()
    work_path, entry_path = export_preview(args.json_path, args.prefix)
    print(f"工作紀錄: {work_path}")
    print(f"出入無線電: {entry_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
