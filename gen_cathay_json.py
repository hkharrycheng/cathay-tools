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
PASSENGERS_TABLE = "tbleF9mFy3Kfyo77"
DASHBOARD_ID = "blkEYDQV9iBTideY"

def run_lark_cli(args):
    cmd = ["lark-cli"] + args + ["--as", "user"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    return result.stdout, result.stderr, result.returncode

def parse_markdown_table(stdout):
    """解析lark-cli markdown表格輸出（legacy，CLI 已停用 markdown 後保留兼容）"""
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

def parse_json_matrix(stdout):
    """解析lark-cli --format json 輸出的 raw matrix（fields + data 行列式）"""
    data = json.loads(stdout)
    payload = data.get('data', data)
    fields = payload.get('fields', [])
    records = payload.get('data', [])
    ids = payload.get('record_id_list', [])
    rows = []
    for i, cells in enumerate(records):
        row = {'_record_id': ids[i] if i < len(ids) else ''}
        for j, name in enumerate(fields):
            if j < len(cells):
                row[name] = cells[j]
        rows.append(row)
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
    """解析select/多選值，如 ["Accepted"] 或字符串"""
    if value is None or value == '' or value == ' ':
        return None
    if isinstance(value, list):
        return value[0] if len(value) > 0 else None
    if isinstance(value, str):
        try:
            arr = json.loads(value)
            if isinstance(arr, list) and len(arr) > 0:
                return arr[0]
            return value
        except:
            return value
    return value

def parse_num(value):
    if value is None or value == '' or value == ' ':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except:
        return None

def parse_ts(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        # 時間戳（秒或毫秒）
        import datetime as _dt
        if value > 10_000_000_000:
            value = value / 1000
        try:
            return _dt.datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M')
        except:
            return None
    s = str(value)
    m = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})', s)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m2 = re.match(r'(\d{4}-\d{2}-\d{2})[ ](\d{2}:\d{2})', s)
    if m2:
        return f"{m2.group(1)} {m2.group(2)}"
    return s

def outport_str(value):
    """location cell（dict 或字符串）統一輸出為 JSON 字符串"""
    if value is None or value == '' or value == ' ':
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return json.dumps(parsed, ensure_ascii=False)
        except:
            return value
    return str(value)

def download_screenshots(row_id, attachments, shot_dir):
    """下載 Original Cap Screen 附件到 screenshots/，返回相對 path list"""
    if not attachments:
        return []
    if isinstance(attachments, str):
        try:
            attachments = json.loads(attachments)
        except:
            return []
    if not isinstance(attachments, list):
        return []
    os.makedirs(shot_dir, exist_ok=True)
    results = []
    for i, att in enumerate(attachments):
        if not isinstance(att, dict):
            continue
        ftoken = att.get('file_token', '')
        fname = att.get('name', f'{row_id}_{i}.jpg')
        if not ftoken:
            continue
        # filename: prefer original name, sanitize
        safe_name = fname.replace(' ', '_').replace('/', '_')
        out_path = os.path.join(shot_dir, safe_name)
        rel_path = f"screenshots/{safe_name}"
        # 已存在就跳過（incremental）
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            results.append(rel_path)
            continue
        cmd = ["lark-cli", "base", "+record-download-attachment",
               "--base-token", BASE_TOKEN, "--table-id", TICKETS_TABLE,
               "--record-id", row_id, "--file-token", ftoken,
               "--output", rel_path, "--overwrite", "--as", "user"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if r.returncode == 0 and os.path.exists(out_path):
            results.append(rel_path)
            print(f"  📷 下載截圖: {safe_name}")
        else:
            print(f"  ⚠️ 截圖下載失敗 {safe_name}: {r.stderr[:200]}")
    return results

def main():
    print("=== J01C 國泰員工機票 JSON 生成器 ===")
    
    # 1. 讀取 Cathay Tickets
    stdout, stderr, rc = run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TICKETS_TABLE,
        "--format", "json"
    ])
    if rc != 0:
        print(f"讀取Cathay Tickets失敗: {stderr}")
        return
    try:
        tickets_rows = parse_json_matrix(stdout)
    except Exception as e:
        print(f"解析Cathay Tickets失敗: {e}")
        return
    print(f"讀取 {len(tickets_rows)} 條航班記錄")
    
    # 2. 讀取 Passengers
    stdout2, stderr2, rc2 = run_lark_cli([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", PASSENGERS_TABLE,
        "--format", "json"
    ])
    if rc2 != 0:
        print(f"⚠️ 讀取Passengers失敗（繼續用空list）: {stderr2[:200]}")
        passenger_rows = []
    else:
        try:
            passenger_rows = parse_json_matrix(stdout2)
        except Exception as e:
            print(f"⚠️ 解析Passengers失敗（繼續用空list）: {e}")
            passenger_rows = []
    print(f"讀取 {len(passenger_rows)} 個乘客")
    
    # 3. 構建 passengers
    passengers = []
    for row in passenger_rows:
        pname = row.get('DisplayName', '')
        avatar_file = f'pax-avatars/{pname}.jpg'
        avatar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), avatar_file)
        avatar_url = avatar_file if os.path.exists(avatar_path) else ''
        passengers.append({
            "id": row.get('_record_id', ''),
            "name": pname,
            "appName": row.get('Flight Load App Name', ''),
            "avatar": avatar_url,
        })
    
    # 4. 構建 tickets
    shot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
    tickets = []
    for row in tickets_rows:
        # 解析 passengers link
        pax_ids = []
        raw_pax = row.get('Passengers', '')
        if raw_pax:
            try:
                if isinstance(raw_pax, list):
                    pax_list = raw_pax
                else:
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

        # 下載截圖（Original Cap Screen 附件欄）
        row_id = row.get('_record_id', '')
        raw_shots = row.get('Original Cap Screen', [])
        screenshots = download_screenshots(row_id, raw_shots, shot_dir)

        tickets.append({
            "id": row_id,
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
            "outport": outport_str(row.get('Outport Location', '')),
            "passengers": pax_names,
            "screenshots": screenshots,
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

    # Top Flyers 龍虎榜（只計有 Flight Load App Name 的成員）
    AVATAR_NAME_MAP = {
        'Father': 'Father', 'Mother': 'Mother', '我': 'Harry',
        '老婆': 'Alice', '姐姐': 'Dyna', '妹妹': 'Joe',
        '沖舅父': 'ChungUncle', '鄭家瑩': 'Alice',
    }
    staff_names = {p['name'] for p in passengers if p.get('appName')}
    pax_avatar_map = {}
    for p in passengers:
        pname = p['name']
        eng = AVATAR_NAME_MAP.get(pname, pname)
        avatar_file = f'pax-avatars/{eng}.jpg'
        avatar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), avatar_file)
        pax_avatar_map[pname] = avatar_file if os.path.exists(avatar_path) else ''
    pax_flight_count = {}
    for t in tickets:
        for pname in t.get('passengers', []):
            if pname in staff_names:
                pax_flight_count[pname] = pax_flight_count.get(pname, 0) + 1
    top_flyers = sorted(
        [{"name": n, "flights": c, "avatar": pax_avatar_map.get(n, '')} for n, c in pax_flight_count.items()],
        key=lambda x: -x['flights']
    )[:15]

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
        "passengers": passengers,
        "topFlyers": top_flyers
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
