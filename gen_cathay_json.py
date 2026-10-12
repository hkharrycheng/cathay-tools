#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J01C 國泰員工機票 - JSON 生成器
用法: python gen_cathay_json.py
功能: 讀取飛書 Cathay Base -> 生成 cathay.json（HTML Prototype 數據源）
"""
import subprocess
import json
import re
import os
from datetime import datetime

BASE_TOKEN = "C2x4byTkEaN3Ths9FXwcagDSn5e"
TICKETS_TABLE = "tbl97F6lmemjat8V"
PASSENGERS_TABLE = "tblxBC2f3i4L3Khh"
DASHBOARD_ID = "blkEYDQV9iBTideY"

def run_lark_cli(args):
    cmd = ["lark-cli"] + args + ["--as", "user"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    return result.stdout, result.stderr, result.returncode

def parse_markdown_table(stdout):
    """解析lark-cli markdown表格輸出"""
    rows = []
    lines = stdout.strip().split('\n')
    in_table = False
    headers = []
    for line in lines:
        if line.startswith('| _record_id'):
            in_table = True
            headers = [h.strip() for h in line.split('|')[1:-1]]
            continue
        if in_table and line.startswith('| ---'):
            continue
        if in_table and line.startswith('|'):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
        if line.startswith('Meta:'):
            break
    return rows

def parse_dash_data(stdout):
    """解析dashboard-block-get-data輸出"""
    try:
        # 提取JSON部分
        start = stdout.find('{')
        if start == -1:
            return None
        data = json.loads(stdout[start:])
        return data.get('data', {})
    except:
        return None

def parse_opt(value):
    """解析select/多選值，如 ["Accepted"]"""
    if not value or value == '':
        return None
    try:
        arr = json.loads(value)
        if isinstance(arr, list) and len(arr) > 0:
            return arr[0]
        return value
    except:
        return value

def parse_num(value):
    if value is None or value == '' or value == ' ':
        return None
    try:
        return float(value)
    except:
        return None

def parse_ts(value):
    """解析datetime: 2026-05-16T08:10:00.000+08:00"""
    if not value:
        return None
    m = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})', value)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return value

def main():
    print("=== J01C 國泰員工機票 JSON 生成器 ===")
    
    # 1. 讀取 Cathay Tickets
    stdout, stderr, rc = run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TICKETS_TABLE
    ])
    if rc != 0:
        print(f"讀取Cathay Tickets失敗: {stderr}")
        return
    tickets_rows = parse_markdown_table(stdout)
    print(f"讀取 {len(tickets_rows)} 條航班記錄")
    
    # 2. 讀取 Passengers
    stdout2, stderr2, rc2 = run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", PASSENGERS_TABLE
    ])
    if rc2 != 0:
        print(f"讀取Passengers失敗: {stderr2}")
        return
    passenger_rows = parse_markdown_table(stdout2)
    print(f"讀取 {len(passenger_rows)} 個乘客")
    
    # 3. 構建 passengers
    passengers = []
    for row in passenger_rows:
        passengers.append({
            "id": row.get('_record_id', ''),
            "name": row.get('DisplayName', ''),
            "appName": row.get('Flight Load App Name', ''),
        })
    
    # 4. 構建 tickets
    tickets = []
    for row in tickets_rows:
        # 解析 passengers link
        pax_ids = []
        raw_pax = row.get('Passengers', '')
        if raw_pax:
            try:
                pax_list = json.loads(raw_pax)
                pax_ids = [p['id'] for p in pax_list]
            except:
                pass
        
        pax_names = []
        for pid in pax_ids:
            for p in passengers:
                if p['id'] == pid:
                    pax_names.append(p['name'])
                    break
        
        tickets.append({
            "id": row.get('_record_id', ''),
            "displayName": row.get('Display Name', ''),
            "flightNumber": row.get('Flight Number', ''),
            "from": row.get('From', ''),
            "to": row.get('To', ''),
            "startTime": parse_ts(row.get('Start Time', '')),
            "endTime": parse_ts(row.get('End Time', '')),
            "planeModel": row.get('Plane Model', ''),
            "capacity": parse_num(row.get('Capacity', '')),
            "booked": parse_num(row.get('Booked', '')),
            "checkedIn": parse_num(row.get('Checked-In', '')),
            "bookedPercent": parse_num(row.get('% Booked', '')),
            "p25": parse_num(row.get('P25', '')),
            "p27": parse_num(row.get('P27', '')),
            "p29": parse_num(row.get('P29', '')),
            "p31": parse_num(row.get('P31', '')),
            "p33": parse_num(row.get('P33', '')),
            "noOfStaff": parse_num(row.get('No. of Staff', '')),
            "staffPercent": parse_num(row.get('% Staff', '')),
            "yHk": parse_num(row.get('Y HK$', '')),
            "yListedHk": parse_num(row.get('Y Listed HK$', '')),
            "yMilesHk": parse_num(row.get('Y Miles HK$', '')),
            "discount": parse_num(row.get('Discount %', '')),
            "asiaMilesUsed": parse_num(row.get('Asia Miles Used', '')),
            "finalStatus": parse_opt(row.get('Final Status', '')),
            "finalStatusProb": parse_num(row.get('Final Status Prob', '')),
            "rollingProb": parse_num(row.get('Rolling Final Status Prob', '')),
            "outport": row.get('Outport Location', ''),
            "passengers": pax_names,
        })
    
    # 5. Dashboard 統計（自行計算，與飛書 Dashboard 一致）
    # Dashboard 只統計有 Final Status 嘅航班（No. of Flights = 17）
    with_status = [t for t in tickets if t['finalStatus'] is not None]
    accepted = [t for t in with_status if t['finalStatus'] == 'Accepted']
    
    booked_vals = [t['bookedPercent'] for t in with_status if t['bookedPercent'] is not None]
    staff_pct_vals = [t['staffPercent'] for t in with_status if t['staffPercent'] is not None]
    discount_vals = [t['discount'] for t in with_status if t['discount'] is not None]
    staff_count_vals = [t['noOfStaff'] for t in with_status if t['noOfStaff'] is not None]
    
    avg_booked = sum(booked_vals) / len(booked_vals) if booked_vals else 0
    avg_staff_pct = sum(staff_pct_vals) / len(staff_pct_vals) if staff_pct_vals else 0
    avg_discount = sum(discount_vals) / len(discount_vals) if discount_vals else 0
    avg_staff_count = sum(staff_count_vals) / len(staff_count_vals) if staff_count_vals else 0
    
    # Final Status 分佈
    status_dist = {}
    for t in with_status:
        s = t['finalStatus']
        status_dist[s] = status_dist.get(s, 0) + 1
    
    # Rolling Probability 趨勢（按 Start Time 排序）
    rolling = sorted(
        [{"time": t['startTime'], "prob": t['rollingProb']} for t in tickets if t['startTime'] and t['rollingProb'] is not None],
        key=lambda x: x['time']
    )
    
    # Staff 趨勢
    staff_trend = sorted(
        [{"time": t['startTime'], "staff": t['noOfStaff']} for t in tickets if t['startTime'] and t['noOfStaff'] is not None],
        key=lambda x: x['time']
    )
    
    # Upcoming Flights（Start Time > 現在）
    now = datetime.now()
    upcoming = []
    for t in tickets:
        if t['startTime']:
            try:
                t_dt = datetime.strptime(t['startTime'], '%Y-%m-%d %H:%M')
                if t_dt > now:
                    upcoming.append(t)
            except:
                pass
    upcoming.sort(key=lambda x: x['startTime'])
    
    # 6. 構建最終 JSON
    result = {
        "version": "1.00",
        "lastUpdate": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "source": {
            "baseToken": BASE_TOKEN,
            "ticketsTable": TICKETS_TABLE,
            "passengersTable": PASSENGERS_TABLE,
            "dashboardId": DASHBOARD_ID
        },
        "stats": {
            "noOfFlights": len(with_status),
            "totalTickets": len(tickets),
            "successful": len(accepted),
            "successRate": round(len(accepted) / len(with_status), 4) if with_status else 0,
            "avgBooked": round(avg_booked, 4),
            "avgStaffPercent": round(avg_staff_pct, 4),
            "avgStaffCount": round(avg_staff_count, 2),
            "avgDiscount": round(avg_discount, 4),
            "statusDist": [{"status": k, "count": v} for k, v in status_dist.items()]
        },
        "rollingProb": rolling,
        "staffTrend": staff_trend,
        "upcoming": upcoming,
        "tickets": tickets,
        "passengers": passengers
    }
    
    # 7. 寫入文件
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cathay.json')
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"✅ cathay.json 已生成: {out_path}")
    print(f"   航班: {len(tickets)} | 有狀態: {len(with_status)} | 成功: {len(accepted)} ({len(accepted)/len(with_status)*100:.1f}%)" if with_status else "   無狀態航班")
    print(f"   即將起飛: {len(upcoming)} | 乘客: {len(passengers)}")

if __name__ == '__main__':
    main()
