// Worker for Joshua Moy's Expert NFL Picks (a static GitHub Pages site).
//
// The site can't hold secrets, so this small server does the two things that need one:
//   /yahoo/login, /yahoo/callback, /yahoo/refresh  Sign in with Yahoo (OAuth 2.0). Tokens go back to the browser
//                                                 in the page address fragment, which never reaches a server.
//   /yahoo/api?path=...                           Read-only Yahoo Fantasy API calls, passed through with CORS.
//   /chat                                         The AI chat, answered by Google Gemini with the site's context.
// Only the site's own origin may call it.

const YAHOO_AUTH = "https://api.login.yahoo.com/oauth2/request_auth";
const YAHOO_TOKEN = "https://api.login.yahoo.com/oauth2/get_token";
const YAHOO_API = "https://fantasysports.yahooapis.com/fantasy/v2/";

const SYSTEM = `You are the fantasy football and NFL betting assistant on "Joshua Moy's Expert NFL Picks".
Answer in plain, friendly language, short paragraphs or a few bullets. Use the numbers in the context below
(rest-of-season projections, trade values, rosters, injuries, matchups) and say when you're unsure.
Never use em dashes or en dashes. This is for fun, not financial advice.`;

function allowedOrigin(req, env) {
  const o = req.headers.get("Origin") || "";
  return o === env.SITE_ORIGIN || /^http:\/\/localhost(:\d+)?$/.test(o) ? o : null;
}

function cors(req, env, extra = {}) {
  const o = allowedOrigin(req, env);
  return {
    ...(o ? { "Access-Control-Allow-Origin": o, Vary: "Origin" } : {}),
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    ...extra,
  };
}

function json(req, env, body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: cors(req, env, { "Content-Type": "application/json" }) });
}

async function yahooToken(env, params, redirectUri) {
  const body = new URLSearchParams({ ...params, redirect_uri: redirectUri });
  const r = await fetch(YAHOO_TOKEN, {
    method: "POST",
    headers: { Authorization: `Basic ${btoa(`${env.YAHOO_CLIENT_ID}:${env.YAHOO_CLIENT_SECRET}`)}`, "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const d = await r.json();
  if (!r.ok || !d.access_token) throw new Error(d.error_description || d.error || `Yahoo token error ${r.status}`);
  return { access_token: d.access_token, refresh_token: d.refresh_token, expires_at: Date.now() + (d.expires_in || 3600) * 1000 };
}

const b64url = (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const callback = `${url.origin}/yahoo/callback`;
    if (req.method === "OPTIONS") return new Response(null, { headers: cors(req, env) });

    // ---- Yahoo sign-in
    if (url.pathname === "/yahoo/login") {
      const state = crypto.randomUUID();
      const to = new URL(YAHOO_AUTH);
      to.search = new URLSearchParams({ client_id: env.YAHOO_CLIENT_ID, redirect_uri: callback, response_type: "code", language: "en-us", state }).toString();
      return new Response(null, { status: 302, headers: { Location: to.toString(), "Set-Cookie": `ystate=${state}; Path=/yahoo; Max-Age=600; HttpOnly; Secure; SameSite=Lax` } });
    }
    if (url.pathname === "/yahoo/callback") {
      const state = url.searchParams.get("state");
      const cookie = (req.headers.get("Cookie") || "").match(/ystate=([\w-]+)/)?.[1];
      const back = new URL(env.SITE_URL);
      try {
        if (!state || state !== cookie) throw new Error("Sign-in expired, please try again.");
        const tokens = await yahooToken(env, { grant_type: "authorization_code", code: url.searchParams.get("code") || "" }, callback);
        back.hash = `#/league?yahoo=${b64url(JSON.stringify(tokens))}`;
      } catch (err) {
        back.hash = `#/league?yahoo_error=${encodeURIComponent(err.message)}`;
      }
      return new Response(null, { status: 302, headers: { Location: back.toString(), "Set-Cookie": "ystate=; Path=/yahoo; Max-Age=0" } });
    }
    if (!allowedOrigin(req, env)) return new Response("Forbidden", { status: 403 });

    if (url.pathname === "/yahoo/refresh" && req.method === "POST") {
      try {
        const { refresh_token } = await req.json();
        return json(req, env, await yahooToken(env, { grant_type: "refresh_token", refresh_token }, callback));
      } catch (err) {
        return json(req, env, { error: err.message }, 401);
      }
    }
    if (url.pathname === "/yahoo/api") {
      const path = url.searchParams.get("path") || "";
      if (!/^[\w;=,.\/-]+$/.test(path)) return json(req, env, { error: "bad path" }, 400);
      const r = await fetch(`${YAHOO_API}${path}${path.includes("?") ? "&" : "?"}format=json`, { headers: { Authorization: req.headers.get("Authorization") || "" } });
      return new Response(await r.text(), { status: r.status, headers: cors(req, env, { "Content-Type": "application/json" }) });
    }

    // ---- AI chat (Gemini)
    if (url.pathname === "/chat" && req.method === "POST") {
      if (!env.GEMINI_API_KEY) return json(req, env, { error: "The chat isn't set up yet." }, 503);
      let body;
      try { body = await req.json(); } catch { return json(req, env, { error: "bad request" }, 400); }
      const messages = (body.messages || []).slice(-16).map((m) => ({ role: m.role === "user" ? "user" : "model", parts: [{ text: String(m.text || "").slice(0, 4000) }] }));
      if (!messages.length || messages[messages.length - 1].role !== "user") return json(req, env, { error: "no question" }, 400);
      const context = String(body.context || "").slice(0, 12000);
      const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${env.GEMINI_MODEL}:generateContent`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: `${SYSTEM}\n\nContext from the site:\n${context}` }] },
          contents: messages,
          generationConfig: { maxOutputTokens: 1200, temperature: 0.6 },
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) return json(req, env, { error: d.error?.message || `Gemini error ${r.status}` }, r.status === 429 ? 429 : 502);
      const text = (d.candidates?.[0]?.content?.parts || []).map((p) => p.text || "").join("").trim();
      return json(req, env, { text: text || "Sorry, I couldn't come up with an answer to that." });
    }
    return new Response("Not found", { status: 404, headers: cors(req, env) });
  },
};
