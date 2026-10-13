# J09: 讀取 data/pending-paid.json -> 換 tenant_access_token -> 更新飛書「Y HK$」
# -> 寫 push-status.json + 清空 pending（防循環：下次觸發讀到空就 exit）
import base64
import json
import os
import urllib.request
from datetime import datetime, timezone

REPO = "hkharrycheng/cathay-tools"
BRANCH = "main"
BASE_TOKEN = "C2x4byTkEaN3Ths9FXwcagDSn5e"
TABLE_ID = "tbl97F6lmemjat8V"
FIELD_PAID = "Y HK$"

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
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


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
            resp = lark_call(
                "https://open.feishu.cn/open-apis/base/v3/bases/%s/tables/%s/records/%s" % (BASE_TOKEN, TABLE_ID, rid),
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
            errors.append("%s: %s" % (rid, e))

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
