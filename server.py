#!/usr/bin/env python3
"""B站UP主视频速览 Web 服务 - 支持登录+关注UP主"""

import json
import re
import hashlib
import time
import io
import qrcode
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

import requests

PORT = 3457

MIXIN_KEY_ENC_TAB = [
    46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,
    27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,
    37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,
    22,25,54,21,56,59,6,63,57,62,11,36,20,52,44,34,
]
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
}
_public_session = None
_login_session = None
_login_info = None  # {uid, uname, face}
_wbi_cache = None
_wbi_cache_time = 0

def _ensure_public():
    global _public_session
    if _public_session is None:
        _public_session = requests.Session()
        _public_session.headers.update(HEADERS)
        try:
            _public_session.get('https://www.bilibili.com/', timeout=10)
        except:
            pass
    return _public_session

def _ensure_login():
    global _login_session
    if _login_session is None:
        _login_session = requests.Session()
        _login_session.headers.update(HEADERS)
    return _login_session

def _get_session():
    """优先使用登录session"""
    if _login_session is not None and _login_info is not None:
        return _login_session
    return _ensure_public()

def _get_wbi_keys():
    global _wbi_cache, _wbi_cache_time
    now = time.time()
    if _wbi_cache and (now - _wbi_cache_time) < 900:
        return _wbi_cache
    s = _ensure_public()
    resp = s.get('https://api.bilibili.com/x/web-interface/nav', timeout=10)
    data = resp.json()
    wbi = data['data']['wbi_img']
    ik = re.search(r'wbi/(.*?)\.', wbi['img_url']).group(1)
    sk = re.search(r'wbi/(.*?)\.', wbi['sub_url']).group(1)
    mk = ''.join((ik+sk)[i] for i in MIXIN_KEY_ENC_TAB)[:32]
    _wbi_cache = {'mixin_key': mk}
    _wbi_cache_time = now
    return _wbi_cache

def _sign_params(params):
    wbi = _get_wbi_keys()
    params['wts'] = int(time.time())
    params = dict(sorted(params.items()))
    query = urlencode(params)
    params['w_rid'] = hashlib.md5((query + wbi['mixin_key']).encode()).hexdigest()
    return params

def _bili_get(path, params=None):
    s = _get_session()
    resp = s.get('https://api.bilibili.com' + path, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"B站API错误({data.get('code')}): {data.get('message','unknown')}")
    return data

