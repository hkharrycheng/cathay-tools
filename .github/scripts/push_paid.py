# J09: 讀取 data/pending-paid.json -> 換 tenant_access_token -> 更新飛書「Y HK$」
# -> 自動重生 cathay.json（version +0.01，用飛書最新數據）-> 寫 push-status.json + 清空 pending
# v2 (2026-10-13): 新增 sync_cathay_json —— 飛書更新後自動重生 cathay.json，HTML refresh 即時見最新數據
import base64
import json
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta

REPO = "hkharrycheng/cathay-tools"
BRANCH = "main"
BASE_TOKEN = "C2x4byTkEaN3Ths9FXwcagDSn5e"
TABLE_ID = "tbl97F6lmemjat8V"
PASSENGERS_TABLE = "tblxBC2f3i4L3Khh"
DASHBOARD_ID = "blkEYDQV9iBTideY"
FIELD_PAID = "Y HK$"
HK_TZ = timezone(timedelta(hours=8))

UA = "HIS-Tools-Agent"


def gh_headers():
    return {
        "Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""),
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
    }


def gh_get(path):
    url = "https://api.github.com/repos/%s/contents/%s" % (REPO, path)
    req = urllib.request.Request(url, headers=gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def gh_put(path, content_str, msg):
    url = "https://api.github.com/repos/%s/contents/%s" % (REPO, path)
    data = {
        "message": msg,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    existing = gh_get(path)
    if existing and existing.get("sha"):
        data["sha"] = existing["sha"]
    body = json.dumps(data).encode("utf-8")
    headers = gh_headers()
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method="PUT", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def lark_call(url, payload, token=None, method="POST"):
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if token:
        headers["Authorization"] = "Bearer " + token
    if method == "GET":
        req = urllib.request.Request(url, method="GET", headers=headers)
    else:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def lark_list_all(token, table_id):
    """bitable v1 list records 全頁（page_token 循環）"""
    items = []
    page_token = ""
    while True:
        url = "https://open.feishu.cn/open-apis/bitable/v1/apps/%s/tables/%s/records" % (BASE_TOKEN, table_id)
        if page_token:
            url += "?page_token=" + page_token
        r = lark_call(url, {}, token=token, method="GET")
        if r.get("code") != 0:
            raise Exception("list fail %s %s" % (r.get("code"), r.get("msg")))
        data = r.get("data", {})
        items.extend(data.get("items", []))
        if data.get("has_more"):
            page_token = data.get("page_token", "")
        else:
            break
    return items


# ---- cell 轉換（處理飛書 API 默認 JSON 形態）----

def s(v):
    """text：list 只保留非 dict 元素"""
    if v is None:
        return ""
    if isinstance(v, list):
        return "".join(str(x) for x in v if not isinstance(x, dict))
    return str(v)


def n(v):
    """number：int/float/含 HK$ 逗號字符串 -> float"""
    if v is None or v == "":
        return None
    if isinstance(v, list):
        if not v:
            return None
        v = v[0]
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("HK$", "").replace("$", "").strip())
    except Exception:
        return None


def opt(v):
    """select：單選返回字符串 / 多選返回數組 -> 攞第一個"""
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v)


def link_ids(v):
    """link 字段：默認 [{"record_ids":[..]}] / [{"id":..}] / ["id"] -> id 列表"""
    if not v:
        return []
    if isinstance(v, list):
        ids = []
        for item in v:
            if isinstance(item, dict):
                if "record_ids" in item:
                    ids.extend(item.get("record_ids", []) or [])
                elif "id" in item:
                    ids.append(item.get("id"))
            else:
                ids.append(str(item))
        return ids
    return [str(v)]


def link_texts(v):
    """link 字段：直接攞 text_arr（關聯記錄顯示名），最可靠"""
    if not v:
        return []
    if isinstance(v, list):
        out = []
        for item in v:
            if isinstance(item, dict):
                out.extend(item.get("text_arr", []) or [])
            elif item:
                out.append(str(item))
        return out
    return [str(v)] if v else []


