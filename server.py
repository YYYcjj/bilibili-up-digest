#!/usr/bin/env python3
"""B站UP主视频速览 Web 服务 - 支持登录+关注UP主+AI概括+字幕"""
import json,re,hashlib,time,io,base64,os
from http.server import HTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,urlencode
import requests
try:import qrcode;QR_AVAILABLE=True
except:QR_AVAILABLE=False
try:from PIL import Image;PIL_AVAILABLE=True
except:PIL_AVAILABLE=False
PORT=int(os.environ.get('PORT',3457))
LLM_API_KEY=os.environ.get('LLM_API_KEY','')
LLM_API_BASE=os.environ.get('LLM_API_BASE','https://api.openai.com/v1')
LLM_MODEL=os.environ.get('LLM_MODEL','gpt-4o-mini')
MIXIN_KEY_ENC_TAB=[46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,52,44,34]
HEADERS={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'}
_public_session=None
_login_session=None
_login_info=None
_wbi_cache=None
_wbi_cache_time=0
_LOGIN_STATE_FILE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'.login_state.json')
def _save_login_state():
 if not _login_info:return
 try:
  c={}
  if _login_session:
   for k in _login_session.cookies:
    if k.name in('SESSDATA','bili_jct','DedeUserID','DedeUserID__ckMd5'):c[k.name]=k.value
  with open(_LOGIN_STATE_FILE,'w')as f:json.dump({'info':_login_info,'cookies':c},f,ensure_ascii=False)
 except Exception as e:print(f'[WARN]{e}')
def _load_login_state():
 global _login_session,_login_info
 if not os.path.exists(_LOGIN_STATE_FILE):return False
 try:
  with open(_LOGIN_STATE_FILE)as f:state=json.load(f)
  _login_info=state.get('info');cookies=state.get('cookies',{})
  if _login_info and cookies:
   s=_ensure_login()
   for n,v in cookies.items():s.cookies.set(n,v,domain='.bilibili.com')
   try:
    nav=s.get('https://api.bilibili.com/x/web-interface/nav',timeout=10).json()
    if nav.get('data',{}).get('isLogin'):
     _login_info={'uid':nav['data']['mid'],'uname':nav['data']['uname'],'face':_fix_url(nav['data'].get('face',''))}
     _save_login_state();return True
   except:pass
  return False
 except:return False
def _fix_url(u):
 if not u:return u
 if u.startswith('//'):return'https:'+u
 if u.startswith('http://'):return u.replace('http://','https://',1)
 return u
def _ensure_public():
 global _public_session
 if _public_session is None:_public_session=requests.Session();_public_session.headers.update(HEADERS)
 return _public_session
def _ensure_login():
 global _login_session
 if _login_session is None:_login_session=requests.Session();_login_session.headers.update(HEADERS)
 return _login_session
def _get_session():
 if _login_session and _login_info:return _login_session
 return _ensure_public()
def _get_wbi_keys():
 global _wbi_cache,_wbi_cache_time
 now=time.time()
 if _wbi_cache and(now-_wbi_cache_time)<900:return _wbi_cache
 s=_ensure_public();r=s.get('https://api.bilibili.com/x/web-interface/nav',timeout=10);d=r.json()
 w=d['data']['wbi_img'];ik=re.search(r'wbi/(.*?)\.',w['img_url']).group(1);sk=re.search(r'wbi/(.*?)\.',w['sub_url']).group(1)
 mk=''.join((ik+sk)[i]for i in MIXIN_KEY_ENC_TAB)[:32];_wbi_cache={'mixin_key':mk};_wbi_cache_time=now
 return _wbi_cache
def _sign_params(p):
 w=_get_wbi_keys();p['wts']=int(time.time());p=dict(sorted(p.items()))
 q=urlencode(p);p['w_rid']=hashlib.md5((q+w['mixin_key']).encode()).hexdigest();return p
def compute_scores(vid_meta):
 import math;ls=vid_meta.get('length','00:00');ps=ls.split(':')
 d=max(int(ps[0])*60+int(ps[1])if len(ps)>=2 else 60,10)
 if d<60:dur=2
 elif d<300:dur=3+(d-60)/120
 elif d<900:dur=5+(d-300)/300
 elif d<1800:dur=7
 else:dur=max(3,8-(d-1800)/900)
 l=round(dur*0.6+1.5,1);k=round(dur*0.65+0.5,1);h=round(max(2,dur*0.55)+1,1);o=round(l*0.4+k*0.35+h*0.25,1)
 return{x:max(1,min(10,v))for x,v in{'learning':l,'knowledge':k,'horizon':h,'overall':o}.items()}
def _bili_get(path,params=None):
 s=_get_session();r=s.get('https://api.bilibili.com'+path,params=params,timeout=15);r.raise_for_status()
 d=r.json()
 if d.get('code')!=0:raise Exception(f"B站API({d.get('code')}):{d.get('message','')}")
 return d