# ── API 处理 ────────────────────────────────────────
def handle_api(path, query):
    global _login_session, _login_info

    # ---- 登录 ----
    if path == '/api/login/generate':
        s = _ensure_login()
        resp = s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate', timeout=10)
        data = resp.json()
        if data.get('code') != 0:
            return 500, {'error': data.get('message','生成二维码失败')}
        qr_url = data['data']['url']
        qr_key = data['data']['qrcode_key']
        # 生成二维码图片 base64
        img = qrcode.make(qr_url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return 200, {'qrcode_key': qr_key, 'qr_image': f'data:image/png;base64,{b64}'}

    if path == '/api/login/poll':
        key = query.get('key', [''])[0]
        if not key:
            return 400, {'error': '缺少 key'}
        s = _ensure_login()
        resp = s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll',
                      params={'qrcode_key': key}, timeout=10)
        data = resp.json()
        code = data.get('data', {}).get('code', -1)
        # 登录成功，提取cookie
        if code == 0 and 'Set-Cookie' in str(resp.headers):
            # 获取登录用户信息
            try:
                nav = s.get('https://api.bilibili.com/x/web-interface/nav', timeout=10).json()
                if nav.get('data', {}).get('isLogin'):
                    _login_info = {
                        'uid': nav['data']['mid'],
                        'uname': nav['data']['uname'],
                        'face': nav['data'].get('face', ''),
                    }
            except:
                pass
        return 200, {'code': code, 'message': data.get('data', {}).get('message',''),
                      'user': _login_info}

    if path == '/api/login/info':
        return 200, {'logged_in': bool(_login_info), 'user': _login_info}

    if path == '/api/login/logout':
        _login_session = None
        _login_info = None
        return 200, {'ok': True}

    # ---- 关注列表 ----
    if path == '/api/followings':
        if not _login_info:
            return 401, {'error': '请先登录'}
        page = int(query.get('page', ['1'])[0])
        try:
            s = _login_session
            resp = s.get('https://api.bilibili.com/x/relation/followings',
                          params={'vmid': _login_info['uid'], 'pn': page, 'ps': 50,
                                  'order': 'desc', 'order_type': 'attention'},
                          timeout=15)
            data = resp.json()
            if data.get('code') != 0:
                return 500, {'error': data.get('message', 'unknown')}
            users = []
            for u in data.get('data', {}).get('list', []):
                face = u.get('face', '')
                if face and face.startswith('//'):
                    face = 'https:' + face
                users.append({
                    'mid': u['mid'], 'uname': u['uname'],
                    'sign': u.get('sign', ''), 'face': face,
                })
            return 200, {'users': users, 'total': data.get('data',{}).get('total',0)}
        except Exception as e:
            return 500, {'error': str(e)}

    # ---- 搜索 ----
    if path == '/api/search_up':
        name = query.get('name', [''])[0]
        if not name:
            return 400, {'error': '缺少 name 参数'}
        try:
            data = _bili_get('/x/web-interface/search/type', {
                'search_type': 'bili_user', 'keyword': name,
            })
            results = []
            for u in (data.get('data', {}).get('result', []) or []):
                face = u.get('upic', '')
                if face and face.startswith('//'):
                    face = 'https:' + face
                results.append({
                    'mid': u['mid'], 'uname': u['uname'],
                    'sign': u.get('usign', ''), 'fans': u.get('fans', 0),
                    'videos': u.get('videos', 0), 'face': face,
                })
            return 200, {'results': results}
        except Exception as e:
            return 500, {'error': str(e)}

    # ---- 视频 ----
    if path == '/api/all_videos':
        mid = int(query.get('mid', ['0'])[0])
        max_pages = int(query.get('pages', ['2'])[0])
        if not mid:
            return 400, {'error': '缺少 mid 参数'}
        all_videos = []
        count = 0
        error_msg = None
        for p in range(1, max_pages + 1):
            try:
                params = _sign_params({'mid': mid, 'ps': 50, 'pn': p, 'order': 'pubdate'})
                data = _bili_get('/x/space/wbi/arc/search', params)
                vlist = data['data']['list']['vlist']
                count = data['data']['page']['count']
                for v in vlist:
                    pic = v.get('pic', '')
                    if pic and pic.startswith('//'):
                        pic = 'https:' + pic
                    all_videos.append({
                        'bvid': v['bvid'], 'title': v['title'],
                        'description': v.get('description', ''),
                        'length': v['length'], 'created': v['created'],
                        'play': v.get('play', 0), 'comment': v.get('comment', 0),
                        'video_review': v.get('video_review', 0), 'pic': pic,
                    })
            except Exception as e:
                error_msg = str(e)
                break
            if len(all_videos) >= count:
                break
            time.sleep(0.3)
        result = {'videos': all_videos, 'total': len(all_videos)}
        if error_msg:
            result['error'] = error_msg
            result['count'] = count
        return 200, result

    return 404, {'error': '未知 API'}


