#!/usr/bin/env python3
"""B站UP主视频速览 - Vercel Serverless 版本"""

import json, re, hashlib, time, io, base64, os
from urllib.parse import urlencode
from flask import Flask, request, jsonify, Response

import requests
try:
    import qrcode
except:
    pass

app = Flask(__name__)

LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_API_BASE = os.environ.get('LLM_API_BASE', 'https://api.openai.com/v1')
LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')

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
_session = None
_login_session = None
_login_info = None
_wbi = None
_wbi_ts = 0

def _fix_url(u):
    if not u: return u
    if u.startswith('//'): return 'https:' + u
    if u.startswith('http://'): return u.replace('http://','https://',1)
    return u

def _public():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        try: _session.get('https://www.bilibili.com/', timeout=8)
        except: pass
    return _session

def _login():
    global _login_session
    if _login_session is None:
        _login_session = requests.Session()
        _login_session.headers.update(HEADERS)
    return _login_session

def _sess():
    if _login_session and _login_info: return _login_session
    return _public()

def _wbi_keys():
    global _wbi, _wbi_ts
    now = time.time()
    if _wbi and (now - _wbi_ts) < 900: return _wbi
    r = _public().get('https://api.bilibili.com/x/web-interface/nav', timeout=10)
    d = r.json()
    wi = d['data']['wbi_img']
    ik = re.search(r'wbi/(.*?)\.', wi['img_url']).group(1)
    sk = re.search(r'wbi/(.*?)\.', wi['sub_url']).group(1)
    mk = ''.join((ik+sk)[i] for i in MIXIN_KEY_ENC_TAB)[:32]
    _wbi = {'mk': mk}; _wbi_ts = now
    return _wbi

def _sign(p):
    w = _wbi_keys()
    p['wts'] = int(time.time())
    p = dict(sorted(p.items()))
    q = urlencode(p)
    p['w_rid'] = hashlib.md5((q + w['mk']).encode()).hexdigest()
    return p

def _get(path, params=None):
    r = _sess().get('https://api.bilibili.com' + path, params=params, timeout=12)
    r.raise_for_status()
    d = r.json()
    if d.get('code') != 0:
        raise Exception(f"B站错误({d.get('code')}): {d.get('message','')}")
    return d

# ── API Routes ─────────────────────────────────────
@app.route('/api/search_up')
def search_up():
    name = request.args.get('name','')
    if not name: return jsonify(error='缺少name'), 400
    try:
        d = _get('/x/web-interface/search/type', {'search_type':'bili_user','keyword':name})
        results = [{'mid':u['mid'],'uname':u['uname'],'sign':u.get('usign',''),'fans':u.get('fans',0),'videos':u.get('videos',0),'face':_fix_url(u.get('upic',''))} for u in (d.get('data',{}).get('result',[]) or [])]
        return jsonify(results=results)
    except Exception as e: return jsonify(error=str(e)), 500

@app.route('/api/all_videos')
def all_videos():
    mid = int(request.args.get('mid','0'))
    pages = int(request.args.get('pages','2'))
    if not mid: return jsonify(error='缺少mid'), 400
    vids, count, err = [], 0, None
    for p in range(1, pages+1):
        try:
            d = _get('/x/space/wbi/arc/search', _sign({'mid':mid,'ps':50,'pn':p,'order':'pubdate'}))
            vl = d['data']['list']['vlist']; count = d['data']['page']['count']
            for v in vl:
                vids.append({'bvid':v['bvid'],'title':v['title'],'description':v.get('description',''),'length':v['length'],'created':v['created'],'play':v.get('play',0),'comment':v.get('comment',0),'video_review':v.get('video_review',0),'pic':_fix_url(v.get('pic',''))})
        except Exception as e: err = str(e); break
        if len(vids) >= count: break
        time.sleep(0.3)
    result = {'videos':vids,'total':len(vids)}
    if err: result['error']=err; result['count']=count
    return jsonify(result)