def summarize_video(vid):
 if not LLM_API_KEY:return{'topic':vid.get('title',''),'summary':'未配置AI Key','recommendation':'可选'}
 try:
  p="分析B站视频："+vid.get('title','')+" 简介："+((vid.get('description','')or vid.get('desc',''))[:200])+" 输出JSON主题、概括、分类、推荐度"
  r=requests.post(LLM_API_BASE+"/chat/completions",headers={"Authorization":"Bearer "+LLM_API_KEY},json={"model":LLM_MODEL,"messages":[{"role":"user","content":p}],"temperature":0.3,"max_tokens":200},timeout=20)
  d=r.json();t=d['choices'][0]['message']['content'].strip()
  if'```json'in t:t=t.split('```json')[1].split('```')[0]
  elif'```'in t:t=t.split('```')[1].split('```')[0]
  return json.loads(t)
 except Exception as e:return{'topic':vid.get('title',''),'summary':'AI失败','recommendation':'可选'}
def get_subtitle(bvid):
 try:
  info=_bili_get('/x/web-interface/view',{'bvid':bvid});cid=info['data']['cid']
  player=_bili_get('/x/player/v2',{'bvid':bvid,'cid':cid})
  subs=player.get('data',{}).get('subtitle',{}).get('subtitles',[])
  if not subs:return{'subtitles':[],'text':'该视频没有字幕'}
  sr=requests.get(_fix_url(subs[0]['subtitle_url']),timeout=15);sd=sr.json()
  body=sd.get('body',[]);text='\n'.join(str(i+1)+'. '+it['content']for i,it in enumerate(body[:5000]))
  if len(body)>5000:text+='\n...（共'+str(len(body))+'句）'
  return{'subtitles':[{'lan':subs[0].get('lan',''),'lan_doc':subs[0].get('lan_doc','')}],'text':text}
 except Exception as e:return{'subtitles':[],'text':'获取失败:'+str(e)}
