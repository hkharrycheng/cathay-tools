#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions: regenerate cathay.json from Feishu Bitable (no lark-cli needed)
"""
import os, json, re, requests
from datetime import datetime, timezone, timedelta

HKT = timezone(timedelta(hours=8))  # 飛書時間戳按香港時間解讀，避免差一日

APP_ID = os.environ.get('FEISHU_APP_ID')
APP_SECRET = os.environ.get('FEISHU_APP_SECRET')
BASE_TOKEN = os.environ.get('BASE_TOKEN', 'C2x4byTkEaN3Ths9FXwcagDSn5e')
TICKETS_TABLE = os.environ.get('TICKETS_TABLE', 'tbl97F6lmemjat8V')
PASSENGERS_TABLE = os.environ.get('PASSENGERS_TABLE', 'tbleF9mFy3Kfyo77')

RAW_FILE = os.environ.get('RAW_FILE', 'data/feishu_raw.json')
DEFAULT_REPO = 'hkharrycheng/cathay-tools'


def load_raw_snapshot():
    """快照來源：① 公開 raw URL（免 token、必定是最新 main）② 本機檔 ③ GitHub API"""
    repo = os.environ.get('GITHUB_REPOSITORY') or os.environ.get('GITHUB_REPO') or DEFAULT_REPO

    # ① 公開 raw（最穩，避開 checkout 時間差）
    try:
        r = requests.get(
            f'https://raw.githubusercontent.com/{repo}/main/{RAW_FILE}',
            headers={'User-Agent': 'cathay-regen'}, timeout=20)
        if r.ok:
            return json.loads(r.text)
        print(f'WARN raw URL HTTP {r.status_code}')
    except Exception as e:
        print(f'WARN raw URL failed: {e}')

    # ② 本機檔
    if os.path.exists(RAW_FILE):
        try:
            with open(RAW_FILE, encoding='utf-8') as fp:
                return json.load(fp)
        except Exception as e:
            print(f'WARN local raw snapshot unreadable: {e}')

    # ③ GitHub API（如有 token）
    tok = os.environ.get('GITHUB_TOKEN')
    if tok:
        try:
            r = requests.get(
                f'https://api.github.com/repos/{repo}/contents/{RAW_FILE}',
                headers={'Authorization': 'Bearer ' + tok,
                         'Accept': 'application/vnd.github.raw',
                         'User-Agent': 'cathay-regen'},
                params={'ref': 'main'}, timeout=20)
            if r.ok:
                return json.loads(r.text)
            print(f'WARN raw API HTTP {r.status_code}')
        except Exception as e:
            print(f'WARN raw API failed: {e}')
    return None


RAW = load_raw_snapshot()
if RAW:
    print(f'Raw snapshot loaded, generatedAt={RAW.get("generatedAt")}')
else:
    print('Raw snapshot missing → 直連飛書 API')


def get_token():
    r = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': APP_ID, 'app_secret': APP_SECRET}, timeout=15)
    j = r.json()
    if not j.get('tenant_access_token'):
        raise SystemExit(f'Feishu auth failed: code={j.get("code")} msg={j.get("msg")}')
    return j['tenant_access_token']


def list_records(token, table_id):
    if RAW:
        return (RAW.get('tables') or {}).get(table_id, [])
    out, page = [], ''
    while True:
        url = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records?page_size=100'
        if page: url += f'&page_token={page}'
        r = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=15)
        j = r.json()
        if j.get('code') != 0:
            print(f'WARN table {table_id}: {j.get("msg")}')
            break
        out.extend(j['data'].get('items', []))
        if j['data'].get('has_more'):
            page = j['data']['page_token']
        else:
            break
    return out

def opt(v):
    if v is None: return None
    if isinstance(v, list):
        if not v: return None
        x = v[0]
        return x.get('text') if isinstance(x, dict) else x
    if isinstance(v, dict):
        return v.get('text') or v.get('name')
    return v

def num(v):
    if v is None or v == '': return None
    try: return float(v)
    except: return None

def ts(v):
    if v is None: return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v/1000, HKT).strftime('%Y-%m-%d %H:%M')
    return str(v)

token = None if RAW else get_token()
raw = list_records(token, TICKETS_TABLE)
print(f'Read {len(raw)} tickets')

pax_map = {}
staff_names = set()
if PASSENGERS_TABLE:
    try:
        pax_raw = list_records(token, PASSENGERS_TABLE)
        for p in pax_raw:
            f = p.get('fields', {})
            name = f.get('DisplayName')
            if isinstance(name, list): name = name[0].get('text') if name else ''
            pax_map[p['record_id']] = name or p['record_id']
            app_name = f.get('Flight Load App Name')
            if app_name:
                staff_names.add(name or p['record_id'])
    except Exception as e:
        print(f'WARN passengers: {e}')

tickets = []
for rec in raw:
    f = rec.get('fields', {})
    # Resolve passenger names from link field
    pax_links = f.get('Passengers', [])
    pax_names = []
    if isinstance(pax_links, list):
        for pl in pax_links:
            pid = pl if isinstance(pl, str) else (pl.get('id') or pl.get('record_id'))
            if pid and pid in pax_map:
                pax_names.append(pax_map[pid])
    t = {
        'id': rec['record_id'],
        'displayName': opt(f.get('Display Name')) or '',
        'flightNumber': opt(f.get('Flight Number')) or '',
        'from': opt(f.get('From')) or '',
        'to': opt(f.get('To')) or '',
        'startTime': ts(f.get('Start Time')),
        'endTime': ts(f.get('End Time')),
        'planeModel': opt(f.get('Plane Model')) or '',
        'capacity': num(f.get('Capacity')),
        'booked': num(f.get('Booked')),
        'checkedIn': num(f.get('Checked-In')),
        'bookedPercent': num(f.get('% Booked')),
        'p25': num(f.get('P25')),
        'p27': num(f.get('P27')),
        'p29': num(f.get('P29')),
        'p31': num(f.get('P31')),
        'p33': num(f.get('P33')),
        'noOfStaff': num(f.get('No. of Staff')),
        'staffPercent': num(f.get('% Staff')),
        'yHk': num(f.get('Y HK$')),
        'yListedHk': num(f.get('Y Listed HK$')),
        'yMilesHk': num(f.get('Y Miles HK$')),
        'discount': num(f.get('Discount %')),
        'asiaMilesUsed': num(f.get('Asia Miles Used')),
        'finalStatus': opt(f.get('Final Status')),
        'finalStatusProb': num(f.get('Final Status Prob')),
        'rollingProb': num(f.get('Rolling Final Status Prob')),
        'passengers': pax_names,
        'screenshots': [],
    }
    tickets.append(t)

with_status = [t for t in tickets if t['finalStatus'] is not None]
accepted = [t for t in with_status if t['finalStatus'] == 'Accepted']
upcoming = [t for t in tickets if t['startTime'] and t['startTime'] > datetime.now().strftime('%Y-%m-%d %H:%M')]

# Top Flyers leaderboard (only staff with Flight Load App Name)
pax_count = {}
for t in tickets:
    for pn in t.get('passengers', []):
        if pn in staff_names:
            pax_count[pn] = pax_count.get(pn, 0) + 1
top_flyers = sorted(
    [{'name': n, 'flights': c, 'avatar': f'pax-avatars/{n}.jpg'} for n, c in pax_count.items()],
    key=lambda x: -x['flights']
)[:15]

result = {
    'version': '1.00',
    'lastUpdate': datetime.now().strftime('%Y-%m-%d %H:%M'),
    'source': {'baseToken': BASE_TOKEN, 'ticketsTable': TICKETS_TABLE},
    'stats': {
        'noOfFlights': len(with_status),
        'totalTickets': len(tickets),
        'successful': len(accepted),
        'successRate': round(len(accepted)/len(with_status), 4) if with_status else 0,
    },
    'tickets': tickets,
    'upcoming': upcoming,
    'topFlyers': top_flyers,
}

with open('cathay.json', 'w', encoding='utf-8') as fp:
    json.dump(result, fp, ensure_ascii=False, indent=2)
print(f'Wrote cathay.json: {len(tickets)} tickets, {len(with_status)} with status')

# ===== itinerary.json (設計行程 / 設計行程圖) =====
PLAN_TABLE = os.environ.get('PLAN_TABLE', 'tblQEnksbXxP2Wa8')
REQ_TABLE = os.environ.get('REQ_TABLE', 'tblsRYPi1RrCfokq')
SLOT_START = {'上午': 9, '中午': 12, '下午': 14, '傍晚': 17, '晚上': 19, '全天': 8}
SLOT_ORDER = {'上午': 0, '中午': 1, '下午': 2, '傍晚': 3, '晚上': 4, '全天': 5}


def flat_text(v):
    if v is None: return ''
    if isinstance(v, list):
        return ' '.join(flat_text(x) for x in v).strip()
    if isinstance(v, dict):
        return flat_text(v.get('text') or v.get('name') or '')
    return str(v).strip()


def day_str(v):
    if v is None: return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v/1000, HKT).strftime('%Y-%m-%d')
    return str(v)[:10]


def slot_by_clock(hh, mm):
    t = hh * 60 + mm
    if t < 12 * 60:
        return '上午'
    if t < 13 * 60:
        return '中午'
    if t < 17 * 60:
        return '下午'
    if t < 19 * 60:
        return '傍晚'
    return '晚上'


def parse_time(v):
    """時間欄可以是 HH:MM（精確）或時段字；回傳 (hh, mm, slot, overnight)"""
    s = flat_text(v)
    overnight = '及第2天上午' in s
    m = re.search(r"(\d{1,2})[:：](\d{2})", s)
    if m:
        hh = min(max(int(m.group(1)), 0), 23)
        mm = min(max(int(m.group(2)), 0), 59)
        return hh, mm, slot_by_clock(hh, mm), overnight
    base = s.split('及第2天上午')[0] if overnight else s
    return SLOT_START.get(base, 9), 0, base, overnight


def place_of(v):
    if not isinstance(v, dict): return None
    lat, lng = v.get('lat'), v.get('lng')
    if lat is None and isinstance(v.get('location'), str):
        parts = v['location'].split(',')
        if len(parts) == 2:
            try:
                lng, lat = float(parts[0]), float(parts[1])
            except Exception:
                lat, lng = None, None
    if lat is None or lng is None: return None
    addr = v.get('full_address') or v.get('address') or v.get('name') or ''
    return {'name': addr, 'lat': float(lat), 'lng': float(lng), 'address': addr}


try:
    plan_raw = list_records(token, PLAN_TABLE)
    req_raw = list_records(token, REQ_TABLE)
    print(f'Read {len(plan_raw)} plan items, {len(req_raw)} requirements')

    items = []
    for idx, rec in enumerate(plan_raw):
        f = rec.get('fields', {})
        d = day_str(f.get('計劃日期'))
        if not d: continue
        hh, mm, base_slot, overnight = parse_time(f.get('時間'))
        items.append({
            'id': rec['record_id'],
            'idx': idx,
            'day': opt(f.get('天數')) or '',
            'date': d,
            'slot': base_slot,
            'start': f'{d} {hh:02d}:{mm:02d}',
            'overnight': overnight,
            'order': SLOT_ORDER.get(base_slot, 99),
            'activity': flat_text(f.get('活動')),
            'plan': flat_text(f.get('行程')),
            'note': flat_text(f.get('備註')),
            'stay': flat_text(f.get('建议停留时长')),
            'budget': num(f.get('消費預算 (HKD)')),
            'taxiMin': num(f.get('打車估計時間 (分鐘)')),
            'distKm': num(f.get('距離上一景點 (KM)')),
            'xhs': flat_text(f.get('小紅書參考連結')),
            'aiTip': flat_text(f.get('AI旅程建議')),
            'place': place_of(f.get('景點')),
            'status': opt(f.get('狀態')) or 'Pending',
        })
    items.sort(key=lambda x: (x['start'], x['order'], x['idx']))

    meta = {}
    for rec in req_raw:
        f = rec.get('fields', {})
        label = flat_text(f.get('文本'))
        detail = flat_text(f.get('詳細'))
        if label and detail: meta[label] = detail

    dates = sorted({i['date'] for i in items})
    day_labels = []
    for i in items:
        if i['day'] and i['day'] not in day_labels: day_labels.append(i['day'])
    day_labels.sort(key=lambda s: int(''.join(ch for ch in s if ch.isdigit()) or 0))

    days = []
    for label in day_labels:
        d_items = [i for i in items if i['day'] == label]
        if not d_items: continue
        days.append({'label': label, 'date': d_items[0]['date'], 'items': d_items,
                     'completed': sum(1 for i in d_items if i['status'] == 'Completed'), 'total': len(d_items)})

    trip = {
        'name': (f'{dates[0]} → {dates[-1]}' if dates else ''),
        'start': dates[0] if dates else None,
        'end': dates[-1] if dates else None,
        'days': len(day_labels),
        'dayLabels': day_labels,
        'party': meta.get('團友', ''),
        'partyBg': meta.get('團友背景', ''),
        'food': meta.get('食物偏好', ''),
        'climate': meta.get('氣溫', ''),
        'mode': meta.get('運行模式', ''),
        'span': meta.get('大約時間', ''),
        'category': meta.get('行程類別', ''),
        'content': meta.get('行程內容', ''),
        'meta': meta,
        'tips': [],
    }

    itin = {
        'version': '1.00',
        'lastUpdate': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'source': {'baseToken': BASE_TOKEN, 'planTable': PLAN_TABLE, 'reqTable': REQ_TABLE},
        'trip': trip,
        'nextId': next((i['id'] for i in items if i['status'] != 'Completed'), None),
        'itemsCount': len(items),
        'completedCount': sum(1 for i in items if i['status'] == 'Completed'),
        'days': days,
        'items': items,
    }
    with open('itinerary.json', 'w', encoding='utf-8') as fp:
        json.dump(itin, fp, ensure_ascii=False, indent=2)
    print(f'Wrote itinerary.json: {len(items)} items, {len(days)} days')
except Exception as e:
    print(f'WARN itinerary: {e}')

# ===== 自行 commit + push（repo 內 workflow 的 commit 步驟只 add cathay.json）=====
import subprocess


def git_push_outputs():
    files = [f for f in ('cathay.json', 'itinerary.json') if os.path.exists(f)]
    if not files:
        return
    try:
        subprocess.run(['git', 'config', 'user.name', 'cathay-bot'], check=True)
        subprocess.run(['git', 'config', 'user.email', 'cathay-bot@users.noreply.github.com'], check=True)
        # 先追平遠端（worker 剛剛推過 raw 快照），否則 push 會被拒
        subprocess.run(['git', 'fetch', 'origin', 'main'], check=False)
        subprocess.run(['git', 'merge', '--no-edit', 'origin/main'], check=False)
        subprocess.run(['git', 'add'] + files, check=True)
        r = subprocess.run(['git', 'diff', '--staged', '--quiet'])
        if r.returncode == 0:
            print('No changes to commit')
            return
        subprocess.run(['git', 'commit', '-m', 'auto: regenerate cathay.json + itinerary.json [skip ci]'], check=True)
        subprocess.run(['git', 'push'], check=True)
        print('Pushed: ' + ', '.join(files))
    except Exception as e:
        print(f'WARN git push: {e}')


git_push_outputs()
