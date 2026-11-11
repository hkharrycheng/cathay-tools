#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J09 行程 JSON 共用建構器（v1.21）
- 本地 gen_itinerary_json.py 與 GitHub Actions regen_json.py 共用，確保兩邊產出格式一致
- 支援「行程總表」多行程、活動性質、圖片詳細、小紅書連結
"""
import re
from datetime import datetime, timedelta

SLOT_START = {"上午": 9, "中午": 12, "下午": 14, "傍晚": 17, "晚上": 19, "全天": 8}
SLOT_ORDER = {"上午": 0, "中午": 1, "下午": 2, "傍晚": 3, "晚上": 4, "全天": 5}
OVERNIGHT_KEY = "及第2天上午"
AIR_NATURE = {"飛機"}
STAY_NATURE = {"住宿"}
EDGE_NATURE = AIR_NATURE | STAY_NATURE


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


def date_of(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000).strftime("%Y-%m-%d")
    s = str(v)
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


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
    """時間欄可為 HH:MM 或時段字；回傳 (hh, mm, slot, overnight)"""
    s = txt(v)
    overnight = OVERNIGHT_KEY in s
    m = re.search(r"(\d{1,2})[:：](\d{2})", s)
    if m:
        hh = min(max(int(m.group(1)), 0), 23)
        mm = min(max(int(m.group(2)), 0), 59)
        return hh, mm, slot_by_clock(hh, mm), overnight
    base = s.split(OVERNIGHT_KEY)[0] if overnight else s
    if base not in SLOT_START:
        base = "上午" if not base else base
    return SLOT_START.get(base, 9), 0, base, overnight


def parse_xhs(v):
    """小紅書連結欄是 url 樣式 text，寫入時是 Markdown 連結；讀出時抽回純網址"""
    s = txt(v)
    m = re.search(r"\((https?://[^)\s]+)\)", s)
    if m:
        return m.group(1)
    m = re.search(r"https?://\S+", s)
    return m.group(0) if m else s


def place_of(v):
    if not isinstance(v, dict):
        return None
    lat, lng = v.get("lat"), v.get("lng")
    if lat is None or lng is None:
        return None
    addr = v.get("full_address") or v.get("address") or v.get("name") or ""
    return {"name": addr, "lat": float(lat), "lng": float(lng), "address": addr}


def images_of(v):
    out = []
    if isinstance(v, list):
        for a in v:
            if isinstance(a, dict) and a.get("file_token"):
                out.append({
                    "token": a.get("file_token"),
                    "name": a.get("name") or "",
                    "type": a.get("type") or "",
                })
    return out


def day_no(label):
    n = "".join(ch for ch in str(label) if ch.isdigit())
    return int(n) if n else 0


def adapt(row):
    """兼容 lark-cli flat row 與 bitable v1 {record_id, fields}"""
    if isinstance(row.get("fields"), dict):
        f = dict(row["fields"])
        f["_rid"] = row.get("record_id")
        return f
    return row


def build_trip_items(plan_rows, trip_start, trip_id):
    items = []
    for idx, row in enumerate(plan_rows):
        f = adapt(row)
        rid = f.get("_rid") or f.get("record_id")
        day = opt(f.get("天數")) or ""
        d0 = date_of(f.get("計劃日期"))
        hh, mm, base_slot, overnight = parse_time(f.get("時間"))
        if not d0 and not trip_start and not day:
            continue
        if trip_start and day_no(day) >= 1:
            d = (datetime.strptime(trip_start, "%Y-%m-%d") + timedelta(days=day_no(day) - 1)).strftime("%Y-%m-%d")
        else:
            d = d0 or trip_start
        if not d:
            continue
        items.append({
            "id": rid,
            "idx": idx,
            "tripId": trip_id,
            "day": day,
            "date": d,
            "slot": base_slot,
            "start": f"{d} {hh:02d}:{mm:02d}",
            "overnight": overnight,
            "minutes": hh * 60 + mm,
            "order": SLOT_ORDER.get(base_slot, 99),
            "nature": opt(f.get("活動性質")) or "",
            "activity": txt(f.get("活動")),
            "plan": txt(f.get("行程")),
            "note": txt(f.get("備註")),
            "stay": txt(f.get("建议停留时长")),
            "xhs": parse_xhs(f.get("小紅書參考連結")),
            "images": images_of(f.get("圖片詳細")),
            "place": place_of(f.get("景點")),
            "status": "Completed" if txt(opt(f.get("狀態"))) == "已完成" else "Pending",
            "statusRaw": txt(opt(f.get("狀態"))) or "等待中",
        })
    items.sort(key=lambda x: (x["date"], x["minutes"], x["order"], x["idx"]))
    return items


def enforce_edges(items):
    """Timeline 必定由機場／酒店開始，結束是酒店或機場"""
    if len(items) < 2:
        return items
    if items[0]["nature"] not in EDGE_NATURE:
        for i, it in enumerate(items):
            if it["nature"] in EDGE_NATURE:
                items.insert(0, items.pop(i))
                break
    if items[-1]["nature"] not in EDGE_NATURE:
        for i in range(len(items) - 1, -1, -1):
            if items[i]["nature"] in EDGE_NATURE:
                items.append(items.pop(i))
                break
    return items


def build_days(items):
    labels = sorted({i["day"] for i in items if i["day"]}, key=day_no)
    days = []
    for label in labels:
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
    return days, labels


def meta_of(req_rows, city):
    meta = {}
    for row in req_rows:
        f = adapt(row)
        label = txt(f.get("文本"))
        detail = txt(f.get("詳細"))
        if not label or not detail:
            continue
        rc = txt(f.get("城市"))
        if city and rc and city not in rc:
            continue
        meta[label] = detail
    return meta


def build_itinerary(plan_rows, trip_rows, req_rows, base_token, version,
                    trips_table="tblW8jSdaVe6uF31", plan_table="tblCISrHCFswpWjv",
                    req_table="tblsRYPi1RrCfokq"):
    plan_ids = set()
    trips = []

    for row in trip_rows:
        f = adapt(row)
        rid = f.get("_rid") or f.get("record_id")
        start = date_of(f.get("開始日期"))
        ids = [x.get("id") for x in (f.get("計劃行程") or []) if isinstance(x, dict) and x.get("id")]
        city = txt(f.get("城市"))
        label_text = txt(f.get("文本"))
        sub = [r for r in plan_rows if (adapt(r).get("_rid") or adapt(r).get("record_id")) in ids] if ids else []
        plan_ids.update(ids)
        items = enforce_edges(build_trip_items(sub, start, rid))
        dates = sorted({i["date"] for i in items})
        days, day_labels = build_days(items)
        meta = meta_of(req_rows, city)
        trips.append({
            "id": rid,
            "label": label_text or ((city + " · ") if city else "") + (start or ""),
            "city": city,
            "startDate": start,
            "planCount": len(items),
            "items": items,
            "days": days,
            "itemsCount": len(items),
            "completedCount": sum(1 for i in items if i["status"] == "Completed"),
            "trip": {
                "name": (f"{dates[0]} → {dates[-1]}" if dates else ""),
                "start": dates[0] if dates else start,
                "end": dates[-1] if dates else None,
                "days": len(day_labels),
                "dayLabels": day_labels,
                "city": city,
                "party": meta.get("團友", ""),
                "partyBg": meta.get("團友背景", ""),
                "food": meta.get("食物偏好", ""),
                "climate": meta.get("氣溫", ""),
                "mode": meta.get("運行模式", ""),
                "span": meta.get("大約時間", ""),
                "category": meta.get("行程類別", ""),
                "content": meta.get("行程內容", ""),
                "meta": meta,
                "tips": [],
            },
        })

    # 冇行程總表（或未 link）時：全部計劃行程當單一行程
    if not trips:
        all_items = enforce_edges(build_trip_items(plan_rows, None, "ALL"))
        dates = sorted({i["date"] for i in all_items})
        days, day_labels = build_days(all_items)
        start = dates[0] if dates else None
        meta = meta_of(req_rows, "")
        trips = [{
            "id": "ALL", "label": "全部行程", "city": "", "startDate": start,
            "planCount": len(all_items), "items": all_items, "days": days,
            "itemsCount": len(all_items),
            "completedCount": sum(1 for i in all_items if i["status"] == "Completed"),
            "trip": {
                "name": (f"{dates[0]} → {dates[-1]}" if dates else ""),
                "start": start, "end": dates[-1] if dates else None,
                "days": len(day_labels), "dayLabels": day_labels, "city": "",
                "party": meta.get("團友", ""), "partyBg": meta.get("團友背景", ""),
                "food": meta.get("食物偏好", ""), "climate": meta.get("氣溫", ""),
                "mode": meta.get("運行模式", ""), "span": meta.get("大約時間", ""),
                "category": meta.get("行程類別", ""), "content": meta.get("行程內容", ""),
                "meta": meta, "tips": [],
            },
        }]

    trips.sort(key=lambda t: (t.get("startDate") or "", t["id"]))
    default_trip = trips[-1]

    result = {
        "version": version,
        "lastUpdate": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": {"baseToken": base_token, "tripsTable": trips_table,
                   "planTable": plan_table, "reqTable": req_table},
        "defaultTripId": default_trip["id"],
        "trips": [{
            "id": t["id"], "label": t["label"], "city": t["city"],
            "startDate": t["startDate"], "planCount": t["planCount"],
            "trip": t["trip"], "days": t["days"], "items": t["items"],
            "itemsCount": t["itemsCount"], "completedCount": t["completedCount"],
        } for t in trips],
    }

    # 兼容舊前端：預設行程鏡射到頂層
    result.update({
        "tripId": default_trip["id"],
        "trip": default_trip["trip"],
        "nextId": next((i["id"] for i in default_trip["items"] if i["status"] != "Completed"), None),
        "itemsCount": default_trip["itemsCount"],
        "completedCount": default_trip["completedCount"],
        "days": default_trip["days"],
        "items": default_trip["items"],
    })
    return result
