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
//   STUDENT_CODES    секрет, личные коды студентов: «Имя=код» (или просто «код») через ; , или с новой строки
//   ADMIN_CODE       секрет, код преподавателя: загрузка песен и разметка времени строк
// Каждый запрос к песне пишется в журнал воркера (Observability → Logs): кто и что открывал.
//
// Раздел «Кино» (фильмы из закрытого хранилища Backblaze B2; разбор фильма лежит в MUSIC, как песни):
//   B2_KEY_ID, B2_APP_KEY  секреты, ключ приложения B2 только для чтения
//   B2_BUCKET              имя хранилища B2 с частями фильмов
// Студент по личному коду получает подпись на 6 часов; видео идёт через посредника (трафик B2 → Cloudflare),
// а без подписи части фильма не отдаются.

const MAX_BODY = 64 * 1024;
const MAX_MESSAGES = 40;
const MAX_SONG = 3 * 1024 * 1024;  // разбор полного фильма — до нескольких мегабайт
const FILM_TTL = 6 * 3600;          // сколько живёт подпись на просмотр фильма, с

// Коды сравниваются без пробелов, кавычек, невидимых символов и без учёта регистра; русские буквы,
// похожие на латинские (А, В, Е, К, М, Н, О, Р, С, Т, У, Х), считаются латинскими — на планшете
// код легко набрать то на одной, то на другой раскладке.
const LOOKALIKE = { А: 'A', В: 'B', Е: 'E', К: 'K', М: 'M', Н: 'H', О: 'O', Р: 'P', С: 'C', Т: 'T', У: 'Y', Х: 'X', Ё: 'E' };
// Код сравнивается терпимо: регистр, русские буквы-двойники, пробелы, дефисы и прочие знаки не важны,
// O и 0, I/L и 1 считаются одним знаком (на телефоне их легко перепутать).
const norm = c => String(c || '').toUpperCase().replace(/[АВЕКМНОРСТУХЁ]/g, ch => LOOKALIKE[ch])
  .replace(/[^0-9A-ZА-Я]/g, '').replace(/O/g, '0').replace(/[IL]/g, '1');
// Сайт присылает код в кодировке URL, чтобы проходили и русские буквы; старые клиенты — как есть.
const sentCode = req => { const raw = req.headers.get('x-student-code') || ''; try { return decodeURIComponent(raw); } catch { return raw; } };
const codeList = env => String(env.STUDENT_CODES || '').split(/[;,\n]/).filter(p => norm(p.slice(p.lastIndexOf('=') + 1)));
const isAdmin = (env, code) => !!env.ADMIN_CODE && !!norm(code) && norm(code) === norm(env.ADMIN_CODE);

