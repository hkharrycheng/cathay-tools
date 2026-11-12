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

# 上一版 cathay.json：保留 version 與截圖路徑（截圖檔名無規律，唔可以靠規則重建）
PREV = {}
if os.path.exists('cathay.json'):
    try:
        with open('cathay.json', encoding='utf-8') as fp:
            PREV = json.load(fp)
    except Exception as e:
        print(f'WARN prev cathay.json unreadable: {e}')
PREV_SHOTS = {t.get('id'): (t.get('screenshots') or [])
              for t in (PREV.get('tickets') or []) if t.get('id')}
PREV_VER = PREV.get('version') or '1.00'
VERSION = PREV_VER if PREV_VER >= '1.02' else '1.02'
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
pax_list = []
if PASSENGERS_TABLE:
    try:
        pax_raw = list_records(token, PASSENGERS_TABLE)
        for p in pax_raw:
            f = p.get('fields', {})
            name = opt(f.get('DisplayName')) or p['record_id']
            pax_map[p['record_id']] = name
            app_name = opt(f.get('Flight Load App Name')) or ''
            pax_list.append({'id': p['record_id'], 'name': name,
                             'appName': app_name, 'avatar': f'pax-avatars/{name}.jpg'})
            if app_name:
                staff_names.add(name)
    except Exception as e:
        print(f'WARN passengers: {e}')

tickets = []
for rec in raw:
    f = rec.get('fields', {})
    # Resolve passenger names from link field（v1.23：單條 link 會回傳 dict 而非 list）
    pax_links = f.get('Passengers', [])
    pax_names = []
    if isinstance(pax_links, dict):
        pax_links = [pax_links]
    if isinstance(pax_links, list):
        for pl in pax_links:
            if isinstance(pl, str):
                ids = [pl]
            elif isinstance(pl, dict):
                ids = pl.get('record_ids') or ([pl.get('id')] if pl.get('id') else [])
            else:
                ids = []
            for pid in ids:
                if pid in pax_map:
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
        'outport': (json.dumps(f.get('Outport Location'), ensure_ascii=False)
                    if isinstance(f.get('Outport Location'), dict) else (f.get('Outport Location') or None)),
        'passengers': pax_names,
        'screenshots': PREV_SHOTS.get(rec['record_id'], []),
    }
    tickets.append(t)

with_status = [t for t in tickets if t['finalStatus'] is not None]
accepted = [t for t in with_status if t['finalStatus'] == 'Accepted']
upcoming = [t for t in tickets if t['startTime'] and t['startTime'] > datetime.now(HKT).strftime('%Y-%m-%d %H:%M')]

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

def mean_of(key):
    vals = [t[key] for t in tickets if t.get(key) is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


status_counts = {}
for t in with_status:
    status_counts[t['finalStatus']] = status_counts.get(t['finalStatus'], 0) + 1
status_dist = [{'status': s, 'count': c} for s, c in
               sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

by_time = sorted([t for t in tickets if t['startTime']], key=lambda t: t['startTime'])
rolling_series = [{'time': t['startTime'], 'prob': t['rollingProb']}
                  for t in by_time if t['rollingProb'] is not None]
staff_trend = [{'time': t['startTime'], 'staff': t['noOfStaff']}
               for t in by_time if t['noOfStaff'] is not None]

result = {
    'version': VERSION,
    'lastUpdate': datetime.now(HKT).strftime('%Y-%m-%d %H:%M'),
    'source': {'baseToken': BASE_TOKEN, 'ticketsTable': TICKETS_TABLE,
               'passengersTable': PASSENGERS_TABLE},
    'stats': {
        'noOfFlights': len(with_status),
        'totalTickets': len(tickets),
        'successful': len(accepted),
        'successRate': round(len(accepted)/len(with_status), 4) if with_status else 0,
        'avgBooked': mean_of('bookedPercent'),
        'avgStaffPercent': mean_of('staffPercent'),
        'avgStaffCount': mean_of('noOfStaff'),
        'avgDiscount': mean_of('discount'),
        'statusDist': status_dist,
    },
    'rollingProb': rolling_series,
    'staffTrend': staff_trend,
    'tickets': tickets,
    'upcoming': upcoming,
    'passengers': pax_list,
    'topFlyers': top_flyers,
}

with open('cathay.json', 'w', encoding='utf-8') as fp:
    json.dump(result, fp, ensure_ascii=False, indent=2)
print(f'Wrote cathay.json: {len(tickets)} tickets, {len(with_status)} with status')

# ===== itinerary.json (設計行程 / 設計行程圖；多行程) =====
import sys

sys.path.insert(0, os.getcwd())
TRIPS_TABLE = os.environ.get('TRIPS_TABLE', 'tblW8jSdaVe6uF31')
PLAN_TABLE = os.environ.get('PLAN_TABLE', 'tblCISrHCFswpWjv')
REQ_TABLE = os.environ.get('REQ_TABLE', 'tblsRYPi1RrCfokq')


def snap_table(tid, alias):
    tabs = (RAW or {}).get('tables') or {}
    if tid in tabs:
        return tabs[tid]
    if alias in tabs:
        return tabs[alias]
    return []


try:
    from itinerary_builder import build_itinerary

    prev_it = {}
    if os.path.exists('itinerary.json'):
        try:
            with open('itinerary.json', encoding='utf-8') as fp:
                prev_it = json.load(fp)
        except Exception:
            prev_it = {}
    itin = build_itinerary(snap_table(PLAN_TABLE, 'plan'), snap_table(TRIPS_TABLE, 'trips'),
                           snap_table(REQ_TABLE, 'req'), BASE_TOKEN,
                           str(prev_it.get('version') or '1.05'),
                           trips_table=TRIPS_TABLE, plan_table=PLAN_TABLE, req_table=REQ_TABLE)
    with open('itinerary.json', 'w', encoding='utf-8') as fp:
        json.dump(itin, fp, ensure_ascii=False, indent=2)
    print(f"Wrote itinerary.json: {len(itin['trips'])} trips, {itin['itemsCount']} items")
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