# ── 前端 HTML ────────────────────────────────────────
HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>B站UP主视频速览</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f5f5;color:#333;min-height:100vh;padding-bottom:80px}
.header{background:linear-gradient(135deg,#fb7299,#fc8f6e);color:#fff;padding:24px 16px 20px;position:sticky;top:0;z-index:100}
.header h1{font-size:22px;text-align:center}
.header .sub{font-size:13px;opacity:.85;text-align:center;margin:6px 0 0}
.login-bar{display:flex;justify-content:center;align-items:center;gap:8px;padding:12px;background:#fff;border-bottom:1px solid #eee;position:sticky;top:82px;z-index:99}
.login-bar .avatar{width:32px;height:32px;border-radius:50%;background:#eee}
.login-bar .uname{font-size:14px;font-weight:500}
.login-bar button{border:1px solid #fb7299;background:#fff;color:#fb7299;padding:6px 16px;border-radius:16px;font-size:13px;cursor:pointer}
.login-bar button.logout{color:#999;border-color:#ddd}

.search-box{display:flex;gap:8px;padding:12px;background:#fff}
.search-box input{flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:20px;font-size:15px;outline:none}
.search-box input:focus{border-color:#fb7299}
.search-box button{background:#fb7299;border:none;color:#fff;padding:10px 20px;border-radius:20px;font-size:15px;cursor:pointer}
#upInfo{background:#fff;padding:16px;margin:12px;border-radius:12px;display:none;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
#upInfo img{width:48px;height:48px;border-radius:50%}
#upInfo .name{font-size:16px;font-weight:600}
#upInfo .meta{font-size:12px;color:#999}
#upInfo .sign{font-size:12px;color:#666;margin-top:4px}

.follow-section{display:none;padding:12px}
.follow-section h3{font-size:14px;color:#666;margin-bottom:8px;padding:0 4px}
.follow-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.follow-card{background:#fff;border-radius:10px;padding:10px;text-align:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.06);transition:transform .1s}
.follow-card:active{transform:scale(.96)}
.follow-card img{width:40px;height:40px;border-radius:50%;margin-bottom:6px}
.follow-card .uname{font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.content{padding:0 12px}
.card{background:#fff;border-radius:12px;margin-bottom:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);display:flex;cursor:pointer;transition:transform .15s}
.card:active{transform:scale(.98)}
.card .thumb{width:120px;min-width:120px;height:75px;background:#eee;position:relative;overflow:hidden}
.card .thumb img{width:100%;height:100%;object-fit:cover;display:block}
.card .dur{position:absolute;right:4px;bottom:4px;background:rgba(0,0,0,.75);color:#fff;font-size:10px;padding:2px 5px;border-radius:3px}
.card .info{flex:1;padding:10px 12px;min-width:0}
.card .title{font-size:14px;font-weight:600;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:4px}
.card .meta{font-size:11px;color:#999;margin-bottom:4px;display:flex;gap:10px;flex-wrap:wrap}
.card .meta span{white-space:nowrap}
.card .desc{font-size:12px;color:#666;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.result-stats{text-align:center;font-size:12px;color:#999;padding:4px 0 8px}
.loading{padding:60px;text-align:center;color:#999}
.loading .spinner{display:inline-block;width:32px;height:32px;border:3px solid #eee;border-top-color:#fb7299;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.error{padding:40px 20px;text-align:center;color:#e74c3c;font-size:14px}
.error small{color:#999;font-size:12px;display:block;margin-top:8px}
.bili-link{display:inline-block;background:#fb7299;color:#fff;padding:10px 24px;border-radius:20px;text-decoration:none;font-size:14px;margin-top:12px}

.modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:200;align-items:center;justify-content:center}
.modal.show{display:flex}
.modal-box{background:#fff;border-radius:16px;padding:24px;max-width:300px;width:90%;text-align:center}
.modal-box h3{font-size:18px;margin-bottom:8px}
.modal-box .qr{width:200px;height:200px;margin:12px auto;display:block}
.modal-box .tip{font-size:13px;color:#999}
.modal-box .close-btn{margin-top:16px;padding:8px 24px;border:1px solid #ddd;border-radius:20px;background:#fff;color:#666;font-size:14px;cursor:pointer}
</style>
</head>
<body>
<div class="header"><h1>📺 B站UP主视频速览</h1><div class="sub">登录后查看关注UP主，一键浏览视频</div></div>

<div class="login-bar" id="loginBar">
  <span id="loginStatus" style="font-size:13px;color:#999">未登录</span>
  <button onclick="showLogin()">🔑 扫码登录</button>
</div>

<div class="search-box">
  <input type="text" id="searchInput" placeholder="输入UP主名字..." autocomplete="off" onkeydown="if(event.key==='Enter')search()">
  <button onclick="search()">搜索</button>
</div>

<div class="follow-section" id="followSection">
  <h3>⭐ 我关注的UP主</h3>
  <div class="follow-grid" id="followList"></div>
</div>

<div id="upInfo"></div>
<div class="result-stats" id="stats"></div>
<div class="content" id="list">
  <div style="padding:60px 20px;text-align:center;color:#999;font-size:14px">
    👆 登录后可查看关注UP主<br><small>或直接搜索任意UP主名字</small>
  </div>
</div>

<div class="modal" id="loginModal">
  <div class="modal-box">
    <h3>🔑 扫码登录B站</h3>
    <p class="tip">请用B站APP扫码</p>
    <img class="qr" id="qrImage" src="" alt="QR Code">
    <p class="tip" id="qrStatus">等待扫码...</p>
    <button class="close-btn" onclick="closeLogin()">取消</button>
  </div>
</div>

<script>
var POLL_INTERVAL = null;
var LOGGED_IN = false;
var LOGIN_UID = null;

function fmt(n){if(n>=1e4)return (n/1e4).toFixed(1)+'万';return n.toLocaleString()}
function ts(d){return new Date(d*1000).toLocaleDateString('zh-CN')}

async function checkLogin(){
  try{
    var r=await fetch('/api/login/info');
    var d=await r.json();
    if(d.logged_in){
      LOGGED_IN = true;
      LOGIN_UID = d.user.uid;
      document.getElementById('loginStatus').innerHTML='<img src="'+d.user.face+'" class="avatar" style="display:inline-block;vertical-align:middle"> <span class="uname">'+d.user.uname+'</span>';
      document.getElementById('loginBar').innerHTML=document.getElementById('loginStatus').outerHTML+'<button class="logout" onclick="logout()">退出</button>';
      loadFollowings();
    }
  }catch(e){}
}

async function showLogin(){
  document.getElementById('loginModal').classList.add('show');
  document.getElementById('qrStatus').textContent='正在生成二维码...';
  try{
    var r=await fetch('/api/login/generate');
    var d=await r.json();
    if(d.error){alert(d.error);closeLogin();return}
    document.getElementById('qrImage').src=d.qr_image;
    document.getElementById('qrStatus').textContent='请用B站APP扫码';
    POLL_INTERVAL = setInterval(function(){pollLogin(d.qrcode_key)}, 2000);
  }catch(e){
    document.getElementById('qrStatus').textContent='生成失败: '+e.message;
  }
}

async function pollLogin(key){
  try{
    var r=await fetch('/api/login/poll?key='+key);
    var d=await r.json();
    if(d.code===0 && d.user){
      clearInterval(POLL_INTERVAL);
      closeLogin();
      checkLogin();
    }else if(d.code===86038){
      document.getElementById('qrStatus').textContent='二维码已过期，请重新生成';
      clearInterval(POLL_INTERVAL);
    }else if(d.code===86090){
      document.getElementById('qrStatus').textContent='已扫码，请在手机上确认';
    }else if(d.code===86101){
      document.getElementById('qrStatus').textContent='等待扫码...';
    }
  }catch(e){}
}

function closeLogin(){
  document.getElementById('loginModal').classList.remove('show');
  if(POLL_INTERVAL){clearInterval(POLL_INTERVAL);POLL_INTERVAL=null}
}

async function logout(){
  await fetch('/api/login/logout');
  LOGGED_IN=false; LOGIN_UID=null;
  location.reload();
}

async function loadFollowings(){
  try{
    var r=await fetch('/api/followings?page=1');
    var d=await r.json();
    if(d.error){return}
    document.getElementById('followSection').style.display='block';
    var h='';
    d.users.forEach(function(u){
      h+='<div class="follow-card" onclick="openUP('+u.mid+',\''+u.uname+'\',\''+u.face+'\',\''+(u.sign||'').replace(/'/g,'')+'\')">'+
        '<img src="'+u.face+'" onerror="this.style.background=\'#ccc\'">'+
        '<div class="uname">'+u.uname+'</div></div>';
    });
    document.getElementById('followList').innerHTML=h;
  }catch(e){}
}

function openUP(mid, uname, face, sign){
  document.getElementById('searchInput').value='';
  document.getElementById('upInfo').innerHTML='<img src="'+face+'" onerror="this.style.display=\'none\'"><div><div class="name">'+uname+'</div><div class="sign">'+sign.slice(0,60)+'</div></div>';
  document.getElementById('upInfo').style.display='flex';
  document.getElementById('stats').textContent='';
  loadVideos(mid);
}

async function search(){
  var name=document.getElementById('searchInput').value.trim();
  if(!name)return;
  document.getElementById('list').innerHTML='<div class="loading"><div class="spinner"></div><p style="margin-top:12px">正在搜索UP主...</p></div>';
  document.getElementById('upInfo').style.display='none';
  document.getElementById('stats').textContent='';
  try{
    var r=await fetch('/api/search_up?name='+encodeURIComponent(name));
    var d=await r.json();
    if(d.error){document.getElementById('list').innerHTML='<div class="error">搜索失败<br><small>'+d.error+'</small></div>';return}
    if(!d.results||d.results.length===0){document.getElementById('list').innerHTML='<div class="error">未找到UP主</div>';return}
    var up=d.results[0];
    openUP(up.mid, up.uname, up.face, up.sign);
  }catch(e){
    document.getElementById('list').innerHTML='<div class="error">搜索失败: '+e.message+'</div>';
  }
}

async function loadVideos(mid){
  document.getElementById('list').innerHTML='<div class="loading"><div class="spinner"></div><p style="margin-top:12px">正在获取视频列表...</p></div>';
  try{
    var r=await fetch('/api/all_videos?mid='+mid+'&pages=2');
    var d=await r.json();
    if(d.error && d.total===0){
      document.getElementById('list').innerHTML='<div class="error">视频列表获取失败<br><small>'+d.error+'</small><br><a href="https://space.bilibili.com/'+mid+'" class="bili-link">👉 打开B站主页</a></div>';
      return;
    }
    var txt='共 '+d.total+' 个视频';
    if(d.count>d.total)txt+=' (总 '+d.count+' 个)';
    if(d.error)txt+=' | ⚠️ '+d.error.slice(0,20);
    document.getElementById('stats').textContent=txt;
    render(d.videos);
  }catch(e){
    document.getElementById('list').innerHTML='<div class="error">加载失败<br><small>'+e.message+'</small></div>';
  }
}

function render(videos){
  var h='';
  videos.forEach(function(v){
    h+='<div class="card" onclick="window.open(\'https://www.bilibili.com/video/'+v.bvid+'\')">'+
      '<div class="thumb">'+(v.pic?'<img src="'+v.pic+'" loading="lazy">':'')+'<span class="dur">'+v.length+'</span></div>'+
      '<div class="info"><div class="title">'+v.title+'</div>'+
      '<div class="meta"><span>📅 '+ts(v.created)+'</span><span>👁 '+fmt(v.play)+'</span><span>💬 '+fmt(v.comment)+'</span></div>'+
      '<div class="desc">'+(v.description||'')+'</div></div></div>';
  });
  document.getElementById('list').innerHTML=h||'<div class="error">该UP主暂无视频</div>';
  window.scrollTo({top:document.getElementById('upInfo').offsetTop-90,behavior:'smooth'});
}

checkLogin();
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith('/api/'):
            try:
                status, body = handle_api(path, query)
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin','*')
                self.end_headers()
                self.wfile.write(json.dumps(body,ensure_ascii=False).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type','application/json')
                self.send_header('Access-Control-Allow-Origin','*')
                self.end_headers()
                self.wfile.write(json.dumps({'error':str(e)},ensure_ascii=False).encode())
            return

        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(HTML.encode())

    def log_message(self,*a): pass

if __name__=='__main__':
    import os
    # 使 qrcode 使用 PIL 内置字体
    os.environ.setdefault('PIL_FONT_FILE','')
    HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
