import json, pathlib, threading, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
root=pathlib.Path(__file__).resolve().parents[1]
out=root/'ux-audit-output';out.mkdir(exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/index.html'
report=[]
with sync_playwright() as p:
    for engine, size in [('chromium',(1440,900)),('chromium',(390,844)),('chromium',(360,800)),('chromium',(820,1180)),('webkit',(390,844))]:
        label=f'{engine}-{size[0]}'
        browser=getattr(p,engine).launch(headless=True)
        context=browser.new_context(viewport={'width':size[0],'height':size[1]},is_mobile=(engine=='webkit'),has_touch=size[0]<820)
        context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(url.rsplit('/',1)[0]) else route.abort())
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        result={'viewport':label,'errors':errors}
        try:
            page.goto(url);page.locator('body.js-ready').wait_for()
            page.screenshot(path=str(out/(label+'-initial.png')))
            result['initial']=page.evaluate("""() => {let measure=s=>{let e=document.querySelector(s),r=e.getBoundingClientRect();return {top:Math.round(r.top+scrollY),height:Math.round(r.height),width:Math.round(r.width)}};return {header:measure('header'),planner:measure('#planner'),search:measure('#query'),firstGroup:measure('.fold-section'),overflow:document.documentElement.scrollWidth-innerWidth,controls:[...document.querySelectorAll('.controls input,.controls select,.controls button')].length}}""")
            search=page.locator('#query');search.fill('Judas Priest')
            row=page.locator('.artist').filter(has=page.get_by_role('button',name='Judas Priest 상세 정보',exact=True))
            row.wait_for()
            result['artist']=row.evaluate("""e=>({height:Math.round(e.getBoundingClientRect().height),overflow:document.documentElement.scrollWidth-innerWidth,targets:[...e.querySelectorAll('button,select,a')].filter(x=>x.getBoundingClientRect().width&&x.getBoundingClientRect().height).map(x=>({label:x.getAttribute('aria-label')||x.innerText,width:Math.round(x.getBoundingClientRect().width),height:Math.round(x.getBoundingClientRect().height)}))})""")
            result['spotifyHref']=row.locator('a.spotify').get_attribute('href')
            row.locator('.listen').click()
            assert row.locator('.listen').get_attribute('aria-pressed')=='true'
            row.locator('.fav').click()
            row.locator('.priority').select_option('must')
            assert row.locator('.priority').input_value()=='must'
            result['focusAfterPriority']=page.evaluate("document.activeElement.tagName")
            row.locator('.name-toggle').click()
            page.screenshot(path=str(out/(label+'-detail.png')))
            page.locator('[data-profile="brother"]').click()
            row.locator('.priority').select_option('must')
            page.locator('[data-profile="both"]').click()
            page.locator('.joint-stat').filter(has_text='공통 필관람').click()
            assert page.locator('#count').inner_text().startswith('1 /')
            result['joint']=page.evaluate("""()=>({panelTop:Math.round(document.querySelector('#jointPanel').getBoundingClientRect().top+scrollY),panelHeight:Math.round(document.querySelector('#jointPanel').getBoundingClientRect().height),resultTop:Math.round(document.querySelector('#count').getBoundingClientRect().top+scrollY),scrollY:Math.round(scrollY),overflow:document.documentElement.scrollWidth-innerWidth})""")
            page.screenshot(path=str(out/(label+'-joint.png')))
            result['flows']='pass'
            try:
                axe=root/'node_modules/axe-core/axe.min.js'
                if axe.exists():
                    page.add_script_tag(path=str(axe))
                    result['axe']=page.evaluate("""async()=>{let r=await axe.run({runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return r.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,nodes:v.nodes.length,targets:v.nodes.slice(0,5).map(n=>n.target)}))}""")
            except Exception as e:result['axeError']=str(e)
        except Exception as e:result['flowError']=str(e);page.screenshot(path=str(out/(label+'-error.png')))
        finally:
            report.append(result);browser.close()
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
server.shutdown()
