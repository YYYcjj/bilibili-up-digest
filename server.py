#!/usr/bin/env python3
"""B站UP主视频速览 Web 服务 - 支持登录+关注UP主+AI概括+字幕+登录持久化"""

import json, re, hashlib, time, io, base64, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import requests

try:
    import qrcode
    QR_AVAILABLE = True
except:
    QR_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except:
    PIL_AVAILABLE = False

PORT = int(os.environ.get('PORT', 3457))

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
_public_session = None
_login_session = None
_login_info = None
_wbi_cache = None
_wbi_cache_time = 0
_LOGIN_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.login_state.json')
_GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
_GITHUB_REPO = 'YYYcjj/bilibili-up-digest'
_GITHUB_STATE_PATH = '.login_state.json'

def _save_login_state():
    """保存登录状态到文件"""
    if not _login_info: return
    try:
        cookies = {}
        if _login_session:
            for cookie in _login_session.cookies:
                if cookie.name in ('SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5'):
                    cookies[cookie.name] = cookie.value
        with open(_LOGIN_STATE_FILE, 'w') as f:
            json.dump({'info': _login_info, 'cookies': cookies}, f, ensure_ascii=False)
        if _GITHUB_TOKEN:
            _save_to_github()
    except Exception as e:
        print(f'[WARN] 保存登录状态失败: {e}')

def _save_to_github():
    """上传登录状态到 GitHub（持久化）"""
    try:
        with open(_LOGIN_STATE_FILE) as f:
            content = f.read()
        b64 = base64.b64encode(content.encode()).decode()
        url = f'https://api.github.com/repos/{_GITHUB_REPO}/contents/{_GITHUB_STATE_PATH}'
        r = requests.get(url, headers={'Authorization': f'Bearer {_GITHUB_TOKEN}'}, timeout=10)
        sha = r.json().get('sha', '') if r.status_code == 200 else ''
        body = {'message': 'save login state', 'content': b64, 'branch': 'main'}
        if sha:
            body['sha'] = sha
        requests.put(url, headers={'Authorization': f'Bearer {_GITHUB_TOKEN}'}, json=body, timeout=10)
        print('[INFO] 登录状态已同步到 GitHub')
    except Exception as e:
        print(f'[WARN] GitHub 同步失败: {e}')

def _load_from_github():
    """从 GitHub 下载登录状态"""
    try:
        url = f'https://api.github.com/repos/{_GITHUB_REPO}/contents/{_GITHUB_STATE_PATH}'
        r = requests.get(url, headers={'Authorization': f'Bearer {_GITHUB_TOKEN}'}, timeout=10)
        if r.status_code != 200:
            return
        data = r.json()
        decoded = base64.b64decode(data.get('content', '')).decode()
        with open(_LOGIN_STATE_FILE, 'w') as f:
            f.write(decoded)
        print('[INFO] 从 GitHub 恢复登录状态')
    except Exception as e:
        print(f'[WARN] GitHub 下载失败: {e}')

def _load_login_state():
    """从文件加载登录状态"""
    global _login_session, _login_info
    if not os.path.exists(_LOGIN_STATE_FILE):
        if _GITHUB_TOKEN:
            _load_from_github()
    if not os.path.exists(_LOGIN_STATE_FILE):
        return False
    try:
        with open(_LOGIN_STATE_FILE) as f:
            state = json.load(f)
        _login_info = state.get('info')
        cookies = state.get('cookies', {})
        if _login_info and cookies:
            s = _ensure_login()
            for name, value in cookies.items():
                s.cookies.set(name, value, domain='.bilibili.com')
            try:
                nav = s.get('https://api.bilibili.com/x/web-interface/nav', timeout=10).json()
                if nav.get('data', {}).get('isLogin'):
                    _login_info = {'uid': nav['data']['mid'], 'uname': nav['data']['uname'],
                                   'face': _fix_url(nav['data'].get('face',''))}
                    _save_login_state()
                    return True
                else:
                    _login_info = None
            except: pass
        return False
    except: return False

def _fix_url(url):
    if not url: return url
    if url.startswith('//'): return 'https:' + url
    if url.startswith('http://'): return url.replace('http://', 'https://', 1)
    return url

def _ensure_public():
    global _public_session
    if _public_session is None:
        _public_session = requests.Session()
        _public_session.headers.update(HEADERS)
        try: _public_session.get('https://www.bilibili.com/', timeout=10)
        except: pass
    return _public_session

