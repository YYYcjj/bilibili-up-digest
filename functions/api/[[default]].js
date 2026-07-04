/**
 * B站UP主视频速览 - EdgeOne Pages Edge Functions
 * 处理所有 /api/* 路由请求
 */

// ── WBI 签名常量 ──
const MIXIN_KEY_ENC_TAB = [
  46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,
  27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,
  37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,
  22,25,54,21,56,59,6,63,57,62,11,36,20,52,44,34,
];

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const BILI_HEADERS = {
  'User-Agent': UA,
  'Referer': 'https://www.bilibili.com/',
};

// ── 全局状态（边缘函数实例内缓存） ──
let _publicCookies = '';
let _wbiCache = null;
let _wbiCacheTime = 0;
let _loginCookies = '';
let _loginInfo = null;

// ── MD5 实现（B站 WBI 签名需要） ──
function md5(str) {
  function rotateLeft(lValue, iShiftBits) {
    return (lValue << iShiftBits) | (lValue >>> (32 - iShiftBits));
  }
  function addUnsigned(lX, lY) {
    let lX8 = lX & 0x80000000, lY8 = lY & 0x80000000;
    let lX4 = lX & 0x40000000, lY4 = lY & 0x40000000;
    let lResult = (lX & 0x3FFFFFFF) + (lY & 0x3FFFFFFF);
    if (lX4 & lY4) return lResult ^ 0x80000000 ^ (lX8 & lY8 ? 0 : 0x80000000) ^ ((lX8 | lY8) ? 0 : 0x40000000);
    if (lX4 | lY4) return lResult ^ ((lResult & 0x40000000) ? 0xC0000000 : 0x40000000) ^ ((lX8 & lY8) ? 0x80000000 : 0);
    return lResult ^ ((lX8 & lY8) ? 0x80000000 : 0);
  }
  function f(x, y, z) { return (x & y) | ((~x) & z); }
  function g(x, y, z) { return (x & z) | (y & (~z)); }
  function h(x, y, z) { return x ^ y ^ z; }
  function i(x, y, z) { return y ^ (x | (~z)); }
  function ff(a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(f(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b); }
  function gg(a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(g(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b); }
  function hh(a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(h(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b); }
  function ii(a, b, c, d, x, s, ac) { a = addUnsigned(a, addUnsigned(addUnsigned(i(b, c, d), x), ac)); return addUnsigned(rotateLeft(a, s), b); }
  function convertToWordArray(str) {
    let lWordCount, lMessageLength = str.length, lNumberOfWords_temp1 = lMessageLength + 8, lNumberOfWords_temp2 = (lNumberOfWords_temp1 - (lNumberOfWords_temp1 % 64)) / 64;
    let lNumberOfWords = (lNumberOfWords_temp2 + 1) * 16;
    let lWordArray = new Array(lNumberOfWords - 1);
    let lBytePosition = 0, lByteCount = 0;
    while (lByteCount < lMessageLength) {
      lWordCount = (lByteCount - (lByteCount % 4)) / 4;
      lBytePosition = (lByteCount % 4) * 8;
      lWordArray[lWordCount] = (lWordArray[lWordCount] | (str.charCodeAt(lByteCount) << lBytePosition));
      lByteCount++;
    }
    lWordCount = (lByteCount - (lByteCount % 4)) / 4;
    lBytePosition = (lByteCount % 4) * 8;
    lWordArray[lWordCount] = lWordArray[lWordCount] | (0x80 << lBytePosition);
    lWordArray[lNumberOfWords - 2] = lMessageLength << 3;
    lWordArray[lNumberOfWords - 1] = lMessageLength >>> 29;
    return lWordArray;
  }
  function wordToHex(lValue) {
    let wordToHexValue = '', wordToHexValue_temp = '', lByte, lCount;
    for (lCount = 0; lCount <= 3; lCount++) {
      lByte = (lValue >>> (lCount * 8)) & 255;
      wordToHexValue_temp = '0' + lByte.toString(16);
      wordToHexValue = wordToHexValue + wordToHexValue_temp.substr(wordToHexValue_temp.length - 2, 2);
    }
    return wordToHexValue;
  }
  let x = convertToWordArray(str);
  let a = 0x67452301, b = 0xEFCDAB89, c = 0x98BADCFE, d = 0x10325476;
  for (let k = 0; k < x.length; k += 16) {
    let AA = a, BB = b, CC = c, DD = d;
    a = ff(a, b, c, d, x[k+0],  7, 0xD76AA478);
    d = ff(d, a, b, c, x[k+1], 12, 0xE8C7B756);
    c = ff(c, d, a, b, x[k+2], 17, 0x242070DB);
    b = ff(b, c, d, a, x[k+3], 22, 0xC1BDCEEE);
    a = ff(a, b, c, d, x[k+4],  7, 0xF57C0FAF);
    d = ff(d, a, b, c, x[k+5], 12, 0x4787C62A);
    c = ff(c, d, a, b, x[k+6], 17, 0xA8304613);
    b = ff(b, c, d, a, x[k+7], 22, 0xFD469501);
    a = ff(a, b, c, d, x[k+8],  7, 0x698098D8);
    d = ff(d, a, b, c, x[k+9], 12, 0x8B44F7AF);
    c = ff(c, d, a, b, x[k+10], 17, 0xFFFF5BB1);
    b = ff(b, c, d, a, x[k+11], 22, 0x895CD7BE);
    a = ff(a, b, c, d, x[k+12],  7, 0x6B901122);
    d = ff(d, a, b, c, x[k+13], 12, 0xFD987193);
    c = ff(c, d, a, b, x[k+14], 17, 0xA679438E);
    b = ff(b, c, d, a, x[k+15], 22, 0x49B40821);
    a = gg(a, b, c, d, x[k+1],  5, 0xF61E2562);
    d = gg(d, a, b, c, x[k+6],  9, 0xC040B340);
    c = gg(c, d, a, b, x[k+11], 14, 0x265E5A51);
    b = gg(b, c, d, a, x[k+0], 20, 0xE9B6C7AA);
    a = gg(a, b, c, d, x[k+5],  5, 0xD62F105D);
    d = gg(d, a, b, c, x[k+10],  9, 0x2441453);
    c = gg(c, d, a, b, x[k+15], 14, 0xD8A1E681);
    b = gg(b, c, d, a, x[k+4], 20, 0xE7D3FBC8);
    a = gg(a, b, c, d, x[k+9],  5, 0x21E1CDE6);
    d = gg(d, a, b, c, x[k+14],  9, 0xC33707D6);
    c = gg(c, d, a, b, x[k+3], 14, 0xF4D50D87);
    b = gg(b, c, d, a, x[k+8], 20, 0x455A14ED);
    a = gg(a, b, c, d, x[k+13],  5, 0xA9E3E905);
    d = gg(d, a, b, c, x[k+2],  9, 0xFCEFA3F8);
    c = gg(c, d, a, b, x[k+7], 14, 0x676F02D9);
    b = gg(b, c, d, a, x[k+12], 20, 0x8D2A4C8A);
    a = hh(a, b, c, d, x[k+5],  4, 0xFFFA3942);
    d = hh(d, a, b, c, x[k+8], 11, 0x8771F681);
    c = hh(c, d, a, b, x[k+11], 16, 0x6D9D6122);
    b = hh(b, c, d, a, x[k+14], 23, 0xFDE5380C);
    a = hh(a, b, c, d, x[k+1],  4, 0xA4BEEA44);
    d = hh(d, a, b, c, x[k+4], 11, 0x4BDECFA9);
    c = hh(c, d, a, b, x[k+7], 16, 0xF6BB4B60);
    b = hh(b, c, d, a, x[k+10], 23, 0xBEBFBC70);
    a = hh(a, b, c, d, x[k+13],  4, 0x289B7EC6);
    d = hh(d, a, b, c, x[k+0], 11, 0xEAA127FA);
    c = hh(c, d, a, b, x[k+3], 16, 0xD4EF3085);
    b = hh(b, c, d, a, x[k+6], 23, 0x4881D05);
    a = hh(a, b, c, d, x[k+9],  4, 0xD9D4D039);
    d = hh(d, a, b, c, x[k+12], 11, 0xE6DB99E5);
    c = hh(c, d, a, b, x[k+15], 16, 0x1FA27CF8);
    b = hh(b, c, d, a, x[k+2], 23, 0xC4AC5665);
    a = ii(a, b, c, d, x[k+0],  6, 0xF4292244);
    d = ii(d, a, b, c, x[k+7], 10, 0x432AFF97);
    c = ii(c, d, a, b, x[k+14], 15, 0xAB9423A7);
    b = ii(b, c, d, a, x[k+5], 21, 0xFC93A039);
    a = ii(a, b, c, d, x[k+12],  6, 0x655B59C3);
    d = ii(d, a, b, c, x[k+3], 10, 0x8F0CCC92);
    c = ii(c, d, a, b, x[k+10], 15, 0xFFEFF47D);
    b = ii(b, c, d, a, x[k+1], 21, 0x85845DD1);
    a = ii(a, b, c, d, x[k+8],  6, 0x6FA87E4F);
    d = ii(d, a, b, c, x[k+15], 10, 0xFE2CE6E0);
    c = ii(c, d, a, b, x[k+6], 15, 0xA3014314);
    b = ii(b, c, d, a, x[k+13], 21, 0x4E0811A1);
    a = ii(a, b, c, d, x[k+4],  6, 0xF7537E82);
    d = ii(d, a, b, c, x[k+11], 10, 0xBD3AF235);
    c = ii(c, d, a, b, x[k+2], 15, 0x2AD7D2BB);
    b = ii(b, c, d, a, x[k+9], 21, 0xEB86D391);
    a = addUnsigned(a, AA);
    b = addUnsigned(b, BB);
    c = addUnsigned(c, CC);
    d = addUnsigned(d, DD);
  }
  return (wordToHex(a) + wordToHex(b) + wordToHex(c) + wordToHex(d)).toLowerCase();
}

// ── URL 修复 ──
function fixUrl(url) {
  if (!url) return url;
  url = url.trim();
  if (url.startsWith('//')) return 'https:' + url;
  if (url.startsWith('http://')) return url.replace('http://', 'https://');
  return url;
}

// ── B站 API 工具 ──
async function ensurePublicSession() {
  if (!_publicCookies) {
    const resp = await fetch('https://www.bilibili.com/', { headers: BILI_HEADERS });
    const setCookie = resp.headers.get('set-cookie') || '';
    _publicCookies = setCookie;
  }
  return _publicCookies;
}

function getCookies() {
  return _loginCookies || _publicCookies;
}

async function getWbiKeys() {
  const now = Date.now();
  if (_wbiCache && (now - _wbiCacheTime) < 900000) return _wbiCache;

  const cookies = getCookies();
  const resp = await fetch('https://api.bilibili.com/x/web-interface/nav', {
    headers: { ...BILI_HEADERS, Cookie: cookies }
  });
  const data = await resp.json();
  const wbi = data.data.wbi_img;
  const ik = wbi.img_url.match(/wbi\/(.*?)\./)[1];
  const sk = wbi.sub_url.match(/wbi\/(.*?)\./)[1];
  const mk = MIXIN_KEY_ENC_TAB.map(i => (ik + sk)[i]).join('').slice(0, 32);
  _wbiCache = { mixin_key: mk };
  _wbiCacheTime = now;
  return _wbiCache;
}

function signParams(params, mixinKey) {
  params.wts = Math.floor(Date.now() / 1000);
  const sorted = Object.keys(params).sort().reduce((acc, k) => { acc[k] = params[k]; return acc; }, {});
  const query = new URLSearchParams(sorted).toString();
  params.w_rid = md5(query + mixinKey);
  return params;
}

async function biliGet(path, params = {}, useSign = false) {
  const cookies = getCookies();
  if (useSign) {
    const wbi = await getWbiKeys();
    params = signParams(params, wbi.mixin_key);
  }
  const url = new URL('https://api.bilibili.com' + path);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const resp = await fetch(url.toString(), {
    headers: { ...BILI_HEADERS, Cookie: cookies }
  });
  const data = await resp.json();
  if (data.code !== 0) {
    throw new Error(`B站API错误(${data.code}): ${data.message || 'unknown'}`);
  }
  return data;
}

// ── JSON 响应辅助 ──
function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 0), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
    }
  });
}