@app.route('/api/summarize')
def summarize():
    bvid = request.args.get('bvid','')
    if not bvid: return jsonify(error='缺少bvid'), 400
    if not LLM_API_KEY: return jsonify(topic='未配置',summary='未配置AI Key',recommendation='可选',category='未知')
    try:
        d = _get('/x/web-interface/view',{'bvid':bvid})
        v = d['data']
        prompt = f"""对以下B站视频简短概括并给推荐度：
标题：{v['title']}
简介：{(v.get('desc',''))[:200]}
时长：{v['duration']}秒
请用JSON：{{"topic":"主题","summary":"30-60字概括","category":"分类","recommendation":"强烈推荐/推荐/可选/可跳过"}}"""
        r = requests.post(f"{LLM_API_BASE}/chat/completions", headers={"Authorization":f"Bearer {LLM_API_KEY}"}, json={"model":LLM_MODEL,"messages":[{"role":"user","content":prompt}],"temperature":0.3,"max_tokens":200}, timeout=15)
        txt = r.json()['choices'][0]['message']['content'].strip()
        if '```' in txt: txt = txt.split('```')[1].split('```')[0].replace('json','')
        return jsonify(json.loads(txt))
    except Exception as e: return jsonify(error=str(e)), 500

@app.route('/api/subtitle')
def subtitle():
    bvid = request.args.get('bvid','')
    if not bvid: return jsonify(error='缺少bvid'), 400
    try:
        d = _get('/x/web-interface/view',{'bvid':bvid})
        cid = d['data']['cid']
        p = _get('/x/player/v2',{'bvid':bvid,'cid':cid})
        subs = p.get('data',{}).get('subtitle',{}).get('subtitles',[])
        if not subs: return jsonify(subtitles=[],text='该视频没有字幕')
        surl = _fix_url(subs[0]['subtitle_url'])
        sd = requests.get(surl,timeout=12).json()
        body = sd.get('body',[])
        text = '\n'.join([f"{i+1}. {item['content']}" for i,item in enumerate(body[:200])])
        if len(body)>200: text += f'\n...(共{len(body)}句)'
        return jsonify(subtitles=[{'lan':subs[0].get('lan',''),'lan_doc':subs[0].get('lan_doc','')}],text=text)
    except Exception as e: return jsonify(error=str(e)), 500

