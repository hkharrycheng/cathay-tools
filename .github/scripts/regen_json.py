#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions: regenerate cathay.json from Feishu Bitable (no lark-cli needed)
"""
import os, json, requests
from datetime import datetime

APP_ID = os.environ['FEISHU_APP_ID']
APP_SECRET = os.environ['FEISHU_APP_SECRET']
BASE_TOKEN = os.environ['BASE_TOKEN']
TICKETS_TABLE = os.environ['TICKETS_TABLE']
PASSENGERS_TABLE = os.environ.get('PASSENGERS_TABLE', 'tbleF9mFy3Kfyo77')

def get_token():
    r = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': APP_ID, 'app_secret': APP_SECRET}, timeout=15)
    return r.json()['tenant_access_token']

def list_records(token, table_id):
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
        return datetime.fromtimestamp(v/1000).strftime('%Y-%m-%d %H:%M')
    return str(v)

token = get_token()
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