def _get_bilibili_ai(bvid,cid,up_mid=0):
 try:
  params=_sign_params({'bvid':bvid,'cid':cid,'up_mid':up_mid});d=_bili_get('/x/web-interface/view/conclusion/get',params)
  dd=d.get('data',{})
  if dd.get('code')!=0:return None
  mr=dd.get('model_result',{});summary=mr.get('summary','');outline=mr.get('outline',[]);sl=mr.get('subtitle',[])
  st=''
  if sl and sl[0].get('part_subtitle'):
   ps=sl[0]['part_subtitle']
   st='\n'.join('['+str(int(p['start_timestamp'])//60).zfill(2)+':'+str(int(p['start_timestamp'])%60).zfill(2)+'] '+p['content']for p in ps[:300])
  return{'summary':summary,'outline':[{'title':o.get('title',''),'timestamp':o.get('timestamp',0),'points':[{'ts':p.get('timestamp',0),'text':p.get('content','')}for p in o.get('part_outline',[])]}for o in outline],'subtitle_text':st,'has_summary':bool(summary),'has_subtitle':bool(st)}
 except:return None
def handle_api(path,query):
 global _login_session,_login_info
 if path=='/api/login/generate':
  if not QR_AVAILABLE:return 500,{'error':'qrcode未安装'}
  s=_ensure_login();r=s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate',timeout=10);d=r.json()
  if d.get('code')!=0:return 500,{'error':'生成失败'}
  qr_url=d['data']['url'];qr_key=d['data']['qrcode_key']
  img=qrcode.make(qr_url);buf=io.BytesIO();img.save(buf,format='PNG');b64=base64.b64encode(buf.getvalue()).decode()
  return 200,{'qrcode_key':qr_key,'qr_image':'data:image/png;base64,'+b64}
 if path=='/api/login/poll':
  key=query.get('key',[''])[0]
  if not key:return 400,{'error':'缺少key'}
  s=_ensure_login();r=s.get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll',params={'qrcode_key':key},timeout=10);d=r.json()
  code=d.get('data',{}).get('code',-1)
  if code==0:
   try:
    nav=s.get('https://api.bilibili.com/x/web-interface/nav',timeout=10).json()
    if nav.get('data',{}).get('isLogin'):_login_info={'uid':nav['data']['mid'],'uname':nav['data']['uname'],'face':_fix_url(nav['data'].get('face',''))};_save_login_state()
   except:pass
  return 200,{'code':code,'message':d.get('data',{}).get('message',''),'user':_login_info}
 if path=='/api/login/info':return 200,{'logged_in':bool(_login_info),'user':_login_info}
 if path=='/api/login/logout':_login_session=None;_login_info=None;return 200,{'ok':True}
 if path=='/api/followings':
  if not _login_info:return 401,{'error':'请先登录'}
  page=int(query.get('page',['1'])[0])
  try:
   s=_login_session;r=s.get('https://api.bilibili.com/x/relation/followings',params={'vmid':_login_info['uid'],'pn':page,'ps':50,'order':'desc','order_type':'attention'},timeout=15);d=r.json()
   if d.get('code')!=0:return 500,{'error':d.get('message','')}
   users=[]
   for u in d.get('data',{}).get('list',[]):users.append({'mid':u['mid'],'uname':u['uname'],'sign':u.get('sign',''),'face':_fix_url(u.get('face',''))})
   return 200,{'users':users,'total':d.get('data',{}).get('total',0)}
  except Exception as e:return 500,{'error':str(e)}
 if path=='/api/search_up':
  name=query.get('name',[''])[0]
  if not name:return 400,{'error':'缺少name'}
  try:
   d=_bili_get('/x/web-interface/search/type',{'search_type':'bili_user','keyword':name})
   results=[]
   for u in(d.get('data',{}).get('result',[])or[]):results.append({'mid':u['mid'],'uname':u['uname'],'sign':u.get('usign',''),'fans':u.get('fans',0),'videos':u.get('videos',0),'face':_fix_url(u.get('upic',''))})
   return 200,{'results':results}
  except Exception as e:return 500,{'error':str(e)}
 if path=='/api/all_videos':
  mid=int(query.get('mid',['0'])[0]);page=int(query.get('page',['1'])[0])
  ps=min(max(int(query.get('ps',['30'])[0]),10),50);order=query.get('order',['pubdate'])[0]
  if not mid:return 400,{'error':'缺少mid'}
  try:
   params=_sign_params({'mid':mid,'ps':ps,'pn':page,'order':order});d=_bili_get('/x/space/wbi/arc/search',params)
   vlist=d['data']['list']['vlist'];count=d['data']['page']['count'];videos=[]
   for v in vlist:videos.append({'bvid':v['bvid'],'title':v['title'],'description':v.get('description',''),'length':v['length'],'created':v['created'],'play':v.get('play',0),'comment':v.get('comment',0),'video_review':v.get('video_review',0),'pic':_fix_url(v.get('pic','')),'tname':v.get('tname',''),'scores':compute_scores({'play':v.get('play',0),'length':v['length']})})
   return 200,{'videos':videos,'total':len(videos),'count':count,'page':page,'ps':ps,'has_more':page*ps<count}
  except Exception as e:return 500,{'error':str(e)}
 if path=='/api/summarize':
  bvid=query.get('bvid',[''])[0]
  if not bvid:return 400,{'error':'缺少bvid'}
  try:
   info=_bili_get('/x/web-interface/view',{'bvid':bvid});vid=info['data'];cid=vid['cid'];up_mid=vid.get('owner',{}).get('mid',0)
   bai=_get_bilibili_ai(bvid,cid,up_mid)
   if bai and(bai['has_summary']or bai['has_subtitle']):return 200,{'source':'bilibili_ai','summary':bai['summary']or vid.get('title',''),'outline':bai['outline'],'category':vid.get('tname','')}
   s=summarize_video({'title':vid['title'],'desc':vid.get('desc',''),'length':str(vid['duration'])});s['source']='llm';return 200,s
  except Exception as e:return 500,{'error':str(e)}
 if path=='/api/subtitle':
  bvid=query.get('bvid',[''])[0]
  if not bvid:return 400,{'error':'缺少bvid'}
  try:
   info=_bili_get('/x/web-interface/view',{'bvid':bvid});cid=info['data']['cid'];up_mid=info['data'].get('owner',{}).get('mid',0)
   bai=_get_bilibili_ai(bvid,cid,up_mid)
   if bai and bai['has_subtitle']:return 200,{'source':'bilibili_ai','text':bai['subtitle_text'],'insufficient':False,'subtitles':[{'lan':'zh','lan_doc':'AI字幕'}]}
   result=get_subtitle(bvid);return 200,result
  except Exception as e:return 200,{'text':'','insufficient':True,'subtitles':[],'error':str(e)}
 return 404,{'error':'未知API'}
import os as _os
_HTML_PATH=_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),'templates','index.html')
def _load_html():
 try:
  with open(_HTML_PATH,encoding='utf-8')as f:return f.read()
 except:return'<h1>Template not found</h1>'
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  parsed=urlparse(self.path);path=parsed.path;query=parse_qs(parsed.query)
  if path.startswith('/api/'):
   try:
    status,body=handle_api(path,query)
    self.send_response(status);self.send_header('Content-Type','application/json;charset=utf-8');self.send_header('Access-Control-Allow-Origin','*');self.end_headers()
    self.wfile.write(json.dumps(body,ensure_ascii=False).encode())
   except Exception as e:
    self.send_response(500);self.send_header('Content-Type','application/json');self.send_header('Access-Control-Allow-Origin','*');self.end_headers()
    self.wfile.write(json.dumps({'error':str(e)},ensure_ascii=False).encode())
   return
  self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers()
  self.wfile.write(_load_html().encode())
 def log_message(self,*a):pass
if __name__=='__main__':
 print('[INFO] 启动B站UP主视频速览 端口:'+str(PORT))
 print('[INFO] LLM:'+('已配置'if LLM_API_KEY else'未配置'))
 if _load_login_state():print('[INFO] 登录已恢复: '+_login_info['uname'])
 HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()