def ts(v):
    """datetime：毫秒 timestamp 或 ISO 字符串 -> 'YYYY-MM-DD HH:MM'（香港時區）"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v / 1000, tz=HK_TZ).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", str(v))
    if m:
        return m.group(1) + " " + m.group(2)
    return str(v)


# ---- 重生 cathay.json ----

def sync_cathay_json(token):
    """讀飛書全部 record -> 重生 cathay.json（version +0.01）-> 上傳"""
    try:
        # 現有 version
        version = 1.00
        cur = gh_get("cathay.json")
        if cur and cur.get("content"):
            try:
                old = json.loads(base64.b64decode(cur["content"]).decode("utf-8"))
                version = float(old.get("version", "1.00"))
            except Exception:
                pass
        new_version = round(version + 0.01, 2)

        # 乘客
        p_map = {}
        passengers = []
        for it in lark_list_all(token, PASSENGERS_TABLE):
            f = it.get("fields", {})
            rid = it.get("record_id", "")
            print("RAWPAX %s fields-keys=%s DisplayName=%r" % (rid, list(f.keys()), f.get("DisplayName")))
            name = s(f.get("DisplayName"))
            p_map[rid] = name
            passengers.append({
                "id": rid,
                "name": name,
                "appName": s(f.get("Flight Load App Name")),
            })

        # 航班
        tickets = []
        for it in lark_list_all(token, TABLE_ID):
            f = it.get("fields", {})
            rid = it.get("record_id", "")
            pax_names = link_texts(f.get("Passengers"))
            tickets.append({
                "id": rid,
                "displayName": s(f.get("Display Name")),
                "flightNumber": s(f.get("Flight Number")),
                "from": s(f.get("From")),
                "to": s(f.get("To")),
                "startTime": ts(f.get("Start Time")),
                "endTime": ts(f.get("End Time")),
                "planeModel": s(f.get("Plane Model")),
                "capacity": n(f.get("Capacity")),
                "booked": n(f.get("Booked")),
                "checkedIn": n(f.get("Checked-In")),
                "bookedPercent": n(f.get("% Booked")),
                "p25": n(f.get("P25")),
                "p27": n(f.get("P27")),
                "p29": n(f.get("P29")),
                "p31": n(f.get("P31")),
                "p33": n(f.get("P33")),
                "noOfStaff": n(f.get("No. of Staff")),
                "staffPercent": n(f.get("% Staff")),
                "yHk": n(f.get("Y HK$")),
                "yListedHk": n(f.get("Y Listed HK$")),
                "yMilesHk": n(f.get("Y Miles HK$")),
                "discount": n(f.get("Discount %")),
                "asiaMilesUsed": n(f.get("Asia Miles Used")),
                "finalStatus": opt(f.get("Final Status")),
                "finalStatusProb": n(f.get("Final Status Prob")),
                "rollingProb": n(f.get("Rolling Final Status Prob")),
                "outport": s(f.get("Outport Location")),
                "passengers": pax_names,
            })

        # 統計（與 gen_cathay_json.py 一致）
        with_status = [t for t in tickets if t["finalStatus"] is not None]
        accepted = [t for t in with_status if t["finalStatus"] == "Accepted"]

        booked_vals = [t["bookedPercent"] for t in with_status if t["bookedPercent"] is not None]
        staff_pct_vals = [t["staffPercent"] for t in with_status if t["staffPercent"] is not None]
        discount_vals = [t["discount"] for t in with_status if t["discount"] is not None]
        staff_count_vals = [t["noOfStaff"] for t in with_status if t["noOfStaff"] is not None]

        avg_booked = sum(booked_vals) / len(booked_vals) if booked_vals else 0
        avg_staff_pct = sum(staff_pct_vals) / len(staff_pct_vals) if staff_pct_vals else 0
        avg_discount = sum(discount_vals) / len(discount_vals) if discount_vals else 0
        avg_staff_count = sum(staff_count_vals) / len(staff_count_vals) if staff_count_vals else 0

        status_dist = {}
        for t in with_status:
            st = t["finalStatus"]
            status_dist[st] = status_dist.get(st, 0) + 1

        rolling = sorted(
            [{"time": t["startTime"], "prob": t["rollingProb"]} for t in tickets
             if t["startTime"] and t["rollingProb"] is not None],
            key=lambda x: x["time"],
        )
        staff_trend = sorted(
            [{"time": t["startTime"], "staff": t["noOfStaff"]} for t in tickets
             if t["startTime"] and t["noOfStaff"] is not None],
            key=lambda x: x["time"],
        )

        now = datetime.now(tz=HK_TZ)
        upcoming = []
        for t in tickets:
            if t["startTime"]:
                try:
                    if datetime.strptime(t["startTime"], "%Y-%m-%d %H:%M").replace(tzinfo=HK_TZ) > now:
                        upcoming.append(t)
                except Exception:
                    pass
        upcoming.sort(key=lambda x: x["startTime"])

        result = {
            "version": "%.2f" % new_version,
            "lastUpdate": datetime.now(tz=HK_TZ).strftime("%Y-%m-%d %H:%M"),
            "source": {
                "baseToken": BASE_TOKEN,
                "ticketsTable": TABLE_ID,
                "passengersTable": PASSENGERS_TABLE,
                "dashboardId": DASHBOARD_ID,
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
                "statusDist": [{"status": k, "count": v} for k, v in status_dist.items()],
            },
            "rollingProb": rolling,
            "staffTrend": staff_trend,
            "upcoming": upcoming,
            "tickets": tickets,
            "passengers": passengers,
        }

        gh_put(
            "cathay.json",
            json.dumps(result, ensure_ascii=False, indent=2),
            "J09: auto sync cathay.json v%s" % new_version,
        )
        print("cathay.json synced v%s (tickets=%s, with_status=%s)" % (new_version, len(tickets), len(with_status)))
    except Exception as e:
        print("sync cathay.json FAIL:", e)


def main():
    print("J09 push-paid start")
    pend = gh_get("data/pending-paid.json")
    if not pend or not pend.get("content"):
        print("no pending file / empty; exit")
        return
    raw = base64.b64decode(pend["content"]).decode("utf-8")
    try:
        data = json.loads(raw)
    except Exception as e:
        print("bad json:", e)
        return
    records = data.get("records", {})
    if not records:
        print("no records; exit (avoid loop)")
        return

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("FEISHU_APP_ID / FEISHU_APP_SECRET not set in repo secrets")
        gh_put(
            "data/push-status.json",
            json.dumps(
                {"updatedAt": datetime.now(timezone.utc).isoformat(), "ok": 0, "fail": len(records),
                 "errors": ["repo secrets FEISHU_APP_ID / FEISHU_APP_SECRET not set"]},
                ensure_ascii=False,
            ),
            "J09: push status (secrets missing)",
        )
        return

    # 換 tenant token
    try:
        tr = lark_call(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
        )
    except Exception as e:
        print("token fetch fail:", e)
        return
    if tr.get("code") != 0:
        print("token fail:", tr.get("code"), tr.get("msg"))
        gh_put(
            "data/push-status.json",
            json.dumps(
                {"updatedAt": datetime.now(timezone.utc).isoformat(), "ok": 0, "fail": len(records),
                 "errors": ["tenant token fail: %s %s" % (tr.get("code"), tr.get("msg"))]},
                ensure_ascii=False,
            ),
            "J09: push status (token fail)",
        )
        return
    token = tr["tenant_access_token"]

    ok = 0
    fail = 0
    errors = []
    for rid, amt in records.items():
        try:
            # 先 GET 診斷：如果連 GET 都 404，即係 App 冇權限訪問呢個 base/table（未加入協作者）
            try:
                g = lark_call(
                    "https://open.feishu.cn/open-apis/bitable/v1/apps/%s/tables/%s/records/%s" % (BASE_TOKEN, TABLE_ID, rid),
                    {},
                    token=token,
                    method="GET",
                )
                print("GET %s code=%s" % (rid, g.get("code")))
                if g.get("code") != 0:
                    fail += 1
                    errors.append("%s GET: %s %s（App 可能未加入 Base 協作者）" % (rid, g.get("code"), g.get("msg")))
                    continue
            except Exception as ge:
                body_hint = ""
                if hasattr(ge, "read"):
                    try:
                        body_hint = " body=" + ge.read().decode("utf-8", "replace")[:300]
                    except Exception:
                        pass
                fail += 1
                errors.append("%s GET fail: %s%s（App 可能未加入 Base 協作者）" % (rid, ge, body_hint))
                print("GET ERR %s: %s%s" % (rid, ge, body_hint))
                continue
            resp = lark_call(
                "https://open.feishu.cn/open-apis/bitable/v1/apps/%s/tables/%s/records/%s" % (BASE_TOKEN, TABLE_ID, rid),
                {"fields": {FIELD_PAID: float(amt)}},
                token=token,
                method="PUT",
            )
            if resp.get("code") == 0:
                ok += 1
            else:
                fail += 1
                errors.append("%s: %s %s" % (rid, resp.get("code"), resp.get("msg")))
        except Exception as e:
            fail += 1
            body_hint = ""
            if hasattr(e, "read"):
                try:
                    body_hint = " body=" + e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
            errors.append("%s: %s%s" % (rid, e, body_hint))
            print("ERR %s: %s%s" % (rid, e, body_hint))

    # 飛書更新完成 -> 自動重生 cathay.json（方案 A：Actions 自動 sync）
    sync_cathay_json(token)

    # 寫 status
    status = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "fail": fail,
        "errors": errors[:10],
    }
    gh_put(
        "data/push-status.json",
        json.dumps(status, ensure_ascii=False),
        "J09: push status update (%s ok / %s fail)" % (ok, fail),
    )
    # 清空 pending（呢個 push 會再觸發 workflow，但下次讀到空直接 exit）
    gh_put(
        "data/pending-paid.json",
        json.dumps({"records": {}, "updatedAt": data.get("updatedAt", "")}, ensure_ascii=False),
        "J09: clear pending after push",
    )
    print("done ok=%s fail=%s" % (ok, fail))


if __name__ == "__main__":
    main()
