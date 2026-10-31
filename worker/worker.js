// Посредник между сайтом-тренажёром и Claude API.
// Ключ API хранится здесь, в секрете Worker (API_KEY), и никогда не попадает на страницу.
// Сайт шлёт обычный запрос Messages API; посредник оставляет из него только сообщения
// и формат ответа, сам подставляет модель, ключ и потолок max_tokens.
//
// Переменные Worker (Settings → Variables and Secrets):
//   API_KEY          секрет, ключ API (обязательно)
//   ACCESS_CODE      секрет, код доступа; если не задан, посредник открыт для сайта всем
//   ALLOWED_ORIGINS  адреса сайтов через запятую (по умолчанию https://vioriah.github.io)
//   MODEL            модель (по умолчанию claude-sonnet-5-5)
//   UPSTREAM         адрес API (по умолчанию https://api.anthropic.com); для ключа стороннего
//                    сервиса — его адрес, совместимый с Anthropic Messages API
//   MAX_TOKENS       потолок ответа (по умолчанию 8000)
// Необязательная привязка LIMITER (Rate limiting) ограничивает частоту запросов с одного IP.
//
// Раздел «Музыка» (полные тексты песен — только для студентов курса):
//   MUSIC            привязка KV-хранилища, где лежат песни (ключ song:<id>, значение — JSON песни)
//   STUDENT_CODES    секрет, личные коды студентов: «Имя=код» через точку с запятой или с новой строки
//   ADMIN_CODE       секрет, код преподавателя: загрузка песен и разметка времени строк
// Каждый запрос к песне пишется в журнал воркера (Observability → Logs): кто и что открывал.

const MAX_BODY = 64 * 1024;
const MAX_MESSAGES = 40;
const MAX_SONG = 200 * 1024;

// Имя студента по коду или null; код преподавателя тоже открывает раздел.
function student(env, code) {
  if (!code) return null;
  if (env.ADMIN_CODE && code === env.ADMIN_CODE) return 'преподаватель';
  for (const part of String(env.STUDENT_CODES || '').split(/[;\n]/)) {
    const i = part.lastIndexOf('=');
    if (i > 0 && part.slice(i + 1).trim() === code) return part.slice(0, i).trim();
  }
  return null;
}

