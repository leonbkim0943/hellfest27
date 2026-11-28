import json,pathlib,threading,functools
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
root=pathlib.Path(__file__).resolve().parents[1];out=root/'ux-audit-output';out.mkdir(exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(root)));threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}'
report=[]
with sync_playwright() as p:
 for engine,width,height in [('chromium',1440,900),('chromium',390,844),('chromium',360,800),('webkit',390,844)]:
  browser=getattr(p,engine).launch();ctx=browser.new_context(viewport={'width':width,'height':height},has_touch=width<760)
  initial={'fav':True,'listened':True,'priority':'must','memo':'original memo'}
  remote={('me','Judas Priest'):{'version':3,'data':initial.copy()},('brother','Gojira'):{'version':2,'data':{'fav':True,'listened':False,'priority':'want','memo':'brother memo'}}}
  calls=[];errors=[]
  def route(r):
   if r.request.url.startswith(base):return r.continue_()
   if 'script.google.com/macros/' in r.request.url:
    req=json.loads(r.request.post_data);calls.append(req['action'])
    if req['action']=='read':data={'ok':True,'records':[{'user':u,'artist':a,**v} for (u,a),v in remote.items()]}
    else:
     k=(req['user'],req['artist']);v=remote.get(k,{'version':0,'data':{'fav':False,'listened':False,'priority':'none','memo':''}})
     assert req['version']==v['version']
     v={'version':v['version']+1,'data':{**v['data'],**req['patch']}};remote[k]=v;data={'ok':True,**v}
    return r.fulfill(status=200,content_type='application/json',body=json.dumps(data),headers={'Access-Control-Allow-Origin':'*'})
   return r.abort()
  ctx.route('**/*',route)
  snapshot={'me':{'Judas Priest':initial},'brother':{'Gojira':remote[('brother','Gojira')]['data']},'legacyMigrated':True}
  seed={'initialized':True,'base':{json.dumps([u,a],separators=(',',':')):v for (u,a),v in remote.items()},'pending':[],'snapshot':snapshot}
  ctx.add_init_script(f"""if(!sessionStorage.getItem('seed')){{localStorage.setItem('hellfest2027-plan-v4',{json.dumps(json.dumps(snapshot))});localStorage.setItem('hellfest2027-sync-v5',{json.dumps(json.dumps(seed))});localStorage.setItem('hellfest2027-access-v5','0000');sessionStorage.setItem('seed','1')}}""")
  page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(8000)
  label=f'{engine}-{width}';res={'viewport':label}
  try:
   page.goto(base+'/index.html');page.locator('#syncIndicator').get_by_text('동기화 완료').wait_for() if False else page.wait_for_function("document.getElementById('syncIndicator').textContent==='동기화 완료'")
   page.locator('#query').fill('Judas Priest');row=page.locator('.artist[data-artist="Judas Priest"]')
   assert row.locator('.fav').get_attribute('aria-pressed')=='true'
   assert row.locator('.actions select').input_value()=='must'
   assert row.locator('.date-chip').inner_text()=='6/19 토'
   res['rowHeight']=row.evaluate('(e)=>Math.round(e.getBoundingClientRect().height)')
   res['sameLine']=row.evaluate("""e=>Math.abs(e.querySelector('.music').getBoundingClientRect().top-e.querySelector('.actions').getBoundingClientRect().top)<8""")
   assert res['sameLine']
   assert page.evaluate('document.documentElement.scrollWidth-innerWidth')==0
   row.locator('.namebtn').click()
   detail=page.locator('#detailContent') if width>760 else row.locator('.inline-detail')
   assert detail.is_visible()
   assert detail.locator('textarea').input_value()=='original memo'
   page.screenshot(path=str(out/(label+'-detail.png')))
   row.locator('.listen').click()
   page.wait_for_function("document.getElementById('syncIndicator').textContent==='동기화 완료' && JSON.parse(localStorage.getItem('hellfest2027-sync-v5')).pending.length===0")
   assert remote[('me','Judas Priest')]['data']=={**initial,'listened':False}
   assert remote[('brother','Gojira')]['data']['memo']=='brother memo'
   page.reload();page.wait_for_function("document.getElementById('syncIndicator').textContent==='동기화 완료'")
   page.locator('#query').fill('Judas Priest');assert row.locator('.listen').get_attribute('aria-pressed')=='false'
   page.locator('.navtabs [data-page=joint]').click();page.locator('.navtabs [data-page=plan]').click();assert page.locator('#summary').is_visible()
   page.locator('#syncIndicator').click();assert page.locator('#runSync').is_visible();page.locator('#closeSettings').click()
   page.locator('.navtabs [data-page=explore]').click();page.locator('#view').select_option('day');page.locator('#expand').click()
   assert page.locator('.group[data-day="17"]').count()==1 and page.locator('.group[data-day="20"]').count()==1
   assert page.evaluate('document.documentElement.scrollWidth-innerWidth')==0
   assert not errors,errors
   res['status']='pass';res['calls']=calls
  except Exception as e:res['error']=str(e);res['pageErrors']=errors;page.screenshot(path=str(out/(label+'-error.png')))
  finally:report.append(res);browser.close()
print(json.dumps(report,ensure_ascii=False,indent=2));(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
server.shutdown()
if any(r.get('status')!='pass' for r in report):raise SystemExit(1)
