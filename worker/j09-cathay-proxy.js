// j09-cathay-proxy
// Cloudflare Worker for Cathay Staff Tickets (J09)
// - GET  /api/health          → ping
// - POST /api/paid            → { records: { <record_id>: <yHk> }, updatedAt: iso }
//                                Updates Tickets table "Y HK$" (number)
//
// Auth (ref J14 pattern): supports FEISHU_PAT first, then app_id/app_secret
// Secrets (wrangler secret put):
//   FEISHU_PAT         = <Personal Access Token, preferred>
//   FEISHU_APP_ID      = <app id, fallback>
//   FEISHU_APP_SECRET  = <app secret, fallback>
//
// Env vars:
//   BASE_TOKEN   = C2x4byTkEaN3Ths9FXwcagDSn5e
//   TICKETS_TABLE = tbl97F6lmemjat8V
//   Y_HK_FIELD   = "Y HK$"
//   CORS_ORIGIN  = https://hkharrycheng.github.io
//   GITHUB_TOKEN = <PAT with repo scope>  (for dispatching regen workflow)
//   GITHUB_REPO  = hkharrycheng/cathay-tools

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// ---- raw snapshot: 用 Worker 的 FEISHU_PAT 抓四張表，寫入 repo 供 Actions 離線重生 ----
function b64utf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 8192) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  }
  return btoa(bin);
}

async function listRecords(env, token, tableId) {
  const out = [];
  let pageToken = '';
  for (let guard = 0; guard < 40; guard++) {
    let u = `https://open.feishu.cn/open-apis/bitable/v1/apps/${env.BASE_TOKEN}/tables/${tableId}/records?page_size=100`;
    if (pageToken) u += '&page_token=' + encodeURIComponent(pageToken);
    const r = await fetch(u, {
      headers: { 'Authorization': 'Bearer ' + token, 'User-Agent': 'j09-cathay-proxy' },
    });
    const j = await r.json();
    if (j.code !== 0) throw new Error('list ' + tableId + ': ' + (j.msg || j.code));
    out.push(...((j.data && j.data.items) || []));
    if (j.data && j.data.has_more) pageToken = j.data.page_token; else break;
  }
  return out;
}

async function ghPutFile(env, path, text, message) {
  const base = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`;
  const headers = {
    'Authorization': 'Bearer ' + env.GITHUB_TOKEN,
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'j09-cathay-proxy',
  };
  let sha = null;
  const g = await fetch(base + '?ref=main', { headers });
  if (g.ok) sha = (await g.json()).sha;
  else if (g.status !== 404) return { ok: false, status: g.status, path };
  const body = { message, branch: 'main', content: b64utf8(text) };
  if (sha) body.sha = sha;
  const p = await fetch(base, { method: 'PUT', headers, body: JSON.stringify(body) });
  if (!p.ok) {
    let d = '';
    try { d = (await p.text()).slice(0, 200); } catch (e) { d = ''; }
    return { ok: false, status: p.status, detail: d, path };
  }
  const j = await p.json();
  return { ok: true, path, sha: j.content && j.content.sha };
}

async function dispatchRegen(env) {
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) return { skipped: 'no github config' };
  try {
    const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/regen-cathay.yml/dispatches`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + env.GITHUB_TOKEN,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'j09-cathay-proxy',
      },
      body: JSON.stringify({ ref: 'main' }),
    });
    if (r.ok) return { dispatched: true, status: r.status };
    let detail = '';
    try { detail = (await r.text()).slice(0, 200); } catch (e) { detail = ''; }
    return { dispatched: false, status: r.status, detail: detail };
  } catch (e) {
    return { dispatched: false, error: e.message };
  }
}

