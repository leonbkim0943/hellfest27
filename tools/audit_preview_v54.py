import json,pathlib,threading,functools
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
root=pathlib.Path(__file__).resolve().parents[1]
out=root/'ux-audit-output';out.mkdir(exist_ok=True)
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}'
report=[]
with sync_playwright() as p:
 for engine,width,height in [('chromium',1440,900),('chromium',390,844),('chromium',360,800),('webkit',390,844)]:
    browser=getattr(p,engine).launch()
    context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<760)
    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else r.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    label=f'{engine}-{width}';result={'viewport':label,'errors':errors}
    try:
      page.goto(base+'/preview/v54.html');page.locator('body.preview-v54').wait_for()
      page.locator('.artist').first.wait_for()
      result['initial']=page.evaluate("""()=>({firstGroup:Math.round(document.querySelector('.fold-section').getBoundingClientRect().top+scrollY),firstArtist:Math.round(document.querySelector('.artist').getBoundingClientRect().top+scrollY),overflow:document.documentElement.scrollWidth-innerWidth})""")
      page.screenshot(path=str(out/(label+'-initial.png')))
      page.locator('#query').fill('Judas Priest')
      row=page.locator('.artist').filter(has=page.get_by_role('button',name='Judas Priest 상세 정보',exact=True))
      row.wait_for()
      assert row.locator(':scope > a.spotify').get_attribute('href').startswith('https://open.spotify.com/')
      row.locator('.name-toggle').click();assert row.locator('.artist-detail').is_visible()
      page.screenshot(path=str(out/(label+'-detail.png')))
      before=row.locator('.listen').get_attribute('aria-pressed');row.locator('.listen').click()
      assert row.locator('.listen').get_attribute('aria-pressed')!=before
      row.locator('.priority').select_option('must')
      page.locator('[data-page-nav=joint]').click()
      page.locator('.joint-stat').filter(has_text='공통 필관람').click()
      assert 'Judas Priest' in page.locator('#content').inner_text()
      page.screenshot(path=str(out/(label+'-joint.png')))
      page.locator('[data-page-nav=plan]').click()
      assert page.locator('#summaryDock').is_visible()
      page.locator('[data-layout-choice=B]').click()
      page.locator('[data-page-nav=explore]').click()
      assert page.locator('#summaryDock').is_visible()
      page.screenshot(path=str(out/(label+'-B.png')))
      page.locator('#filterToggle').click();assert page.locator('#filterDock').is_visible()
      page.locator('.gear').click();assert page.locator('#settingsDialog').is_visible()
      assert page.locator('#connectSync').is_disabled()
      page.locator('#settingsClose').click()
      assert not errors,errors
      result['flows']='pass'
      result['overflow']=page.evaluate('document.documentElement.scrollWidth-innerWidth')
    except Exception as e:
      result['flowError']=str(e);page.screenshot(path=str(out/(label+'-error.png')))
    finally:
      report.append(result);browser.close()
(out/'preview-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
server.shutdown()
if any(x.get('flowError') or x.get('errors') for x in report):raise SystemExit(1)