async function music(req, env, path, fail, ok) {
  if (!env.MUSIC) return fail(500, 'api_error', 'В посреднике не подключено хранилище MUSIC.');
  const who = student(env, req.headers.get('x-student-code'));
  if (!who) return fail(401, 'authentication_error', 'Неверный личный код.');
  if (req.method === 'GET' && path === '/music/list') {
    const { keys } = await env.MUSIC.list({ prefix: 'song:' });
    console.log('music list', who);
    return ok({ who, songs: keys.map(k => ({ id: k.name.slice(5), ...(k.metadata || {}) })) });
  }
  const m = path.match(/^\/music\/song\/([a-z0-9-]{1,60})$/);
  if (req.method === 'GET' && m) {
    const song = await env.MUSIC.get('song:' + m[1]);
    if (!song) return fail(404, 'not_found_error', 'Песня не найдена.');
    console.log('music song', who, m[1]);
    return new Response(song, { headers: { 'content-type': 'application/json' } });
  }
  if (req.method === 'POST' && path === '/music/admin/song') {
    if (!env.ADMIN_CODE || req.headers.get('x-student-code') !== env.ADMIN_CODE) return fail(403, 'permission_error', 'Нужен код преподавателя.');
    const text = await req.text();
    if (text.length > MAX_SONG) return fail(413, 'request_too_large', 'Слишком большая песня.');
    let song;
    try { song = JSON.parse(text); } catch { return fail(400, 'invalid_request_error', 'Это не JSON.'); }
    if (!/^[a-z0-9-]{1,60}$/.test(song.id || '') || !song.title || !/^[\w-]{11}$/.test(song.yt || '') || !Array.isArray(song.lines) || !song.lines.length)
      return fail(400, 'invalid_request_error', 'Нужны поля id (латиница, цифры, дефис), title, yt (11 знаков id ролика) и непустой lines.');
    await env.MUSIC.put('song:' + song.id, JSON.stringify(song), { metadata: { title: song.title, artist: song.artist || '', year: song.year || '' } });
    console.log('music save', song.id, song.lines.length, 'строк');
    return ok({ saved: song.id, lines: song.lines.length });
  }
  return fail(404, 'not_found_error', 'Нет такого адреса.');
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get('origin') || '';
    const allowed = (env.ALLOWED_ORIGINS || 'https://vioriah.github.io').split(',').map(s => s.trim()).filter(Boolean);
    const cors = {
      'access-control-allow-origin': allowed.includes(origin) ? origin : allowed[0],
      'access-control-allow-methods': 'GET, POST, OPTIONS',
      'access-control-allow-headers': req.headers.get('access-control-request-headers') || 'content-type, x-access-code',
      'access-control-max-age': '86400',
      vary: 'origin',
    };
    const fail = (status, type, message) =>
      Response.json({ type: 'error', error: { type, message } }, { status, headers: cors });

    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    const path = new URL(req.url).pathname;
    if (path.startsWith('/music/')) {
      if (!allowed.includes(origin)) return fail(403, 'permission_error', 'Запросы принимаются только с сайта тренажёра.');
      const res = await music(req, env, path, fail, data => Response.json(data, { headers: cors }));
      const out = new Headers(res.headers); for (const [k, v] of Object.entries(cors)) out.set(k, v);
      out.set('cache-control', 'no-store');
      return new Response(res.body, { status: res.status, headers: out });
    }
    if (req.method !== 'POST' || path !== '/v1/messages') return fail(404, 'not_found_error', 'Нет такого адреса.');
    if (!allowed.includes(origin)) return fail(403, 'permission_error', 'Запросы принимаются только с сайта тренажёра.');
    if (env.ACCESS_CODE && req.headers.get('x-access-code') !== env.ACCESS_CODE) return fail(401, 'authentication_error', 'Неверный код доступа.');
    if (!env.API_KEY) return fail(500, 'api_error', 'В посреднике не задан секрет API_KEY.');
    if (env.LIMITER) {
      const { success } = await env.LIMITER.limit({ key: req.headers.get('cf-connecting-ip') || 'unknown' });
      if (!success) return fail(429, 'rate_limit_error', 'Слишком много запросов, подождите минуту.');
    }

    const text = await req.text();
    if (text.length > MAX_BODY) return fail(413, 'request_too_large', 'Слишком длинный запрос.');
    let incoming;
    try { incoming = JSON.parse(text); } catch { return fail(400, 'invalid_request_error', 'Запрос не в формате JSON.'); }
    if (!Array.isArray(incoming.messages) || !incoming.messages.length || incoming.messages.length > MAX_MESSAGES)
      return fail(400, 'invalid_request_error', 'Неверный список сообщений.');

    const upstream = (env.UPSTREAM || 'https://api.anthropic.com').replace(/\/+$/, '');
    const official = upstream === 'https://api.anthropic.com';
    const body = {
      model: env.MODEL || 'claude-sonnet-5-5',
      max_tokens: Math.min(Number(incoming.max_tokens) || 4000, Number(env.MAX_TOKENS) || 8000),
      messages: incoming.messages,
    };
    if (incoming.output_config) body.output_config = incoming.output_config;
    const headers = { 'content-type': 'application/json', 'anthropic-version': '2023-06-01', 'x-api-key': env.API_KEY };
    if (official) {
      // Если Claude откажется отвечать, Anthropic сам повторит запрос на запасной модели.
      body.fallbacks = 'default';
      headers['anthropic-beta'] = 'server-side-fallback-2026-07-01';
    } else {
      headers.authorization = 'Bearer ' + env.API_KEY;  // сторонние сервисы чаще ждут ключ здесь
    }

    let res;
    try {
      res = await fetch(upstream + '/v1/messages', { method: 'POST', headers, body: JSON.stringify(body) });
    } catch {
      return fail(502, 'api_error', 'Посредник не смог связаться с API.');
    }
    // Отказ по ключу владельца — не вина посетителя: отдаём как сбой сервера, а не «неверный код».
    if (res.status === 401 || res.status === 403) return fail(502, 'api_error', 'API не принял ключ посредника.');
    const out = new Headers(cors);
    out.set('content-type', res.headers.get('content-type') || 'application/json');
    return new Response(res.body, { status: res.status, headers: out });
  },
};