function jsonError(msg, status = 500) {
  return json({ error: String(msg).slice(0, 200) }, status);
}

// ── DeepSeek AI ──
const LLM_KEY = 'sk-f1949eb1aa6b47648825efb59f668fc3';
const LLM_BASE = 'https://api.deepseek.com/v1';
const LLM_MODEL = 'deepseek-chat';

async function summarizeVideo(vid) {
  try {
    const prompt = `作为专业视频分析员，请根据标题和简介分析这个B站视频，推测它的内容结构和核心观点：

标题：${vid.title}
简介：${(vid.desc || '').slice(0, 500)}
视频分类：${vid.tname || ''} 时长：${vid.length || ''} 播放：${vid.view || 0}

输出JSON（不要markdown包裹）：
{
  "topic": "一句话主题（15字内）",
  "sections": [
    {"part": "第一部分做什么", "content": "具体内容（20-40字）"},
    {"part": "第二部分做什么", "content": "具体内容（20-40字）"},
    {"part": "第三部分做什么", "content": "具体内容（20-40字）"}
  ],
  "key_points": ["核心观点1", "核心观点2", "核心观点3"],
  "category": "分类标签",
  "recommendation": "强烈推荐/推荐/可选/可跳过",
  "recommendation_reason": "一句话理由（20字内）"
}

注意：sections至少2个，不超过4个；key_points至少2个，不超过5个。`;

    const r = await fetch(`${LLM_BASE}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${LLM_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: LLM_MODEL,
        messages: [{ role: 'user', content: prompt }],
        temperature: 0.3,
        max_tokens: 500
      })
    });
    const d = await r.json();
    let txt = d.choices[0].message.content.trim();
    if (txt.includes('```json')) txt = txt.split('```json')[1].split('```')[0];
    else if (txt.includes('```')) txt = txt.split('```')[1].split('```')[0];
    return JSON.parse(txt);
  } catch (e) {
    return {
      topic: vid.title || '',
      summary: `AI概括失败: ${String(e).slice(0, 50)}`,
      recommendation: '可选',
      category: '未知'
    };
  }
}

// ── 字幕获取 ──
async function getSubtitle(bvid) {
  try {
    const info = await biliGet('/x/web-interface/view', { bvid });
    const cid = info.data.cid;
    const player = await biliGet('/x/player/v2', { bvid, cid });
    const subs = player?.data?.subtitle?.subtitles || [];
    const vidData = info.data;

    if (subs.length > 0) {
      let subUrl = subs[0].subtitle_url || '';
      if (subUrl) {
        subUrl = fixUrl(subUrl);
        const subResp = await fetch(subUrl);
        const subData = await subResp.json();
        const body = subData.body || [];
        const text = body.slice(0, 300).map((item, i) => `${i + 1}. ${item.content}`).join('\n');
        const suffix = body.length > 300 ? `\n...（共${body.length}句，省略剩余）` : '';
        return {
          subtitles: [{ lan: subs[0].lan || '', lan_doc: subs[0].lan_doc || '' }],
          text: text + suffix,
          ai_generated: false
        };
      }
    }

    // AI 生成文字版
    const tagsStr = (vidData.tags || []).map(t => t.tag_name).slice(0, 10).join(', ');
    const durationMin = Math.floor((vidData.duration || 0) / 60);

    const prompt = `这个B站视频没有字幕。请根据标题和简介，推演并生成一个详细的文字版内容。

标题：${vidData.title}
简介：${(vidData.desc || '').slice(0, 600)}
时长：约${durationMin}分钟
标签：${tagsStr}

请生成完整的讲解式文字稿，要求：
1.【开场】（1-2句，自然引入话题）
2.【主体】（至少5个要点，每个要点2-3句话，模拟视频实际讲述的内容，根据标题和简介合理推演）
3.【总结】（1-2句，点明核心价值）

总字数300-500字，用口语化表达，像真人做视频一样娓娓道来。`;

    const r = await fetch(`${LLM_BASE}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${LLM_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: LLM_MODEL,
        messages: [{ role: 'user', content: prompt }],
        temperature: 0.6,
        max_tokens: 1000
      })
    });

    if (r.status !== 200) {
      return { subtitles: [], text: `AI服务异常(HTTP ${r.status})，请稍后重试`, ai_generated: false };
    }

    const respData = await r.json();
    if (!respData.choices?.[0]) {
      const errMsg = respData.error?.message || '未知错误';
      return { subtitles: [], text: `AI服务响应异常: ${errMsg.slice(0, 60)}`, ai_generated: false };
    }

    const text = respData.choices[0].message.content.trim();
    if (text.length < 30) {
      return { subtitles: [], text: 'AI生成内容过短，请重试', ai_generated: false };
    }

    return { subtitles: [], text, ai_generated: true };
  } catch (e) {
    return { subtitles: [], text: `获取失败: ${String(e).slice(0, 80)}`, ai_generated: false };
  }
}

// ── 主路由 ──
export async function onRequest(context) {
  const { request } = context;
  const url = new URL(request.url);
  const path = url.pathname;

  try {
    // 提取 API 子路径: /api/login/generate → login/generate
    const apiPath = path.replace(/^\/api\//, '');

    // ── 登录 ──
    if (apiPath === 'login/generate') {
      // 生成扫码登录 URL（前端用 JS 库生成二维码）
      const cookies = getCookies();
      const resp = await fetch('https://passport.bilibili.com/x/passport-login/web/qrcode/generate', {
        headers: { ...BILI_HEADERS, Cookie: cookies }
      });
      const data = await resp.json();
      if (data.code !== 0) return jsonError(data.message || '生成二维码失败');
      // 保存 cookies（登录会话需要）
      _loginCookies = resp.headers.get('set-cookie') || cookies;
      return json({
        qrcode_key: data.data.qrcode_key,
        qr_url: data.data.url
      });
    }

    if (apiPath === 'login/poll') {
      const key = url.searchParams.get('key');
      if (!key) return jsonError('缺少 key', 400);
      const cookies = _loginCookies || getCookies();
      const resp = await fetch(`https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key=${key}`, {
        headers: { ...BILI_HEADERS, Cookie: cookies }
      });
      const data = await resp.json();
      const code = data?.data?.code ?? -1;
      if (code === 0) {
        // 登录成功，获取用户信息
        const setCookie = resp.headers.get('set-cookie') || '';
        _loginCookies = setCookie || _loginCookies;
        try {
          const navResp = await fetch('https://api.bilibili.com/x/web-interface/nav', {
            headers: { ...BILI_HEADERS, Cookie: _loginCookies }
          });
          const navData = await navResp.json();
          if (navData?.data?.isLogin) {
            _loginInfo = {
              uid: navData.data.mid,
              uname: navData.data.uname,
              face: fixUrl(navData.data.face || '')
            };
          }
        } catch (e) { /* ignore */ }
      }
      return json({
        code,
        message: data?.data?.message || '',
        user: _loginInfo
      });
    }

    if (apiPath === 'login/info') {
      return json({ logged_in: !!_loginInfo, user: _loginInfo });
    }

    if (apiPath === 'login/logout') {
      _loginCookies = '';
      _loginInfo = null;
      return json({ ok: true });
    }

    // ── 关注列表 ──
    if (apiPath === 'followings') {
      if (!_loginInfo) return jsonError('请先登录', 401);
      const page = parseInt(url.searchParams.get('page') || '1');
      const resp = await fetch(
        `https://api.bilibili.com/x/relation/followings?vmid=${_loginInfo.uid}&pn=${page}&ps=50&order=desc&order_type=attention`,
        { headers: { ...BILI_HEADERS, Cookie: _loginCookies } }
      );
      const data = await resp.json();
      if (data.code !== 0) return jsonError(data.message || 'unknown');
      const users = (data.data?.list || []).map(u => ({
        mid: u.mid,
        uname: u.uname,
        sign: u.sign || '',
        face: fixUrl(u.face || '')
      }));
      return json({ users, total: data.data?.total || 0 });
    }

    // ── 搜索 UP主 ──
    if (apiPath === 'search_up') {
      const name = url.searchParams.get('name');
      if (!name) return jsonError('缺少 name 参数', 400);
      // 确保有公开 session 的 cookies
      await ensurePublicSession();
      const data = await biliGet('/x/web-interface/search/type', {
        search_type: 'bili_user',
        keyword: name
      });
      const results = (data.data?.result || []).map(u => ({
        mid: u.mid,
        uname: u.uname,
        sign: u.usign || '',
        fans: u.fans || 0,
        videos: u.videos || 0,
        face: fixUrl(u.upic || '')
      }));
      return json({ results });
    }

    // ── 视频列表 ──
    if (apiPath === 'all_videos') {
      const mid = parseInt(url.searchParams.get('mid') || '0');
      const maxPages = parseInt(url.searchParams.get('pages') || '2');
      if (!mid) return jsonError('缺少 mid 参数', 400);

      const allVideos = [];
      let count = 0;
      let errorMsg = null;

      for (let p = 1; p <= maxPages; p++) {
        try {
          const params = { mid, ps: 50, pn: p, order: 'pubdate' };
          const data = await biliGet('/x/space/wbi/arc/search', params, true);
          const vlist = data.data?.list?.vlist || [];
          count = data.data?.page?.count || 0;
          for (const v of vlist) {
            allVideos.push({
              bvid: v.bvid,
              title: v.title,
              description: v.description || '',
              length: v.length,
              created: v.created,
              play: v.play || 0,
              comment: v.comment || 0,
              video_review: v.video_review || 0,
              pic: fixUrl(v.pic || '')
            });
          }
        } catch (e) {
          errorMsg = String(e);
          break;
        }
        if (allVideos.length >= count) break;
      }

      const result = { videos: allVideos, total: allVideos.length };
      if (errorMsg) {
        result.error = errorMsg;
        result.count = count;
      }
      return json(result);
    }

    // ── AI概括 ──
    if (apiPath === 'summarize') {
      const bvid = url.searchParams.get('bvid');
      if (!bvid) return jsonError('缺少 bvid', 400);
      const info = await biliGet('/x/web-interface/view', { bvid });
      const vid = info.data;
      const vidData = {
        title: vid.title,
        desc: vid.desc || '',
        length: vid.duration,
        view: vid.stat?.view || 0,
        tname: vid.tname || '',
        tags: (vid.tags || []).map(t => t.tag_name).slice(0, 10)
      };
      const summary = await summarizeVideo(vidData);
      return json(summary);
    }

    // ── 字幕 ──
    if (apiPath === 'subtitle') {
      const bvid = url.searchParams.get('bvid');
      if (!bvid) return jsonError('缺少 bvid', 400);
      return json(await getSubtitle(bvid));
    }

    return jsonError('未知 API', 404);
  } catch (e) {
    return jsonError(String(e));
  }
}