def _ensure_login():
    global _login_session
    if _login_session is None:
        _login_session = requests.Session()
        _login_session.headers.update(HEADERS)
    return _login_session

def _get_session():
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

def compute_scores(vid_meta):
    import math
    length_str = vid_meta.get('length', '00:00')
    parts = length_str.split(':')
    d = max(int(parts[0]) * 60 + int(parts[1]) if len(parts) >= 2 else 60, 10)
    if d < 60: dur_s = 2
    elif d < 300: dur_s = 3 + (d-60) / 120
    elif d < 900: dur_s = 5 + (d-300) / 300
    elif d < 1800: dur_s = 7
    else: dur_s = max(3, 8 - (d-1800) / 900)
    learning = round(dur_s * 0.6 + 1.5, 1)
    knowledge = round(dur_s * 0.65 + 0.5, 1)
    horizon = round(max(2, dur_s * 0.55) + 1, 1)
    overall = round(learning * 0.4 + knowledge * 0.35 + horizon * 0.25, 1)
    return {k: max(1, min(10, v)) for k, v in {
        'learning': learning, 'knowledge': knowledge,
        'horizon': horizon, 'overall': overall,
    }.items()}

def _bili_get(path, params=None):
    s = _get_session()
    resp = s.get('https://api.bilibili.com' + path, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"B站API错误({data.get('code')}): {data.get('message','unknown')}")
    return data

def summarize_video(vid):
    if not LLM_API_KEY: return {'topic': vid.get('title',''), 'summary': '未配置AI Key', 'recommendation': '可选', 'category': '未知'}
    try:
        prompt = f"""对以下B站视频进行简短概括（30-60字）并给出推荐度：

标题：{vid.get('title','')}
简介：{(vid.get('description','') or vid.get('desc',''))[:300]}
时长：{vid.get('length','')}

请用JSON输出：{{"topic":"一句话主题","summary":"30-60字概括","category":"分类标签","recommendation":"强烈推荐/推荐/可选/可跳过"}}"""
        r = requests.post(f"{LLM_API_BASE}/chat/completions", headers={"Authorization": f"Bearer {LLM_API_KEY}"}, json={"model": LLM_MODEL, "messages": [{"role":"user","content":prompt}], "temperature":0.3, "max_tokens":200}, timeout=20)
        d = r.json()
        txt = d['choices'][0]['message']['content'].strip()
        if '```json' in txt: txt = txt.split('```json')[1].split('```')[0]
        elif '```' in txt: txt = txt.split('```')[1].split('```')[0]
        return json.loads(txt)
    except Exception as e: return {'topic': vid.get('title',''), 'summary': f'AI失败: {str(e)[:50]}', 'recommendation': '可选', 'category': '未知'}

def get_subtitle(bvid):
    try:
        info = _bili_get('/x/web-interface/view', {'bvid': bvid})
        cid = info['data']['cid']
        player = _bili_get('/x/player/v2', {'bvid': bvid, 'cid': cid})
        subs = player.get('data', {}).get('subtitle', {}).get('subtitles', [])
        if not subs: return {'subtitles': [], 'text': '该视频没有字幕'}
        sub_url = _fix_url(subs[0]['subtitle_url'])
        sub_resp = requests.get(sub_url, timeout=15)
        sub_data = sub_resp.json()
        body = sub_data.get('body', [])
        text = '\n'.join([f"{i+1}. {item['content']}" for i, item in enumerate(body)])
        return {'subtitles': [{'lan': subs[0].get('lan',''), 'lan_doc': subs[0].get('lan_doc','')}], 'text': text, 'total': len(body)}
    except Exception as e: return {'subtitles': [], 'text': f'获取失败: {str(e)}'}

def _get_bilibili_ai(bvid, cid, up_mid=0):
    try:
        params = _sign_params({'bvid': bvid, 'cid': cid, 'up_mid': up_mid})
        data = _bili_get('/x/web-interface/view/conclusion/get', params)
        d = data.get('data', {})
        if d.get('code') != 0: return None
        mr = d.get('model_result', {})
        summary = mr.get('summary', '')
        outline = mr.get('outline', [])
        subtitle_list = mr.get('subtitle', [])
        subtitle_text = ''
        if subtitle_list and subtitle_list[0].get('part_subtitle'):
            parts = subtitle_list[0]['part_subtitle']
            subtitle_text = '\n'.join([f"[{int(p['start_timestamp'])//60:02d}:{int(p['start_timestamp'])%60:02d}] {p['content']}" for p in parts])
        return {'summary': summary, 'outline': [{'title': o.get('title',''), 'timestamp': o.get('timestamp',0), 'points': [{'ts': p.get('timestamp',0), 'text': p.get('content','')} for p in o.get('part_outline',[])]} for o in outline], 'subtitle_text': subtitle_text, 'has_summary': bool(summary), 'has_subtitle': bool(subtitle_text)}
    except: return None