async function getFeishuToken(env) {
  if (env.FEISHU_PAT) return env.FEISHU_PAT;
  // Fallback: app_id + app_secret → tenant_access_token
  if (env.FEISHU_APP_ID && env.FEISHU_APP_SECRET) {
    const r = await fetch('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: env.FEISHU_APP_ID, app_secret: env.FEISHU_APP_SECRET }),
    });
    const j = await r.json();
    if (j.code !== 0) throw new Error('tenant_token: ' + (j.msg || j.code));
    return j.tenant_access_token;
  }
  throw new Error('No FEISHU_PAT or FEISHU_APP_ID/SECRET configured');
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === 'OPTIONS') return new Response('', { headers: CORS });

    if (url.pathname === '/api/health') {
      return new Response(JSON.stringify({ ok: true, ts: Date.now() }), {
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname === '/api/refresh' && req.method === 'POST') {
      // 1) 抓飛書四張表做 raw 快照；2) 推 repo；3) 觸發 Actions 用快照重生 JSON
      if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) {
        return new Response(JSON.stringify({ ok: false, error: 'Worker 未設定 GITHUB_TOKEN／GITHUB_REPO' }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }
      let token;
      try { token = await getFeishuToken(env); }
      catch (e) { return new Response(JSON.stringify({ ok: false, error: '飛書認證失敗：' + e.message }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } }); }

      const tables = {
        [env.TICKETS_TABLE || 'tbl97F6lmemjat8V']: 'tickets',
        [env.PASSENGERS_TABLE || 'tbleF9mFy3Kfyo77']: 'passengers',
        [env.PLAN_TABLE || 'tblQEnksbXxP2Wa8']: 'plan',
        [env.REQ_TABLE || 'tblsRYPi1RrCfokq']: 'req',
      };
      const snap = { generatedAt: new Date().toISOString(), baseToken: env.BASE_TOKEN, tables: {} };
      const counts = {};
      try {
        for (const tid of Object.keys(tables)) {
          snap.tables[tid] = await listRecords(env, token, tid);
          counts[tables[tid]] = snap.tables[tid].length;
        }
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: '讀飛書失敗：' + e.message }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }

      const put = await ghPutFile(env, 'data/feishu_raw.json', JSON.stringify(snap), 'chore: refresh feishu raw snapshot for regen');
      if (!put.ok) {
        return new Response(JSON.stringify({ ok: false, error: '寫入 raw 快照失敗（HTTP ' + put.status + '）', put }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }

      const d = await dispatchRegen(env);
      const failed = d.skipped || !d.dispatched;
      let err = null;
      if (d.skipped) err = 'Worker 未設定 GITHUB_TOKEN／GITHUB_REPO';
      else if (!d.dispatched) err = 'GitHub dispatch 失敗（HTTP ' + (d.status || '?') + '）' + (d.detail || d.error ? '：' + (d.detail || d.error) : '');
      return new Response(JSON.stringify({ ok: !failed, error: err, counts, put, ...d }), {
        status: failed ? 500 : 200,
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname === '/api/paid' && req.method === 'POST') {
      let body;
      try { body = await req.json(); } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: 'bad json' }), { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }
      const records = body.records || {};
      const ids = Object.keys(records);
      if (!ids.length) return new Response(JSON.stringify({ ok: false, error: 'empty records' }), { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });

      let token;
      try { token = await getFeishuToken(env); }
      catch (e) { return new Response(JSON.stringify({ ok: false, error: 'auth failed: ' + e.message }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } }); }

      let ok = 0, fail = 0;
      const errors = [];
      for (const rid of ids) {
        const v = Number(records[rid]);
        if (isNaN(v) || v < 0) { fail++; errors.push(rid + ': bad value'); continue; }
        try {
          const r = await fetch(
            `https://open.feishu.cn/open-apis/bitable/v1/apps/${env.BASE_TOKEN}/tables/${env.TICKETS_TABLE}/records/${rid}`,
            {
              method: 'PUT',
              headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
              body: JSON.stringify({ fields: { [env.Y_HK_FIELD]: v } }),
            });
          const j = await r.json();
          if (j.code === 0) ok++;
          else { fail++; errors.push(rid + ': ' + (j.msg || j.code)); }
        } catch (e) { fail++; errors.push(rid + ': ' + e.message); }
      }
      // After successful push, auto-trigger cathay.json regeneration
      let regen = { skipped: 'no records pushed' };
      if (ok > 0) {
        regen = await dispatchRegen(env);
      }
      return new Response(JSON.stringify({ ok, fail, errors: errors.slice(0, 10), updatedAt: new Date().toISOString(), regen }), {
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname === '/api/plan-status' && req.method === 'POST') {
      let body;
      try { body = await req.json(); } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: 'bad json' }), { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }
      const records = body.records || {};
      const ids = Object.keys(records);
      if (!ids.length) return new Response(JSON.stringify({ ok: false, error: 'empty records' }), { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });

      let token;
      try { token = await getFeishuToken(env); }
      catch (e) { return new Response(JSON.stringify({ ok: false, error: 'auth failed: ' + e.message }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } }); }

      const allowed = ['Completed', 'Pending'];
      const planTable = env.PLAN_TABLE || 'tblQEnksbXxP2Wa8';
      const statusField = env.PLAN_STATUS_FIELD || '\u72c0\u614b';

      let ok = 0, fail = 0;
      const errors = [];
      for (const rid of ids) {
        const v = String(records[rid]);
        if (allowed.indexOf(v) < 0) { fail++; errors.push(rid + ': bad status ' + v); continue; }
        try {
          const r = await fetch(
            `https://open.feishu.cn/open-apis/bitable/v1/apps/${env.BASE_TOKEN}/tables/${planTable}/records/${rid}`,
            {
              method: 'PUT',
              headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
              body: JSON.stringify({ fields: { [statusField]: v } }),
            });
          const j = await r.json();
          if (j.code === 0) ok++;
          else { fail++; errors.push(rid + ': ' + (j.msg || j.code)); }
        } catch (e) { fail++; errors.push(rid + ': ' + e.message); }
      }
      return new Response(JSON.stringify({ ok, fail, errors: errors.slice(0, 10), updatedAt: new Date().toISOString() }), {
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }

    // v1.20: 行程改天數 / 時間 → 寫回「計劃行程」表（天數 + 時間 兩欄）
    if (url.pathname === '/api/plan-edit' && req.method === 'POST') {
      let body;
      try { body = await req.json(); } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: 'bad json' }), { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }
      const records = body.records || {};
      const ids = Object.keys(records);
      if (!ids.length) return new Response(JSON.stringify({ ok: false, error: 'empty records' }), { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });

      let token;
      try { token = await getFeishuToken(env); }
      catch (e) { return new Response(JSON.stringify({ ok: false, error: 'auth failed: ' + e.message }), { status: 500, headers: { ...CORS, 'Content-Type': 'application/json' } }); }

      const planTable = env.PLAN_TABLE || 'tblQEnksbXxP2Wa8';
      const dayField = env.PLAN_DAY_FIELD || '\u5929\u6578';
      const timeField = env.PLAN_TIME_FIELD || '\u6642\u9593';

      let ok = 0, fail = 0;
      const errors = [];
      for (const rid of ids) {
        const rec = records[rid] || {};
        const day = String(rec.day || '');
        const time = String(rec.time || '');
        if (!/^\u7b2c[1-9]\u5929$/.test(day)) { fail++; errors.push(rid + ': bad day ' + day); continue; }
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) { fail++; errors.push(rid + ': bad time ' + time); continue; }
        try {
          const r = await fetch(
            `https://open.feishu.cn/open-apis/bitable/v1/apps/${env.BASE_TOKEN}/tables/${planTable}/records/${rid}`,
            {
              method: 'PUT',
              headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
              body: JSON.stringify({ fields: { [dayField]: day, [timeField]: time } }),
            });
          const j = await r.json();
          if (j.code === 0) ok++;
          else { fail++; errors.push(rid + ': ' + (j.msg || j.code)); }
        } catch (e) { fail++; errors.push(rid + ': ' + e.message); }
      }
      return new Response(JSON.stringify({ ok, fail, errors: errors.slice(0, 10), updatedAt: new Date().toISOString() }), {
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }

    return new Response('not found', { status: 404, headers: CORS });
  },
};
