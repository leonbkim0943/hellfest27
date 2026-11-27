"""Bounded gap-filling pipeline. Preserves existing metadata and writes a review queue.
No credentials, personal data, or browser storage are used."""
import json,re,time,unicodedata,concurrent.futures as cf
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from bs4 import BeautifulSoup
from ytmusicapi import YTMusic
ROOT=Path(__file__).resolve().parent.parent
html=(ROOT/'index.html').read_text(encoding='utf-8')
artists=json.loads(re.search(r'const artists=(\[[\s\S]*?\]);',html).group(1))
curated=json.loads(re.search(r'const discoveryData=(\{[^\n]*\});',html).group(1))
countries=json.loads(re.search(r'const countryMap=(\{[^\n]*\});',html).group(1))
path=ROOT/'data/artist-discovery.json'
doc=json.loads(path.read_text(encoding='utf-8'))
records=doc['artists']
assert len(artists)==len(records)==306 and set(records)=={a['name'] for a in artists}
UA='Hellfest27 lineup explorer (https://github.com/leonbkim0943/hellfest27)'
def norm(s):return ''.join(x for x in unicodedata.normalize('NFKD',str(s)).casefold() if x.isalnum())
aliases={'Sinister 90':['Sinister'],'Big Ass Truck I.E.':['Big Ass Truck'],'Jack and the Bearded Fishermen':['Jack & the Bearded Fishermen'],'Me and That Man':['Me & That Man']}
def names(n):return {norm(n),*(norm(x) for x in aliases.get(n,[]))}
def has(n,k):return bool(curated.get(n,{}).get(k) or records[n].get(k))
def request(url,json_mode=True):
    with urlopen(Request(url,headers={'User-Agent':UA,'Accept':'application/json' if json_mode else 'text/html'}),timeout=12) as r:
        return json.load(r) if json_mode else r.read()
def exact(n,item):return any(norm(x.get('name','')) in names(n) for x in item.get('artists',[]) if isinstance(x,dict))
def unique(xs,key='title'):
    out=[];seen=set()
    for x in xs:
        k=norm(x.get(key,''))
        if k and k not in seen:out.append(x);seen.add(k)
    return out
def anchors(n,r):
    titles={norm(x['title']) for x in (r.get('tracks',[])+r.get('albums',[])+curated.get(n,{}).get('tracks',[])+curated.get(n,{}).get('albums',[])) if x.get('title')}
    video=r.get('officialVideo')
    if re.fullmatch(r'https://www\.youtube\.com/watch\?v=[\w-]{11}',video or ''):
        try:
            t=request('https://www.youtube.com/oembed?'+urlencode({'url':video,'format':'json'})).get('title','')
            for delimiter in [' - ',' – ',' — ',': ',' | ']:
                p=t.split(delimiter,1)
                if len(p)==2 and norm(p[0]) in names(n):
                    title=re.sub(r'\s*[\[(](?:official[^)\]]*|lyric video|music video|visualizer|audio)[\])]\s*$','',p[1],flags=re.I).strip()
                    if title and len(title)<150 and not re.search(r'\b(full album|interview|teaser|trailer|documentary|live at|live in)\b',title,re.I):
                        titles.add(norm(title));r.setdefault('festivalTrack',{'title':title,'url':video})
                    break
        except Exception:pass
    return titles
def channel_candidates(y,n,r,a,known):
    urls=[r.get('musicSource'),a.get('yt')]
    ids=[]
    for url in urls:
        if re.fullmatch(r'https://music\.youtube\.com/channel/UC[\w-]{22}',url or ''):ids.append((url.rsplit('/',1)[-1],True))
    if known:
        for query in [n]+aliases.get(n,[]):
            try:
                for x in y.search(query,filter='artists',limit=6):
                    if norm(x.get('artist','')) in names(n) and re.fullmatch(r'UC[\w-]{22}',x.get('browseId') or ''):ids.append((x['browseId'],False))
            except Exception:pass
    return list(dict.fromkeys(ids))
