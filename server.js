/**
 * B站UP主视频速览 - Web 服务
 * 纯 Node.js 内置模块，无需 npm install
 * 用法: node server.js
 */

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = 3457;

// ── WBI 签名（服务端实现） ──────────────────────────
const MIXIN_KEY_ENC_TAB = [
  46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,
  27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,
  37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,
  22,25,54,21,56,59,6,63,57,62,11,36,20,52,44,34,
];

let wbiCache = null;

function getMixinKey(orig) {
  return MIXIN_KEY_ENC_TAB.map(i => orig[i]).join('').slice(0, 32);
}

function biliGet(apiPath, params = {}) {
  return new Promise((resolve, reject) => {
    const qs = new URLSearchParams(params).toString();
    const fullPath = apiPath + (qs ? '?' + qs : '');
    const opts = {
      hostname: 'api.bilibili.com',
      path: fullPath,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://www.bilibili.com/',
      },
    };
    https.get(opts, res => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch(e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function fetchWbiKeys() {
  const data = await biliGet('/x/web-interface/nav');
  const wbi = data.data.wbi_img;
  const imgKey = wbi.img_url.match(/wbi\/(.*?)\./)[1];
  const subKey = wbi.sub_url.match(/wbi\/(.*?)\./)[1];
  const mixinKey = getMixinKey(imgKey + subKey);
  wbiCache = { imgKey, subKey, mixinKey };
  return wbiCache;
}

async function signParams(params) {
  if (!wbiCache) await fetchWbiKeys();
  params.wts = Math.floor(Date.now() / 1000);
  const sorted = Object.keys(params).sort().map(k => k + '=' + encodeURIComponent(params[k])).join('');
  params.w_rid = crypto.createHash('md5').update(sorted + wbiCache.mixinKey).digest('hex');
  return params;
}

// ── API 处理器 ──────────────────────────────────────
async function handleAPI(reqPath, query) {
  // 搜索UP主
  if (reqPath === '/api/search_up') {
    const name = query.name;
    if (!name) return [400, { error: '缺少 name 参数' }];
    const data = await biliGet('/x/web-interface/search/type', {
      search_type: 'bili_user', keyword: name,
    });
    const results = (data.data?.result || []).map(u => ({
      mid: u.mid, uname: u.uname, sign: u.usign,
      fans: u.fans, videos: u.videos,
      face: u.upic?.startsWith('//') ? 'https:' + u.upic : u.upic,
    }));
    return [200, { results }];
  }

  // 获取UP主视频列表
  if (reqPath === '/api/videos') {
    const mid = parseInt(query.mid);
    const page = parseInt(query.page) || 1;
    if (!mid) return [400, { error: '缺少 mid 参数' }];
    const params = await signParams({ mid, ps: 50, pn: page, order: 'pubdate' });
    const data = await biliGet('/x/space/wbi/arc/search', params);
    const list = data.data.list.vlist;
    const videos = list.map(v => ({
      bvid: v.bvid, title: v.title, description: v.description,
      length: v.length, created: v.created,
      play: v.play, comment: v.comment, video_review: v.video_review,
      pic: v.pic?.startsWith('//') ? 'https:' + v.pic : v.pic,
    }));
    return [200, { videos, count: data.data.page.count, page: data.data.page.pn }];
  }

  // 获取所有视频（分页聚合）
  if (reqPath === '/api/all_videos') {
    const mid = parseInt(query.mid);
    const maxPages = parseInt(query.pages) || 4;
    if (!mid) return [400, { error: '缺少 mid 参数' }];
    let all = [];
    for (let p = 1; p <= maxPages; p++) {
      const params = await signParams({ mid, ps: 50, pn: p, order: 'pubdate' });
      const data = await biliGet('/x/space/wbi/arc/search', params);
      const list = data.data.list.vlist;
      all.push(...list.map(v => ({
        bvid: v.bvid, title: v.title, description: v.description,
        length: v.length, created: v.created,
        play: v.play, comment: v.comment, video_review: v.video_review,
        pic: v.pic?.startsWith('//') ? 'https:' + v.pic : v.pic,
      })));
      if (all.length >= data.data.page.count) break;
      await new Promise(r => setTimeout(r, 400));
    }
    return [200, { videos: all, total: all.length }];
  }

  return [404, { error: '未知 API' }];
}

// ── 前端 HTML ────────────────────────────────────────
const HTML = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>B站UP主视频速览</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f5f5;color:#333;min-height:100vh}
.header{background:linear-gradient(135deg,#fb7299,#fc8f6e);color:#fff;padding:24px 16px 20px;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(251,114,153,.3)}
.header h1{font-size:22px;margin-bottom:4px;text-align:center}
.header .sub{font-size:13px;opacity:.85;text-align:center;margin-bottom:16px}
.header input{width:100%;padding:12px 16px;border:none;border-radius:24px;font-size:16px;outline:none;background:rgba(255,255,255,.25);color:#fff;text-align:center}
.header input::placeholder{color:rgba(255,255,255,.6)}
.header input:focus{background:rgba(255,255,255,.4)}
#suggestions{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin-top:12px}
#suggestions button{background:rgba(255,255,255,.2);border:none;color:#fff;padding:6px 14px;border-radius:14px;font-size:13px;cursor:pointer}
#upInfo{background:#fff;padding:16px;margin:12px;border-radius:12px;display:none;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
#upInfo img{width:48px;height:48px;border-radius:50%}
#upInfo .name{font-size:16px;font-weight:600}
#upInfo .meta{font-size:12px;color:#999}
#upInfo .sign{font-size:12px;color:#666;margin-top:4px}
.content{padding:0 12px 80px}
.card{background:#fff;border-radius:12px;margin-bottom:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);display:flex;cursor:pointer;transition:transform .15s}
.card:active{transform:scale(.98)}
.card .thumb{width:120px;min-width:120px;height:75px;background:#eee;position:relative;overflow:hidden}
.card .thumb img{width:100%;height:100%;object-fit:cover;display:block}
.card .dur{position:absolute;right:4px;bottom:4px;background:rgba(0,0,0,.7);color:#fff;font-size:10px;padding:1px 5px;border-radius:3px}
.card .info{flex:1;padding:10px 12px;min-width:0}
.card .info .title{font-size:14px;font-weight:600;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:4px}
.card .info .meta{font-size:11px;color:#999;margin-bottom:4px;display:flex;gap:10px;flex-wrap:wrap}
.card .info .meta span{white-space:nowrap}
.card .info .desc{font-size:12px;color:#666;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.loading{padding:40px;text-align:center;color:#999}
.loading .spinner{display:inline-block;width:32px;height:32px;border:3px solid #eee;border-top-color:#fb7299;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.search-box{display:flex;gap:8px;margin:0 12px 12px}
.search-box input{flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:20px;font-size:14px;outline:none}
.search-box input:focus{border-color:#fb7299}
.search-box button{background:#fb7299;border:none;color:#fff;padding:10px 20px;border-radius:20px;font-size:14px;cursor:pointer}
.result-stats{text-align:center;font-size:12px;color:#999;padding:4px 0 8px}
</style>
</head>
<body>
<div class="header">
  <h1>📺 B站UP主视频速览</h1>
  <div class="sub">比看视频快100倍 · 先看摘要再决定</div>
</div>

<div class="search-box">
  <input type="text" id="searchInput" placeholder="输入UP主名字..." autocomplete="off" onkeydown="if(event.key==='Enter')search()">
  <button onclick="search()">搜索</button>
</div>

<div id="upInfo"></div>
<div class="result-stats" id="stats"></div>
<div class="content" id="list">
  <div style="padding:60px 20px;text-align:center;color:#999;font-size:14px">
    👆 输入UP主名字开始探索
  </div>
</div>

<script>
function fmt(n){if(n>=1e4)return (n/1e4).toFixed(1)+'万';return n.toLocaleString()}
function ts(d){return new Date(d*1000).toLocaleDateString('zh-CN')}

async function search(){
  const name = document.getElementById('searchInput').value.trim();
  if(!name) return;

  document.getElementById('list').innerHTML = '<div class="loading"><div class="spinner"></div><p style="margin-top:12px">正在搜索...</p></div>';
  document.getElementById('upInfo').style.display = 'none';
  document.getElementById('stats').textContent = '';

  try {
    const resp = await fetch('/api/search_up?name=' + encodeURIComponent(name));
    const data = await resp.json();
    if(!data.results || data.results.length===0){
      document.getElementById('list').innerHTML = '<div style="padding:60px;text-align:center;color:#999">未找到该UP主</div>';
      return;
    }
    const up = data.results[0];
    showUPInfo(up);
    loadVideos(up.mid);
  } catch(e) {
    document.getElementById('list').innerHTML = '<div style="padding:60px;text-align:center;color:#e74c3c">搜索失败: '+e.message+'</div>';
  }
}

function showUPInfo(up){
  const div = document.getElementById('upInfo');
  div.innerHTML = '<img src="'+up.face+'" onerror="this.style.display=\'none\'">'+
    '<div><div class="name">'+up.uname+'</div>'+
    '<div class="meta">👥 '+fmt(up.fans)+' 粉丝 | 🎬 '+up.videos+' 视频</div>'+
    '<div class="sign">'+(up.sign||'').slice(0,50)+'</div></div>';
  div.style.display = 'flex';
}

async function loadVideos(mid){
  document.getElementById('list').innerHTML = '<div class="loading"><div class="spinner"></div><p style="margin-top:12px">正在获取视频列表...</p></div>';
  try {
    const resp = await fetch('/api/all_videos?mid='+mid+'&pages=4');
    const data = await resp.json();
    document.getElementById('stats').textContent = '共 ' + data.total + ' 个视频';
    render(data.videos);
  } catch(e) {
    document.getElementById('list').innerHTML = '<div style="padding:60px;text-align:center;color:#e74c3c">加载失败</div>';
  }
}

function render(videos){
  let html = '';
  videos.forEach(v => {
    html += '<div class="card" onclick="window.open(\'https://www.bilibili.com/video/'+v.bvid+'\')">'+
      '<div class="thumb">'+
        (v.pic ? '<img src="'+v.pic+'" loading="lazy" onerror="this.parentElement.style.background=\'#eee\'">' : '')+
        '<span class="dur">'+v.length+'</span>'+
      '</div>'+
      '<div class="info">'+
        '<div class="title">'+v.title+'</div>'+
        '<div class="meta">'+
          '<span>📅 '+ts(v.created)+'</span>'+
          '<span>👁 '+fmt(v.play)+'</span>'+
          '<span>💬 '+fmt(v.comment)+'</span>'+
        '</div>'+
        '<div class="desc">'+(v.description||'')+'</div>'+
      '</div>'+
    '</div>';
  });
  document.getElementById('list').innerHTML = html || '<div style="padding:60px;text-align:center;color:#999">该UP主暂无视频</div>';
}
</script>
</body>
</html>`;

// ── 启动服务器 ──────────────────────────────────────
const server = http.createServer(async (req, res) => {
  const reqUrl = new URL(req.url, 'http://localhost');
  const reqPath = reqUrl.pathname;

  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

  if (req.method === 'OPTIONS') {
    res.writeHead(204); res.end(); return;
  }

  // API 路由
  if (reqPath.startsWith('/api/')) {
    try {
      const query = Object.fromEntries(reqUrl.searchParams);
      const [status, body] = await handleAPI(reqPath, query);
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // 前端页面
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(HTML);
});

server.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
  console.log(`Mobile: http://${require('os').hostname()}.local:${PORT}`);
});