@app.route('/api/login/generate')
def login_gen():
    s = _login()
    r = s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate', timeout=10)
    d = r.json()
    if d.get('code')!=0: return jsonify(error=d.get('message','')), 500
    try:
        img = qrcode.make(d['data']['url'])
        buf = io.BytesIO(); img.save(buf,format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return jsonify(qrcode_key=d['data']['qrcode_key'],qr_image=f'data:image/png;base64,{b64}')
    except: return jsonify(error='qrcode模块异常'), 500

@app.route('/api/login/poll')
def login_poll():
    global _login_info
    key = request.args.get('key','')
    if not key: return jsonify(error='缺少key'), 400
    s = _login()
    r = s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll', params={'qrcode_key':key}, timeout=10)
    d = r.json()
    code = d.get('data',{}).get('code',-1)
    if code==0:
        try:
            nav = s.get('https://api.bilibili.com/x/web-interface/nav',timeout=10).json()
            if nav.get('data',{}).get('isLogin'):
                _login_info = {'uid':nav['data']['mid'],'uname':nav['data']['uname'],'face':_fix_url(nav['data'].get('face',''))}
        except: pass
    return jsonify(code=code,message=d.get('data',{}).get('message',''),user=_login_info)

@app.route('/api/login/info')
def login_info():
    return jsonify(logged_in=bool(_login_info),user=_login_info)

@app.route('/api/login/logout')
def login_logout():
    global _login_session, _login_info
    _login_session = None; _login_info = None
    return jsonify(ok=True)

@app.route('/api/followings')
def followings():
    if not _login_info: return jsonify(error='请先登录'), 401
    page = int(request.args.get('page','1'))
    try:
        r = _login_session.get('https://api.bilibili.com/x/relation/followings', params={'vmid':_login_info['uid'],'pn':page,'ps':50,'order':'desc','order_type':'attention'}, timeout=12)
        d = r.json()
        if d.get('code')!=0: return jsonify(error=d.get('message','')), 500
        users = [{'mid':u['mid'],'uname':u['uname'],'sign':u.get('sign',''),'face':_fix_url(u.get('face',''))} for u in d.get('data',{}).get('list',[])]
        return jsonify(users=users,total=d.get('data',{}).get('total',0))
    except Exception as e: return jsonify(error=str(e)), 500

# ── Frontend ────────────────────────────────────────
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
.login-bar .avatar{width:32px;height:32px;border-radius:50%;object-fit:cover;vertical-align:middle}
.login-bar .uname{font-size:14px;font-weight:500}
.login-bar button{border:1px solid #fb7299;background:#fff;color:#fb7299;padding:6px 16px;border-radius:16px;font-size:13px;cursor:pointer}
.login-bar button.logout{color:#999;border-color:#ddd}
.search-box{display:flex;gap:8px;padding:12px;background:#fff}
.search-box input{flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:20px;font-size:15px;outline:none}
.search-box input:focus{border-color:#fb7299}
.search-box button{background:#fb7299;border:none;color:#fff;padding:10px 20px;border-radius:20px;font-size:15px;cursor:pointer}
#upInfo{background:#fff;padding:16px;margin:12px;border-radius:12px;display:none;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
#upInfo img{width:48px;height:48px;border-radius:50%;object-fit:cover}
#upInfo .name{font-size:16px;font-weight:600}
#upInfo .meta{font-size:12px;color:#999}
#upInfo .sign{font-size:12px;color:#666;margin-top:4px}
.follow-section{display:none;padding:12px}
.follow-section h3{font-size:14px;color:#666;margin-bottom:8px;padding:0 4px}
.follow-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.follow-card{background:#fff;border-radius:10px;padding:10px;text-align:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.follow-card:active{transform:scale(.96)}
.follow-card img{width:40px;height:40px;border-radius:50%;object-fit:cover;margin-bottom:6px}
.follow-card .uname{font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.content{padding:0 12px}
.card{background:#fff;border-radius:12px;margin-bottom:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card .top{display:flex;cursor:pointer;transition:background .15s}
.card .thumb{width:120px;min-width:120px;height:75px;background:#eee;position:relative;overflow:hidden}
.card .thumb img{width:100%;height:100%;object-fit:cover;display:block}
.card .dur{position:absolute;right:4px;bottom:4px;background:rgba(0,0,0,.75);color:#fff;font-size:10px;padding:2px 5px;border-radius:3px}
.card .info{flex:1;padding:10px 12px;min-width:0}
.card .title{font-size:14px;font-weight:600;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:4px}
.card .meta{font-size:11px;color:#999;margin-bottom:4px;display:flex;gap:10px;flex-wrap:wrap}
.card .meta span{white-space:nowrap}
.card .desc{font-size:12px;color:#666;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .detail{display:none;padding:12px;border-top:1px solid #f0f0f0;background:#fafafa}
.card .detail.show{display:block}
.card .summary{font-size:13px;color:#333;line-height:1.6;margin-bottom:8px}
.card .tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.card .tag{background:#e3f2fd;color:#1976d2;padding:3px 10px;border-radius:12px;font-size:11px}
.card .subtitle-box{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:10px;max-height:200px;overflow-y:auto;font-size:12px;color:#555;line-height:1.7;white-space:pre-wrap}
.card .btn-row{display:flex;gap:8px;margin-bottom:10px}
.card .btn-row button{flex:1;padding:8px;border:none;border-radius:6px;font-size:12px;cursor:pointer;background:#fff;color:#666;border:1px solid #ddd}
.card .btn-row button.primary{background:#fb7299;color:#fff;border:none}
.result-stats{text-align:center;font-size:12px;color:#999;padding:4px 0 8px}
.spin{display:inline-block;width:32px;height:32px;border:3px solid #eee;border-top-color:#fb7299;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading{padding:60px;text-align:center;color:#999}
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
<div class="header"><h1>📺 B站UP主视频速览</h1><div class="sub">登录查看关注UP主 · AI概括 · 字幕获取</div></div>
<div class="login-bar" id="loginBar"><span id="loginStatus" style="font-size:13px;color:#999">未登录</span><button onclick="showLogin()">🔑 扫码登录</button></div>
<div class="search-box"><input type="text" id="searchInput" placeholder="输入UP主名字..." autocomplete="off" onkeydown="if(event.key==='Enter')search()"><button onclick="search()">搜索</button></div>
<div class="follow-section" id="followSection"><h3>⭐ 我关注的UP主</h3><div class="follow-grid" id="followList"></div></div>
<div id="upInfo"></div>
<div class="result-stats" id="stats"></div>
<div class="content" id="list"><div style="padding:60px 20px;text-align:center;color:#999;font-size:14px">👆 登录后可查看关注UP主<br><small>或直接搜索任意UP主名字</small></div></div>
<div class="modal" id="loginModal"><div class="modal-box"><h3>🔑 扫码登录B站</h3><p class="tip">请用B站APP扫码</p><img class="qr" id="qrImage" src=""><p class="tip" id="qrStatus">等待扫码...</p><button class="close-btn" onclick="closeLogin()">取消</button></div></div>
<script>
var PI=null,LI=false,UID=null;
function f(n){if(n>=1e4)return(n/1e4).toFixed(1)+'万';return n.toLocaleString()}
function ts(d){return new Date(d*1000).toLocaleDateString('zh-CN')}

async function chk(){try{var r=await fetch('/api/login/info');var d=await r.json();if(d.logged_in){LI=true;UID=d.user.uid;document.getElementById('loginBar').innerHTML='<img src="'+d.user.face+'" class="avatar"> <span class="uname">'+d.user.uname+'</span> <button class="logout" onclick="lo()">退出</button>';loadFl()}}catch(e){}}

async function sl(){document.getElementById('loginModal').classList.add('show');document.getElementById('qrStatus').textContent='生成中...';try{var r=await fetch('/api/login/generate');var d=await r.json();if(d.error){alert(d.error);cl();return}document.getElementById('qrImage').src=d.qr_image;document.getElementById('qrStatus').textContent='请用B站APP扫码';PI=setInterval(function(){pl(d.qrcode_key)},2000)}catch(e){document.getElementById('qrStatus').textContent='失败'}}
async function pl(key){try{var r=await fetch('/api/login/poll?key='+key);var d=await r.json();if(d.code===0&&d.user){clearInterval(PI);cl();chk()}else if(d.code===86038){document.getElementById('qrStatus').textContent='已过期';clearInterval(PI)}else if(d.code===86090){document.getElementById('qrStatus').textContent='已扫码，请确认'}else if(d.code===86101){document.getElementById('qrStatus').textContent='等待扫码...'}}catch(e){}}
function cl(){document.getElementById('loginModal').classList.remove('show');if(PI){clearInterval(PI);PI=null}}
async function lo(){await fetch('/api/login/logout');LI=false;UID=null;location.reload()}

async function loadFl(){try{var r=await fetch('/api/followings?page=1');var d=await r.json();if(d.error)return;document.getElementById('followSection').style.display='block';var h='';d.users.forEach(function(u){h+='<div class="follow-card" onclick="openUP('+u.mid+',\''+u.uname+'\',\''+u.face+'\',\''+(u.sign||'').replace(/'/g,'')+'\')"><img src="'+u.face+'"><div class="uname">'+u.uname+'</div></div>'});document.getElementById('followList').innerHTML=h}catch(e){}}

function openUP(mid,uname,face,sign){document.getElementById('searchInput').value='';document.getElementById('upInfo').innerHTML='<img src="'+face+'"><div><div class="name">'+uname+'</div><div class="sign">'+sign.slice(0,60)+'</div></div>';document.getElementById('upInfo').style.display='flex';document.getElementById('stats').textContent='';ld(mid)}

async function search(){var n=document.getElementById('searchInput').value.trim();if(!n)return;document.getElementById('list').innerHTML='<div class="loading"><div class="spin"></div><p>搜索中...</p></div>';document.getElementById('upInfo').style.display='none';document.getElementById('stats').textContent='';try{var r=await fetch('/api/search_up?name='+encodeURIComponent(n));var d=await r.json();if(d.error||!d.results||!d.results.length){document.getElementById('list').innerHTML='<div class="error">未找到</div>';return}var u=d.results[0];openUP(u.mid,u.uname,u.face,u.sign)}catch(e){document.getElementById('list').innerHTML='<div class="error">搜索失败</div>'}}

async function ld(mid){document.getElementById('list').innerHTML='<div class="loading"><div class="spin"></div><p>加载视频...</p></div>';try{var r=await fetch('/api/all_videos?mid='+mid+'&pages=2');var d=await r.json();if(d.error&&d.total===0){document.getElementById('list').innerHTML='<div class="error">获取失败<br><small>'+d.error+'</small><br><a href="https://space.bilibili.com/'+mid+'" class="bili-link">打开B站主页</a></div>';return}var t='共 '+d.total+' 个视频';if(d.count>d.total)t+=' (总 '+d.count+' 个)';if(d.error)t+=' | ⚠️ '+d.error.slice(0,20);document.getElementById('stats').textContent=t;rndr(d.videos)}catch(e){document.getElementById('list').innerHTML='<div class="error">加载失败</div>'}}

function rndr(vids){var h='';vids.forEach(function(v,idx){h+='<div class="card" id="c_'+idx+'"><div class="top" onclick="toggle('+idx+')"><div class="thumb"><img src="'+v.pic+'" loading="lazy" onerror="this.style.display=\'none\'"><span class="dur">'+v.length+'</span></div><div class="info"><div class="title">'+v.title+'</div><div class="meta"><span>📅 '+ts(v.created)+'</span><span>👁 '+f(v.play)+'</span><span>💬 '+f(v.comment)+'</span></div><div class="desc">'+(v.description||'')+'</div></div></div><div class="detail" id="d_'+idx+'"><div class="btn-row"><button class="primary" onclick="ls('+idx+',\''+v.bvid+'\')">🤖 AI概括</button><button onclick="lt('+idx+',\''+v.bvid+'\')">📜 字幕</button><button onclick="window.open(\'https://www.bilibili.com/video/'+v.bvid+'\')">▶️ 播放</button></div><div id="s_'+idx+'"></div><div id="t_'+idx+'"></div></div></div>'});document.getElementById('list').innerHTML=h||'<div class="error">暂无视频</div>'}

function toggle(idx){document.getElementById('d_'+idx).classList.toggle('show')}

async function ls(idx,bvid){var bx=document.getElementById('s_'+idx);bx.innerHTML='<div class="loading">🤖 AI分析中...</div>';try{var r=await fetch('/api/summarize?bvid='+bvid);var d=await r.json();var h='<div class="summary">';if(d.topic)h+='<div style="font-weight:600;color:#fb7299;margin-bottom:4px">'+d.topic+'</div>';if(d.category)h+='<div class="tags"><span class="tag">'+d.category+'</span>';if(d.recommendation)h+='<span class="tag">'+d.recommendation+'</span></div>';if(d.summary)h+='<div>'+d.summary+'</div>';h+='</div>';bx.innerHTML=h}catch(e){bx.innerHTML='<div class="error">AI概括失败</div>'}}

async function lt(idx,bvid){var bx=document.getElementById('t_'+idx);bx.innerHTML='<div class="loading">📜 获取字幕中...</div>';try{var r=await fetch('/api/subtitle?bvid='+bvid);var d=await r.json();if(d.subtitles&&d.subtitles.length){bx.innerHTML='<div class="subtitle-box">'+d.text+'</div>'}else{bx.innerHTML='<div class="error">'+d.text+'</div>'}}catch(e){bx.innerHTML='<div class="error">字幕获取失败</div>'}}

chk();
</script>
</body>
</html>'''

@app.route('/')
def index():
    return HTML

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3457)