def collect(n,a,r):
    if curated.get(n,{}).get('unreleased'):return r
    need_t=not has(n,'tracks');need_a=not has(n,'albums')
    if not (need_t or need_a):return r
    known=anchors(n,r)
    try:
        y=YTMusic();matched=[]
        for cid,trusted in channel_candidates(y,n,r,a,known):
            try:
                x=y.get_artist(cid)
                if norm(x.get('name','')) not in names(n):continue
                songs=(x.get('songs') or {}).get('results',[])
                albums=(x.get('albums') or {}).get('results',[])
                evidence={norm(t.get('title','')) for t in songs+albums if isinstance(t,dict)}
                if trusted or (known & evidence):matched.append((cid,x,trusted))
            except Exception:continue
        trusted=[v for v in matched if v[2]]
        if len({v[0] for v in trusted or matched})==1:
            cid,x,_=(trusted or matched)[0]
            if need_t:
                songs=[]
                for t in (x.get('songs') or {}).get('results',[]):
                    if exact(n,t) and t.get('title') and re.fullmatch(r'[\w-]{11}',t.get('videoId') or ''):
                        songs.append({'title':t['title'],'yt':'https://music.youtube.com/watch?v='+t['videoId'],'note':'YouTube Music 아티스트 추천곡 목록'})
                if songs:r['tracks']=unique(songs)[:3]
            if need_a:
                albums=[]
                for t in (x.get('albums') or {}).get('results',[])[:8]:
                    if not t.get('browseId'):continue
                    try:
                        z=y.get_album(t['browseId'])
                        if not exact(n,z) or z.get('type')!='Album' or not z.get('title'):continue
                        item={'title':z['title'],'note':'대표성 미확인'}
                        if re.fullmatch(r'\d{4}',str(z.get('year',''))):item['year']=int(z['year'])
                        albums.append(item)
                    except Exception:continue
                    if len(albums)==2:break
                if albums:r['albums']=unique(albums)
            if r.get('tracks') or r.get('albums'):r['musicSource']='https://music.youtube.com/channel/'+cid
    except Exception:pass
    # iTunes identity: exact artist AND an independently sourced title.
    # Reject ambiguous artist IDs rather than guess.
    if (not has(n,'tracks') or not has(n,'albums')) and known:
        try:
            q=request('https://itunes.apple.com/search?'+urlencode({'term':n,'media':'music','entity':'song','limit':100,'country':'US'}))
            rows=[x for x in q.get('results',[]) if norm(x.get('artistName','')) in names(n) and x.get('artistId')]
            ids={x['artistId'] for x in rows if norm(x.get('trackName','')) in known or norm(x.get('collectionName','')) in known}
            if len(ids)==1:
                aid=ids.pop();rows=[x for x in rows if x['artistId']==aid]
                if not has(n,'tracks'):
                    songs=unique([{'title':x['trackName'],'note':'음원 목록 확인 · 탐색용'} for x in rows if x.get('trackName')])[:3]
                    if songs:r['tracks']=songs
                if not has(n,'albums'):
                    z=request('https://itunes.apple.com/lookup?'+urlencode({'id':aid,'entity':'album','limit':100,'country':'US'}))
                    albums=[]
                    for x in z.get('results',[]):
                        if x.get('wrapperType')!='collection' or x.get('artistId')!=aid or x.get('collectionType')!='Album' or x.get('trackCount',0)<5:continue
                        t=x.get('collectionName','')
                        if not t or re.search(r'\b(single|ep|deluxe|live|greatest hits|compilation)\b',t,re.I):continue
                        item={'title':t,'note':'대표성 미확인'}
                        if re.match(r'\d{4}',x.get('releaseDate','')):item['year']=int(x['releaseDate'][:4])
                        albums.append(item)
                    if albums:r['albums']=unique(albums)[:2]
                r['appleSource']='https://music.apple.com/us/artist/'+str(aid)
        except Exception:pass
    # A festival-selected music video with exact artist and title is a valid
    # entry recommendation even if a streaming artist profile cannot be resolved.
    if not has(n,'tracks') and r.get('festivalTrack'):
        r['tracks']=[{'title':r['festivalTrack']['title'],'note':'Hellfest 공식 선정 영상'}]
    return r
def year_from_official(n,r):
    if curated.get(n,{}).get('year') or r.get('formationYear'):return
    u=r.get('officialUrl')
    if n=='Insidias':u='https://hellfest.fr/artiste/insidias'
    if not u or urlparse(u).hostname!='hellfest.fr':return
    try:
        page=BeautifulSoup(request(u,False),'html.parser')
        h=next((x for x in page.find_all('h1') if norm(x.get_text(' ',strip=True)) in names(n)),None)
        if not h:return
        # Restrict to artist introduction before other bands on the same stage.
        parts=[]
        for t in h.next_elements:
            if not isinstance(t,str) or t.parent.name in ('script','style'):continue
            q=' '.join(t.split())
            if norm(q) in ('surlamemescene','onthesamestage'):break
            if q:parts.append(q)
            if len(parts)>45:break
        text=' '.join(parts)
        # Explicit formation statements only; avoid album-release and solo birth dates.
        if not curated.get(n,{}).get('unreleased'):
            m=re.search(r'\b(?:form[ée]s?|fond[ée]s?|cr[ée][ée]s?|n[ée]s?)\s+(?:à [^,.]{1,35}\s+)?en\s+((?:19|20)\d{2})\b',text,re.I)
            if m and 1960<=int(m[1])<=2027:r['formationYear']=int(m[1])
    except Exception:pass
def counts():
    return {k:sum(has(a['name'],k) for a in artists) for k in ['tracks','albums','formationYear']}
print('Before',counts(),flush=True)
for i,a in enumerate(artists):
    n=a['name']
    records[n]=collect(n,a,records[n])
    if i%20==0:print('Music',i+1,counts(),flush=True)
    time.sleep(.15)
with cf.ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(lambda a:year_from_official(a['name'],records[a['name']]),artists))
assert set(records)=={a['name'] for a in artists}
path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
queue=[]
for a in artists:
    n=a['name'];r=records[n];c=curated.get(n,{})
    missing=[]
    if not (r.get('countries') or countries.get(n)):missing.append('country')
    if not c.get('unreleased'):
        if not has(n,'tracks'):missing.append('tracks')
        if not has(n,'albums'):missing.append('albums')
    if not (r.get('formationYear') or c.get('year')):missing.append('formationYear')
    if not c.get('description'):missing.append('original Korean biography')
    if missing:queue.append({'name':n,'missing':missing,'officialUrl':r.get('officialUrl'),'officialVideo':r.get('officialVideo'),'musicbrainzUrl':r.get('musicbrainzUrl')})
(ROOT/'data/artist-review-queue.json').write_text(json.dumps({'count':len(queue),'artists':queue},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('After',counts(),'Review queue',len(queue),flush=True)