def handle_api(path, query):
    global _login_session, _login_info

    if path == '/api/login/generate':
        if not QR_AVAILABLE: return 500, {'error': 'qrcode未安装'}
        s = _ensure_login()
        resp = s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate', timeout=10)
        data = resp.json()
        if data.get('code') != 0: return 500, {'error': data.get('message','')}
        qr_url = data['data']['url']; qr_key = data['data']['qrcode_key']
        img = qrcode.make(qr_url); buf = io.BytesIO(); img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return 200, {'qrcode_key': qr_key, 'qr_image': f'data:image/png;base64,{b64}'}

    if path == '/api/login/poll':
        key = query.get('key', [''])[0]
        if not key: return 400, {'error': '缺少 key'}
        s = _ensure_login()
        resp = s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll', params={'qrcode_key': key}, timeout=10)
        data = resp.json()
        code = data.get('data', {}).get('code', -1)
        if code == 0:
            try:
                nav = s.get('https://api.bilibili.com/x/web-interface/nav', timeout=10).json()
                if nav.get('data', {}).get('isLogin'):
                    _login_info = {'uid': nav['data']['mid'], 'uname': nav['data']['uname'], 'face': _fix_url(nav['data'].get('face',''))}
                    _save_login_state()
            except: pass
        return 200, {'code': code, 'message': data.get('data', {}).get('message',''), 'user': _login_info}

    if path == '/api/login/info':
        return 200, {'logged_in': bool(_login_info), 'user': _login_info}

    if path == '/api/login/logout':
        _login_session = None
        _login_info = None
        if os.path.exists(_LOGIN_STATE_FILE):
            os.remove(_LOGIN_STATE_FILE)
        return 200, {'ok': True}

    if path == '/api/followings':
        if not _login_info: return 401, {'error': '请先登录'}
        page = int(query.get('page', ['1'])[0])
        try:
            s = _login_session
            resp = s.get('https://api.bilibili.com/x/relation/followings', params={'vmid': _login_info['uid'], 'pn': page, 'ps': 50, 'order': 'desc', 'order_type': 'attention'}, timeout=15)
            data = resp.json()
            if data.get('code') != 0: return 500, {'error': data.get('message', 'unknown')}
            users = []
            for u in data.get('data', {}).get('list', []):
                users.append({'mid': u['mid'], 'uname': u['uname'], 'sign': u.get('sign',''), 'face': _fix_url(u.get('face',''))})
            return 200, {'users': users, 'total': data.get('data',{}).get('total',0)}
        except Exception as e: return 500, {'error': str(e)}

    if path == '/api/search_up':
        name = query.get('name', [''])[0]
        if not name: return 400, {'error': '缺少 name'}
        try:
            data = _bili_get('/x/web-interface/search/type', {'search_type': 'bili_user', 'keyword': name})
            results = []
            for u in (data.get('data', {}).get('result', []) or []):
                results.append({'mid': u['mid'], 'uname': u['uname'], 'sign': u.get('usign',''), 'fans': u.get('fans',0), 'videos': u.get('videos',0), 'face': _fix_url(u.get('upic',''))})
            return 200, {'results': results}
        except Exception as e: return 500, {'error': str(e)}

    if path == '/api/all_videos':
        try:
            mid = int(query.get('mid', ['0'])[0])
        except (ValueError, TypeError):
            return 400, {'error': 'mid 参数无效'}
        page = int(query.get('page', ['1'])[0])
        ps = int(query.get('ps', ['30'])[0])
        order = query.get('order', ['pubdate'])[0]
        if not mid: return 400, {'error': '缺少 mid'}
        ps = max(10, min(50, ps))
        try:
            params = _sign_params({'mid': mid, 'ps': ps, 'pn': page, 'order': order})
            data = _bili_get('/x/space/wbi/arc/search', params)
            vlist = data['data']['list']['vlist']
            count = data['data']['page']['count']
            videos = []
            for v in vlist:
                videos.append({
                    'bvid': v['bvid'], 'title': v['title'],
                    'description': v.get('description',''),
                    'length': v['length'], 'created': v['created'],
                    'play': v.get('play',0), 'comment': v.get('comment',0),
                    'video_review': v.get('video_review',0), 'pic': _fix_url(v.get('pic','')),
                    'tname': v.get('tname',''),
                    'scores': compute_scores({'play':v.get('play',0),'length':v['length']}),
                })
            return 200, {'videos': videos, 'total': len(videos), 'count': count,
                         'page': page, 'ps': ps, 'has_more': page * ps < count}
        except Exception as e: return 500, {'error': str(e)}

    if path == '/api/summarize':
        bvid = query.get('bvid', [''])[0]
        if not bvid: return 400, {'error': '缺少 bvid'}
        try:
            info = _bili_get('/x/web-interface/view', {'bvid': bvid})
            vid = info['data']
            cid = vid['cid']
            up_mid = vid.get('owner', {}).get('mid', 0)
            bili_ai = _get_bilibili_ai(bvid, cid, up_mid)
            if bili_ai and (bili_ai['has_summary'] or bili_ai['has_subtitle']):
                return 200, {
                    'source': 'bilibili_ai',
                    'summary': bili_ai['summary'] or vid.get('title', ''),
                    'outline': bili_ai['outline'],
                    'category': vid.get('tname', ''),
                }
            vid_data = {
                'title': vid['title'], 'desc': vid.get('desc',''),
                'length': vid['duration'],
                'tname': vid.get('tname',''), 'tags': [t['tag_name'] for t in vid.get('tags',[])][:10]
            }
            summary = summarize_video(vid_data)
            summary['source'] = 'llm'
            return 200, summary
        except Exception as e: return 500, {'error': str(e)}

    if path == '/api/subtitle':
        bvid = query.get('bvid', [''])[0]
        if not bvid: return 400, {'error': '缺少 bvid'}
        try:
            info = _bili_get('/x/web-interface/view', {'bvid': bvid})
            cid = info['data']['cid']
            up_mid = info['data'].get('owner', {}).get('mid', 0)
            bili_ai = _get_bilibili_ai(bvid, cid, up_mid)
            if bili_ai and bili_ai['has_subtitle']:
                return 200, {
                    'source': 'bilibili_ai',
                    'text': bili_ai['subtitle_text'],
                    'insufficient': False, 'subtitles': [{'lan': 'zh', 'lan_doc': 'AI字幕'}],
                }
            result = get_subtitle(bvid)
            return 200, result
        except Exception as e: return 200, {'text': '', 'insufficient': True, 'subtitles': [], 'error': str(e)}

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
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f5f5;color:#333;min-height:100vh}
.header{background:linear-gradient(135deg,#fb7299,#fc8f6e);color:#fff;padding:16px 16px 14px;position:sticky;top:0;z-index:100;display:flex;align-items:center;gap:10px}
.header a{color:#fff;text-decoration:none;font-size:20px;min-width:24px;text-align:center;line-height:1}
.header .h-title{font-size:17px;font-weight:600;line-height:1.3;flex:1}
.login-bar{display:flex;justify-content:center;align-items:center;gap:8px;padding:10px 12px;background:#fff;border-bottom:1px solid #eee}
.login-bar .avatar{width:30px;height:30px;border-radius:50%;object-fit:cover}
.login-bar .uname{font-size:13px;font-weight:500}
.login-bar button{border:1px solid #fb7299;background:#fff;color:#fb7299;padding:4px 14px;border-radius:14px;font-size:12px;cursor:pointer}
.login-bar button.logout{color:#999;border-color:#ddd}
.search-box{display:flex;gap:8px;padding:12px;background:#fff}
.search-box input{flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:20px;font-size:15px;outline:none}
.search-box input:focus{border-color:#fb7299}
.search-box button{background:#fb7299;border:none;color:#fff;padding:10px 20px;border-radius:20px;font-size:15px;cursor:pointer;white-space:nowrap}
.follow-section{padding:12px 12px 0}
.follow-section h3{font-size:14px;color:#666;margin-bottom:8px}
.follow-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px}
.follow-card{background:#fff;border-radius:10px;padding:8px;text-align:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.follow-card img{width:36px;height:36px;border-radius:50%;object-fit:cover;margin-bottom:4px}
.follow-card .uname{font-size:11px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.follow-card .sign{font-size:10px;color:#999;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:1px}
.content{padding:0 12px;padding-bottom:80px}
.card{background:#fff;border-radius:12px;margin-bottom:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);cursor:pointer}.card-inner{display:flex}
.card .thumb{width:130px;min-width:130px;height:82px;background:#eee;position:relative;overflow:hidden}
.card .thumb img{width:100%;height:100%;object-fit:cover;display:block}
.card .dur{position:absolute;right:4px;bottom:4px;background:rgba(0,0,0,.75);color:#fff;font-size:10px;padding:2px 5px;border-radius:3px}
.card .info{flex:1;padding:10px 12px;min-width:0}
.card .title{font-size:14px;font-weight:600;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:4px}
.card .meta{font-size:11px;color:#999;display:flex;gap:10px;flex-wrap:wrap}.card .meta span{white-space:nowrap}
.score-row{display:flex;gap:3px;margin-top:3px;flex-wrap:wrap}.score-row .sb{font-size:10px;padding:1px 5px;border-radius:6px;background:#f0f0f0;color:#888;white-space:nowrap}.score-row .sb.hi{background:#e8f5e9;color:#388e3c}
.result-stats{text-align:center;font-size:12px;color:#999;padding:8px 0 4px}
.loading{padding:60px 20px;text-align:center;color:#999}
.loading .spinner{display:inline-block;width:32px;height:32px;border:3px solid #eee;border-top-color:#fb7299;border-radius:50%;animation:spin .8s linear infinite;margin-bottom:10px}
@keyframes spin{to{transform:rotate(360deg)}}
.error{padding:40px 20px;text-align:center;color:#e74c3c;font-size:14px}
.filter-bar{display:flex;align-items:center;gap:6px;padding:8px 12px;font-size:12px;background:#fff;border-bottom:1px solid #f0f0f0}
.filter-bar select{padding:4px 8px;border:1px solid #ddd;border-radius:6px;font-size:12px;background:#fff}
.filter-bar .fl{color:#999}
.up-info{background:#fff;padding:12px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #f0f0f0}
.up-info img{width:40px;height:40px;border-radius:50%;object-fit:cover}
.up-info .name{font-size:15px;font-weight:600}.up-info .sign{font-size:11px;color:#999;margin-top:2px}
.modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:200;align-items:center;justify-content:center}
.modal.show{display:flex}
.modal-box{background:#fff;border-radius:16px;padding:24px;max-width:300px;width:90%;text-align:center}
.modal-box h3{font-size:18px;margin-bottom:8px}.modal-box .qr{width:200px;height:200px;margin:12px auto;display:block}
.modal-box .tip{font-size:13px;color:#999}
.modal-box .close-btn{margin-top:16px;padding:8px 24px;border:1px solid #ddd;border-radius:20px;background:#fff;color:#666;font-size:14px;cursor:pointer}
.pagination{display:flex;justify-content:center;gap:4px;padding:12px;flex-wrap:wrap}
.pagination button{padding:4px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;font-size:12px;cursor:pointer;min-width:28px}
.pagination button.active{background:#fb7299;color:#fff;border-color:#fb7299;font-weight:600}
.pagination button:disabled{opacity:.3;cursor:default}
.vp-section{background:#fff;border-radius:12px;padding:16px;margin:12px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.vp-section .sec-title{font-size:15px;font-weight:600;color:#fb7299;margin-bottom:12px;display:flex;align-items:center;gap:6px}
.vp-section .ai-badge{font-size:11px;background:#fff3e0;color:#e65100;padding:2px 8px;border-radius:10px}
.subtitle-text{font-size:14px;color:#444;line-height:2;white-space:pre-wrap;word-break:break-all}
.outline-wrap{margin:8px 0}.outline-item{margin-bottom:6px}
.outline-title{font-weight:600;color:#1976d2;font-size:13px;margin-bottom:2px}
.outline-points{margin:0;padding-left:16px;font-size:12px;color:#666}.outline-points li{margin-bottom:2px}
.btn-row{display:flex;gap:6px;margin:8px 0}
.btn-row button{padding:6px 12px;border:none;border-radius:6px;font-size:12px;cursor:pointer;background:#fb7299;color:#fff}
</style>
</head>
<body>
<script>
(function(){
var p=new URLSearchParams(location.search);
var b=p.get('bvid');
if(b){renderPage('video',{bvid:b,title:p.get('title')||''});return}
var u=p.get('up');
if(u){renderPage('up',{mid:u});return}
renderPage('home');
})();

function fmt(n){if(n>=1e4)return(n/1e4).toFixed(1)+'万';return n.toLocaleString()}
function ts(d){return new Date(d*1000).toLocaleDateString('zh-CN')}
function he(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function fmtTs(s){if(!s||s<0)return'';var m=Math.floor(s/60);var sec=Math.floor(s%60);return m+':'+String(sec).padStart(2,'0')}

var POLL=null,LOGINED=false,LUID=null;
async function checkLogin(){
try{var r=await fetch('/api/login/info');var d=await r.json();
if(d.logged_in){LOGINED=true;LUID=d.user.uid;
var lb=document.getElementById('loginBar');
if(lb)lb.innerHTML='<img src="'+d.user.face+'" class="avatar"> <span class="uname">'+d.user.uname+'</span> <button class="logout" onclick="logout()">退出</button>';loadFollowings()}
}catch(e){}}
async function showLogin(){
document.getElementById('loginModal').classList.add('show');
document.getElementById('qrStatus').textContent='正在生成...';
try{var r=await fetch('/api/login/generate');var d=await r.json();
if(d.error){alert(d.error);closeLogin();return}
document.getElementById('qrImage').src=d.qr_image;
document.getElementById('qrStatus').textContent='请用B站APP扫码';
POLL=setInterval(function(){pollLogin(d.qrcode_key)},2000)}catch(e){
document.getElementById('qrStatus').textContent='生成失败:'+e.message}}
async function pollLogin(key){
try{var r=await fetch('/api/login/poll?key='+key);var d=await r.json();
if(d.code===0&&d.user){clearInterval(POLL);closeLogin();checkLogin()}
else if(d.code===86038){document.getElementById('qrStatus').textContent='二维码已过期';clearInterval(POLL)}
else if(d.code===86090){document.getElementById('qrStatus').textContent='已扫码，请确认'}
else if(d.code===86101){document.getElementById('qrStatus').textContent='等待扫码...'}
}catch(e){}}
function closeLogin(){document.getElementById('loginModal').classList.remove('show');if(POLL){clearInterval(POLL);POLL=null}}
async function logout(){await fetch('/api/login/logout');LOGINED=false;LUID=null;location.reload()}
async function loadFollowings(){
try{var r=await fetch('/api/followings?page=1');var d=await r.json();
if(d.error)return;
var fs=document.getElementById('followSection');if(fs)fs.style.display='block';
var fl=document.getElementById('followList');
if(fl){var h='';d.users.forEach(function(u){h+='<div class="follow-card" onclick="navUP('+u.mid+')"><img src="'+u.face+'"><div class="uname">'+u.uname+'</div><div class="sign">'+he((u.sign||'').slice(0,20))+'</div></div>'});fl.innerHTML=h}
}catch(e){}}
function navUP(mid){location.href=location.pathname+'?up='+mid}

function renderPage(page,data){
data=data||{};
if(page==='home')renderHome();
else if(page==='up')renderUPPage(data.mid);
else if(page==='video')renderVideoPage(data.bvid,data.title);
}

function renderHome(){
document.body.innerHTML=
'<div class="header"><span class="h-title" style="font-size:20px;text-align:center;flex:1">📺 B站UP主视频速览</span></div>'+
'<div class="login-bar" id="loginBar"><span style="font-size:13px;color:#999">未登录</span> <button onclick="showLogin()">🔑 扫码登录</button></div>'+
'<div class="search-box"><input type="text" id="searchInput" placeholder="输入UP主名字..." autocomplete="off" onkeydown="if(event.key===\'Enter\')doSearch()"><button onclick="doSearch()">搜索</button></div>'+
'<div class="follow-section" id="followSection" style="display:none"><h3>⭐ 我关注的UP主</h3><div class="follow-grid" id="followList"></div></div>'+
'<div class="content" id="list"><div style="padding:60px 20px;text-align:center;color:#999;font-size:14px">👆 登录后可查看关注UP主<br><small>或直接搜索任意UP主名字</small></div></div>'+
'<div class="modal" id="loginModal"><div class="modal-box"><h3>🔑 扫码登录B站</h3><p class="tip">请用B站APP扫码</p><img class="qr" id="qrImage" src="" alt="QR"><p class="tip" id="qrStatus">等待扫码...</p><button class="close-btn" onclick="closeLogin()">取消</button></div></div>';
window.doSearch=function(){
var name=document.getElementById('searchInput').value.trim();if(!name)return;
var lst=document.getElementById('list');lst.innerHTML='<div class="loading"><div class="spinner"></div><p>搜索中...</p></div>';
fetch('/api/search_up?name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
if(!d.results||!d.results.length){lst.innerHTML='<div class="error">未找到</div>';return}
navUP(d.results[0].mid);
}).catch(function(){lst.innerHTML='<div class="error">搜索失败</div>'});
};
checkLogin();
}

var _mid,_page=1,_total,_all=[],PS=30;
function renderUPPage(mid){
if(!mid){document.body.innerHTML='<div class="error">缺少UP主ID</div>';return}
_mid=mid;_page=1;_all=[];
document.body.innerHTML='<div class="header"><a href="'+location.pathname+'">←</a><span class="h-title">加载中...</span></div><div class="content" id="uplist"><div class="loading"><div class="spinner"></div><p>加载视频...</p></div></div>';
loadUPInfo(mid);
loadUPVideos(mid,1);
}
async function loadUPInfo(mid){
if(!mid)return;
try{
var d=await fetch('/api/all_videos?mid='+mid+'&page=1&ps=1').then(function(r){return r.json()});
var vc=d.count||0;
try{
var sr=await fetch('/api/search_up?name='+mid).then(function(r){return r.json()});
if(sr.results&&sr.results.length){
var u=sr.results[0];document.querySelector('.h-title').textContent=u.uname;
var si=document.createElement('div');si.className='up-info';
si.innerHTML='<img src="'+u.face+'"><div><div class="name">'+u.uname+'</div><div class="sign">'+(u.sign||'').slice(0,50)+' · '+fmt(u.fans)+'粉丝 · '+fmt(vc)+'视频</div></div>';
document.querySelector('.content').insertAdjacentElement('beforebegin',si);
}else{document.querySelector('.h-title').textContent='UP主 (MID:'+mid+')'}
}catch(e){document.querySelector('.h-title').textContent='UP主 (MID:'+mid+')'}
}catch(e){document.querySelector('.h-title').textContent='UP主 (MID:'+mid+')'}
}
async function loadUPVideos(mid,page){
if(!mid||mid==='undefined'){var el=document.getElementById('uplist');if(el)el.innerHTML='<div class="error">无效的UP主ID</div>';return}
try{
var d=await fetch('/api/all_videos?mid='+mid+'&page='+page+'&ps='+PS).then(function(r){return r.json()});
if(!d.videos){throw new Error(d.error||'返回数据为空')}
_page=page;_total=d.count||0;_all=d.videos;
var h='<div class="result-stats">共 '+_total+'个 / 第'+page+'页</div>'+
'<div class="filter-bar"><span class="fl">排序：</span><select onchange="sortV(this.value)"><option value="newest">最新发布</option><option value="hot">最多播放</option><option value="comment">最多评论</option></select></div>'+
'<div id="vlist"></div>';
document.getElementById('uplist').innerHTML=h;
renderCards(_all);
renderPager();
}catch(e){document.getElementById('uplist').innerHTML='<div class="error">加载失败: '+e.message+'</div>'}
}
function renderCards(vids){
var c='';vids.forEach(function(v){
var sc=v.scores||{};var sb='<div class="score-row">';
var dims={learning:'学习价值',knowledge:'知识深度',horizon:'视野拓展',overall:'综合'};
for(var k in dims){var s=sc[k]||0;sb+='<span class="sb'+(s>=7?' hi':'')+'">'+dims[k]+':'+s.toFixed(1)+'</span>'}
sb+='</div>';
c+='<div class="card" onclick="window.open(\''+location.pathname+'?bvid='+v.bvid+'&title='+encodeURIComponent(v.title.replace(/'/g,''))+'\')"><div class="card-inner"><div class="thumb"><img src="'+v.pic+'" loading="lazy" onerror="this.style.display=\'none\'"><span class="dur">'+v.length+'</span></div><div class="info"><div class="title">'+v.title+'</div><div class="meta"><span>📅 '+ts(v.created)+'</span><span>👁 '+fmt(v.play)+'</span><span>💬 '+fmt(v.comment)+'</span></div>'+sb+'</div></div></div>';
});
document.getElementById('vlist').innerHTML=c||'<div class="error">暂无视频</div>';
}
function renderPager(){
var t=Math.ceil(_total/PS);if(t<=1)return;
var p=document.createElement('div');p.className='pagination';
var h='<button onclick="goPage(1)"'+(_page===1?' disabled':'')+'>&lt;&lt;</button>';
h+='<button onclick="goPage('+(_page-1)+')"'+(_page===1?' disabled':'')+'>&lt;</button>';
var s=Math.max(1,_page-2),e=Math.min(t,_page+2);
for(var i=s;i<=e;i++)h+='<button onclick="goPage('+i+')"'+(_page===i?' class="active"':'')+'>'+i+'</button>';
h+='<button onclick="goPage('+(_page+1)+')"'+(_page===t?' disabled':'')+'>&gt;</button>';
h+='<button onclick="goPage('+t+')"'+(_page===t?' disabled':'')+'>&gt;&gt;</button>';
p.innerHTML=h;document.getElementById('uplist').appendChild(p);
}
function goPage(p){if(!_mid)return;loadUPVideos(_mid,p);window.scrollTo(0,0)}
function sortV(order){
var v=[].concat(_all);
if(order==='hot')v.sort(function(a,b){return(b.play||0)-(a.play||0)});
else if(order==='comment')v.sort(function(a,b){return(b.comment||0)-(b.comment||0)});
else v.sort(function(a,b){return(b.created||0)-(a.created||0)});
_all=v;renderCards(v);
}

function renderVideoPage(bvid,title){
document.body.innerHTML='<div class="header"><a href="javascript:history.back()">←</a><span class="h-title">'+he(title||'视频详情')+'</span></div>'+
'<div class="vp-section"><div class="sec-title">🤖 AI 概括分析</div><div id="vsl" style="text-align:center;color:#999;padding:20px">DeepSeek AI 分析中...</div><div id="vsc"></div></div>'+
'<div class="vp-section"><div class="sec-title" id="sst">📜 视频文字版</div><div id="ssl" style="text-align:center;color:#999;padding:20px">获取文字版中...</div><div id="ssc"></div></div>'+
'<div class="btn-row" style="padding:0 12px 20px"><button onclick="window.open(\'https://www.bilibili.com/video/'+bvid+'\')">▶️ 播放</button></div>';
loadSummary(bvid);
loadSub(bvid);
}
async function loadSummary(bvid){
try{
var r=await fetch('/api/summarize?bvid='+bvid);var d=await r.json();
document.getElementById('vsl').style.display='none';var h='';
if(d.source==='bilibili_ai')h+='<span class="ai-badge" style="background:#fb7299;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px">B站AI总结</span>';
if(d.outline&&d.outline.length){h+='<div class="outline-wrap">';
d.outline.forEach(function(o){h+='<div class="outline-item"><div class="outline-title">'+fmtTs(o.timestamp)+' '+he(o.title||'')+'</div>';
if(o.points&&o.points.length){h+='<ul class="outline-points">';o.points.forEach(function(p){h+='<li>'+he(p.text)+'</li>'});h+='</ul>'}
h+='</div>'});h+='</div>';}
if(d.summary)h+='<div style="line-height:1.7;margin:8px 0">'+he(d.summary||'')+'</div>';
document.getElementById('vsc').innerHTML=h||'<div style="color:#999;text-align:center;padding:10px">暂无概括数据</div>';
}catch(e){document.getElementById('vsl').style.display='none';document.getElementById('vsc').innerHTML='<div style="color:#e74c3c;text-align:center;padding:10px">AI概括失败</div>'}
}
async function loadSub(bvid){
try{
var r=await fetch('/api/subtitle?bvid='+bvid);var d=await r.json();
document.getElementById('ssl').style.display='none';
if(d.source==='bilibili_ai')document.getElementById('sst').innerHTML='📜 AI字幕（B站识别）';
else if(d.subtitles&&d.subtitles.length)document.getElementById('sst').innerHTML='📜 CC字幕 ('+d.subtitles[0].lan_doc+')';
if(d.text&&d.text.length>20)document.getElementById('ssc').innerHTML='<div class="subtitle-text">'+he(d.text)+'</div>';
else document.getElementById('ssc').innerHTML='<div style="color:#999;text-align:center;padding:20px">'+(d.text||'暂无可用的文字版内容')+'</div>';
}catch(e){document.getElementById('ssl').style.display='none';document.getElementById('ssc').innerHTML='<div style="color:#e74c3c;text-align:center;padding:10px">获取失败</div>'}
}
</script>
</body>
</html>
'''


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
    print(f'[INFO] 启动B站UP主视频速览 端口:{PORT}')
    print(f'[INFO] LLM: {"已配置" if LLM_API_KEY else "未配置"}')
    print(f'[INFO] GitHub持久化: {"已配置" if _GITHUB_TOKEN else "未配置"}')
    if _load_login_state():
        print(f'[INFO] 登录已恢复: {_login_info["uname"]}')
    HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()