#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J09 國泰機票 + 旅程助手 - 行程 JSON 生成器
用法: python gen_itinerary_json.py
功能: 讀取飛書 計劃行程 (tblQEnksbXxP2Wa8) + 旅遊推介要求 (tblsRYPi1RrCfokq)
      -> 生成 itinerary.json（設計行程 / 設計行程圖 兩個 TAB 的數據源）
"""
import subprocess
import json
import re
import os
import calendar
from datetime import datetime

BASE_TOKEN = "C2x4byTkEaN3Ths9FXwcagDSn5e"
PLAN_TABLE = "tblQEnksbXxP2Wa8"
REQ_TABLE = "tblsRYPi1RrCfokq"

# 時間欄位 -> 建議開始時間（本地時區）
SLOT_TIME = {
    "上午": "09:00",
    "中午": "12:00",
    "下午": "14:00",
    "傍晚": "17:30",
    "晚上": "19:30",
    "全天": "09:00",
}
SLOT_ORDER = {"上午": 0, "中午": 1, "下午": 2, "傍晚": 3, "晚上": 4, "全天": 5}
SLOT_START_HOUR = {"上午": 9, "中午": 12, "下午": 14, "傍晚": 17, "晚上": 19, "全天": 8}
OVERNIGHT_KEY = "及第2天上午"


def slot_by_clock(hh, mm):
    t = hh * 60 + mm
    if t < 12 * 60:
        return "上午"
    if t < 13 * 60:
        return "中午"
    if t < 17 * 60:
        return "下午"
    if t < 19 * 60:
        return "傍晚"
    return "晚上"


def parse_time(v):
    """時間欄可以是 HH:MM（精確）或時段字（上午/下午…）；回傳 (hh, mm, slot, overnight)"""
    s = txt(v)
    overnight = OVERNIGHT_KEY in s
    m = re.search(r"(\d{1,2})[:：](\d{2})", s)
    if m:
        hh = min(max(int(m.group(1)), 0), 23)
        mm = min(max(int(m.group(2)), 0), 59)
        return hh, mm, slot_by_clock(hh, mm), overnight
    base_slot = s.split(OVERNIGHT_KEY)[0] if overnight else s
    return SLOT_START_HOUR.get(base_slot, 9), 0, base_slot, overnight


def run_lark_cli(args):
    cmd = ["lark-cli"] + args + ["--as", "user"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError("lark-cli failed: " + (r.stderr or "")[:200])
    return r.stdout


def fetch_ndjson(table_id, tag):
    stamp = datetime.now().strftime("%H%M%S%f")
    out_file = f"_gen_{tag}_{stamp}.ndjson"
    stdout = run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", table_id,
        "--format", "ndjson",
        "--output", "./" + out_file,
    ])
    manifest = json.loads(stdout)
    rec_file = manifest.get("record_file") or out_file
    rows = []
    with open(rec_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    try:
        os.remove(rec_file)
        mf = manifest.get("manifest_file")
        if mf and os.path.exists(mf):
            os.remove(mf)
    except OSError:
        pass
    return rows


def txt(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return " ".join(txt(x) for x in v).strip()
    if isinstance(v, dict):
        return txt(v.get("text") or v.get("name") or v.get("full_address") or "")
    return str(v).strip()


def opt(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def date_of(v):
    if not v:
        return None
    if isinstance(v, str):
        return v[:10]
    return datetime.fromtimestamp(v / 1000).strftime("%Y-%m-%d")


def place_of(v):
    if not isinstance(v, dict):
        return None
    lat, lng = v.get("lat"), v.get("lng")
    if lat is None or lng is None:
        return None
    addr = v.get("full_address") or v.get("address") or ""
    return {"name": addr, "lat": float(lat), "lng": float(lng), "address": addr}


def build_items(rows):
    items = []
    for idx, r in enumerate(rows):
        slot = txt(r.get("時間"))
        d = date_of(r.get("計劃日期"))
        if not d:
            continue
        hh, mm, base_slot, overnight = parse_time(r.get("時間"))
        start = f"{d} {hh:02d}:{mm:02d}"
        items.append({
            "id": r.get("record_id"),
            "idx": idx,
            "day": opt(r.get("天數")) or "",
            "date": d,
            "slot": base_slot,
            "start": start,
            "overnight": overnight,
            "order": SLOT_ORDER.get(base_slot, 99),
            "activity": txt(r.get("活動")),
            "plan": txt(r.get("行程")),
            "note": txt(r.get("備註")),
            "stay": txt(r.get("建议停留时长")),
            "budget": num(r.get("消費預算 (HKD)")),
            "taxiMin": num(r.get("打車估計時間 (分鐘)")),
            "distKm": num(r.get("距離上一景點 (KM)")),
            "xhs": txt(r.get("小紅書參考連結")),
            "aiTip": txt(r.get("AI旅程建議")),
            "place": place_of(r.get("景點")),
            "status": opt(r.get("狀態")) or "Pending",
        })
    items.sort(key=lambda x: (x["start"], x["order"], x["idx"]))
    return items


def build_trip(plan_rows, req_rows):
    day_labels = sorted({opt(r.get("天數")) for r in plan_rows if opt(r.get("天數"))},
                        key=lambda s: int("".join(ch for ch in s if ch.isdigit()) or 0))
    dates = [date_of(r.get("計劃日期")) for r in plan_rows if date_of(r.get("計劃日期"))]
    meta = {}
    tips = []
    for r in req_rows:
        label = txt(r.get("文本"))
        detail = txt(r.get("詳細"))
        if label and detail:
            meta[label] = detail
    trip_name = ""
    if dates:
        trip_name = f"{min(dates)} → {max(dates)}"
    return {
        "name": trip_name,
        "start": min(dates) if dates else None,
        "end": max(dates) if dates else None,
        "days": len(day_labels),
        "dayLabels": day_labels,
        "party": meta.get("團友", ""),
        "partyBg": meta.get("團友背景", ""),
        "food": meta.get("食物偏好", ""),
        "climate": meta.get("氣溫", ""),
        "mode": meta.get("運行模式", ""),
        "span": meta.get("大約時間", ""),
        "category": meta.get("行程類別", ""),
        "content": meta.get("行程內容", ""),
        "meta": meta,
        "tips": tips,
    }


def main():
    plan_rows = fetch_ndjson(PLAN_TABLE, "plan")
    req_rows = fetch_ndjson(REQ_TABLE, "req")
    items = build_items(plan_rows)
    trip = build_trip(plan_rows, req_rows)

    days = []
    for label in trip["dayLabels"]:
        d_items = [i for i in items if i["day"] == label]
        if not d_items:
            continue
        days.append({
            "label": label,
            "date": d_items[0]["date"],
            "items": d_items,
            "completed": sum(1 for i in d_items if i["status"] == "Completed"),
            "total": len(d_items),
        })

    # 第一個未完成項目 = 「下一個行程」
    next_id = next((i["id"] for i in items if i["status"] != "Completed"), None)

    result = {
        "version": "1.00",
        "lastUpdate": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": {"baseToken": BASE_TOKEN, "planTable": PLAN_TABLE, "reqTable": REQ_TABLE},
        "trip": trip,
        "nextId": next_id,
        "itemsCount": len(items),
        "completedCount": sum(1 for i in items if i["status"] == "Completed"),
        "days": days,
        "items": items,
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "itinerary.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ itinerary.json 已生成: {out_path}")
    print(f"   行程項目: {len(items)} | 天數: {len(days)} | 已完成: {result['completedCount']}")


if __name__ == "__main__":
    main()