// Имя студента по коду или null; код преподавателя тоже открывает раздел.
function student(env, code) {
  const c = norm(code);
  if (!c) return null;
  if (isAdmin(env, code)) return 'преподаватель';
  for (const part of codeList(env)) {
    const i = part.lastIndexOf('=');
    const name = i > 0 ? part.slice(0, i).replace(/["'«»]/g, '').trim() : 'студент';
    if (norm(i >= 0 ? part.slice(i + 1) : part) === c) return name || 'студент';
  }
  return null;
}

// Подпись ссылок на фильм: HMAC от «id.срок» на ключе, который знает только посредник.
async function sign(env, msg) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode('film:' + (env.B2_APP_KEY || '')), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(msg)));
  return btoa(String.fromCharCode(...sig)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// Доступ к закрытому хранилищу B2: токен живёт сутки, держим его в памяти воркера.
let B2 = null;
async function b2auth(env, force) {
  if (B2 && !force && B2.until > Date.now()) return B2;
  const r = await fetch('https://api.backblazeb2.com/b2api/v2/b2_authorize_account', { headers: { authorization: 'Basic ' + btoa(env.B2_KEY_ID + ':' + env.B2_APP_KEY) } });
  if (!r.ok) throw new Error('B2 не принял ключ: ' + r.status);
  const j = await r.json();
  B2 = { token: j.authorizationToken, url: j.downloadUrl, until: Date.now() + 20 * 3600e3 };
  return B2;
}

// Часть фильма: проверяем подпись и что файл действительно из этого фильма, затем отдаём из B2 с поддержкой перемотки (Range).
async function filmStream(req, env, id, file, url, fail) {
  const exp = Number(url.searchParams.get('exp'));
  if (!exp || exp < Date.now() / 1000 || url.searchParams.get('sig') !== await sign(env, id + '.' + exp)) return fail(403, 'permission_error', 'Ссылка на фильм устарела — откройте фильм заново.');
  const film = JSON.parse(await env.MUSIC.get('song:' + id) || 'null');
  if (!film?.parts?.some(p => p.file === file)) return fail(404, 'not_found_error', 'Нет такой части фильма.');
  const get = async force => {
    const b2 = await b2auth(env, force);
    const headers = { authorization: b2.token };
    if (req.headers.get('range')) headers.range = req.headers.get('range');
    return fetch(`${b2.url}/file/${encodeURIComponent(env.B2_BUCKET)}/${encodeURIComponent(file)}`, { headers });
  };
  let res;
  try { res = await get(false); if (res.status === 401) res = await get(true); }
  catch (e) { return fail(502, 'api_error', String(e.message || e)); }
  const out = new Headers();
  for (const h of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified']) if (res.headers.get(h)) out.set(h, res.headers.get(h));
  out.set('cache-control', 'private, max-age=3600');
  return new Response(res.body, { status: res.status, headers: out });
}

async function music(req, env, path, fail, ok) {
  if (!env.MUSIC) return fail(500, 'api_error', 'В посреднике не подключено хранилище MUSIC.');
  const who = student(env, sentCode(req));
  if (!who) {
    const n = codeList(env).length;
    // Показываем, как посредник понял введённый код, и длины кодов из списка (сами коды не раскрываются):
    // так видно, опечатка это или лишние символы в секрете.
    const got = norm(sentCode(req)), lens = codeList(env).map(p => norm(p.slice(p.lastIndexOf('=') + 1)).length).join(', ');
    console.log('music wrong code', got.length, 'list lengths', lens);
    return fail(401, 'authentication_error', n ? `Неверный личный код. Посредник понял его как «${got}» (${got.length} зн.). В списке студентов кодов: ${n}, их длина: ${lens} зн.` : 'Неверный личный код. Список кодов студентов пуст — проверьте секрет STUDENT_CODES.');
  }
  if (req.method === 'GET' && path === '/music/list') {
    const { keys } = await env.MUSIC.list({ prefix: 'song:' });
    console.log('music list', who);
    return ok({ who, songs: keys.map(k => ({ id: k.name.slice(5), ...(k.metadata || {}) })) });
  }
  const t = path.match(/^\/music\/ticket\/([a-z0-9-]{1,60})$/);
  if (req.method === 'GET' && t) {
    if (!env.B2_KEY_ID || !env.B2_APP_KEY || !env.B2_BUCKET) return fail(500, 'api_error', 'В посреднике не заданы секреты B2_KEY_ID, B2_APP_KEY и B2_BUCKET.');
    const exp = Math.floor(Date.now() / 1000) + FILM_TTL;
    console.log('film ticket', who, t[1]);
    return ok({ exp, sig: await sign(env, t[1] + '.' + exp) });
  }
  const m = path.match(/^\/music\/song\/([a-z0-9-]{1,60})$/);
  if (req.method === 'GET' && m) {
    const song = await env.MUSIC.get('song:' + m[1]);
    if (!song) return fail(404, 'not_found_error', 'Песня не найдена.');
    console.log('music song', who, m[1]);
    return new Response(song, { headers: { 'content-type': 'application/json' } });
  }
  if (req.method === 'POST' && path === '/music/admin/song') {
    if (!isAdmin(env, sentCode(req))) return fail(403, 'permission_error', 'Нужен код преподавателя.');
    const text = await req.text();
    if (text.length > MAX_SONG) return fail(413, 'request_too_large', 'Слишком большая песня.');
    let song;
    try { song = JSON.parse(text); } catch { return fail(400, 'invalid_request_error', 'Это не JSON.'); }
    const film = Array.isArray(song.parts) && song.parts.length && song.parts.every(p => typeof p.file === 'string' && p.file);
    if (!/^[a-z0-9-]{1,60}$/.test(song.id || '') || !song.title || !(film || /^[\w-]{11}$/.test(song.yt || '')) || !Array.isArray(song.lines) || !song.lines.length)
      return fail(400, 'invalid_request_error', 'Нужны поля id (латиница, цифры, дефис), title, lines и либо yt (11 знаков id ролика), либо parts (части фильма в B2).');
    await env.MUSIC.put('song:' + song.id, JSON.stringify(song), { metadata: { title: song.title, artist: song.artist || '', year: song.year || '', kind: film ? 'film' : 'song' } });
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
    const url = new URL(req.url), path = url.pathname;
    // Видео запрашивает сам тег <video> — без заголовка Origin, поэтому здесь доступ проверяется по подписи.
    const fs = path.match(/^\/film\/([a-z0-9-]{1,60})\/([^/]{1,200})$/);
    if (fs && (req.method === 'GET' || req.method === 'HEAD')) {
      if (!env.MUSIC || !env.B2_BUCKET) return fail(500, 'api_error', 'Кино не настроено в посреднике.');
      return filmStream(req, env, fs[1], decodeURIComponent(fs[2]), url, fail);
    }
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
