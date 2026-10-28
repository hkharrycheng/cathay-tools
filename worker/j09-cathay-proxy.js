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

async function dispatchRegen(env) {
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) return { skipped: 'no github config' };
  try {
    const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/regen-cathay.yml/dispatches`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + env.GITHUB_TOKEN,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main' }),
    });
    return { dispatched: r.ok, status: r.status };
  } catch (e) {
    return { dispatched: false, error: e.message };
  }
}

async function getFeishuToken(env) {
  // Preferred: Personal Access Token (like J14)
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
      const d = await dispatchRegen(env);
      return new Response(JSON.stringify({ ok: true, ...d }), {
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

    return new Response('not found', { status: 404, headers: CORS });
  },
};
