"""Second pass: fill gaps without replacing already collected records."""
import json, re, time, unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from ytmusicapi import YTMusic

ROOT=Path(__file__).resolve().parent.parent
HTML=(ROOT/"index.html").read_text(encoding="utf-8")
ARTISTS=json.loads(re.search(r"const artists=(\[[\s\S]*?\]);",HTML).group(1))
CURATED=json.loads(re.search(r"const discoveryData=(\{[^\n]*\});",HTML).group(1))
PATH=ROOT/"data/artist-discovery.json"
D=json.loads(PATH.read_text(encoding="utf-8"))
assert D["count"]==306 and set(D["artists"])=={a["name"] for a in ARTISTS}
UA="Hellfest27 personal lineup explorer (https://github.com/leonbkim0943/hellfest27)"
def norm(s):return "".join(c for c in unicodedata.normalize("NFKD",str(s)).casefold() if c.isalnum())
def request(url):
    with urlopen(Request(url,headers={"User-Agent":UA,"Accept":"application/json"}),timeout=15) as response:return json.load(response)
def video_title(name, url):
    if not re.fullmatch(r"https://www\.youtube\.com/watch\?v=[\w-]{11}",url or ""):return None
    try:
        info=request("https://www.youtube.com/oembed?"+urlencode({"url":url,"format":"json"}))
        title=info.get("title","")
        parts=re.split(r"\s+(?:-|–|—|:)\s+",title,maxsplit=1)
        if len(parts)!=2 or norm(parts[0])!=norm(name):return None
        song=re.sub(r"\s*[\[(](?:official(?:\s+(?:music|lyric|live))?\s+video|official audio|lyric video|music video|visualizer|lyrics|audio)[\])]\s*$","",parts[1],flags=re.I).strip(' "')
        if not song or len(song)>150 or re.search(r"\b(?:full album|interview|teaser|trailer|live at|live in|documentary)\b",song,re.I):return None
        return song
    except Exception:return None
def exact_artist(result,name):
    return any(norm(x.get("name",""))==norm(name) for x in result.get("artists",[]) if isinstance(x,dict))
def lookup_channel(y,name,title):
    if not title:return None
    try:
        results=y.search(name+" "+title,filter="songs",limit=12)
        ids=set()
        for r in results:
            if norm(r.get("title",""))!=norm(title) or not exact_artist(r,name):continue
            for a in r.get("artists",[]):
                if norm(a.get("name",""))==norm(name) and re.fullmatch(r"UC[\w-]{22}",a.get("id") or ""):ids.add(a["id"])
        if len(ids)==1:return ids.pop()
    except Exception:pass
    return None
def enrich_music(name,r,c):
    y=YTMusic()
    title=video_title(name,r.get("officialVideo"))
    # A festival-selected video, by exact artist and title, anchors a new channel.
    channel=lookup_channel(y,name,title)
    if not channel:return
    try:
        artist=y.get_artist(channel)
        if norm(artist.get("name",""))!=norm(name):return
        songs=[]
        for t in (artist.get("songs") or {}).get("results",[]):
            if not exact_artist(t,name) or not t.get("title") or not re.fullmatch(r"[\w-]{11}",t.get("videoId") or ""):continue
            if t["title"] not in [x["title"] for x in songs]:songs.append({"title":t["title"],"note":"YouTube Music 아티스트 추천곡 목록","yt":"https://music.youtube.com/watch?v="+t["videoId"]})
            if len(songs)==3:break
        if not r.get("tracks") and not c.get("tracks") and songs:r["tracks"]=songs
        # Channel release list is evidence of a release, not representative status.
        if not r.get("albums") and not c.get("albums"):
            albums=[]
            for t in (artist.get("albums") or {}).get("results",[]):
                if not t.get("title") or not t.get("browseId"):continue
                try:
                    album=y.get_album(t["browseId"])
                    if not exact_artist(album,name) or album.get("type")!="Album":continue
                    item={"title":album["title"],"note":"대표성 미확인"}
                    if re.fullmatch(r"\d{4}",str(album.get("year",""))):item["year"]=int(album["year"])
                    if item["title"] not in [x["title"] for x in albums]:albums.append(item)
                except Exception:continue
                if len(albums)==2:break
            if albums:r["albums"]=albums
        if songs or r.get("albums"):r["musicSource"]="https://music.youtube.com/channel/"+channel
    except Exception:pass
def mb_enrich(name,r,c):
    url=r.get("musicbrainzUrl","")
    if not re.fullmatch(r"https://musicbrainz\.org/artist/[0-9a-f-]{36}",url):return
    mid=url.rsplit("/",1)[-1]
    try:
        time.sleep(1.1)
        data=request("https://musicbrainz.org/ws/2/artist/"+mid+"?fmt=json")
        if norm(data.get("name",""))!=norm(name):return
        begin=(data.get("life-span") or {}).get("begin") or ""
        if data.get("type")=="Group" and not c.get("year") and re.match(r"^\d{4}",begin):r["formationYear"]=int(begin[:4])
        if not r.get("albums") and not c.get("albums"):
            time.sleep(1.1)
            albums=request("https://musicbrainz.org/ws/2/release-group?"+urlencode({"artist":mid,"type":"album","limit":100,"fmt":"json"}))
            items=[]
            for a in albums.get("release-groups",[]):
                if a.get("primary-type")!="Album" or a.get("secondary-types") or not a.get("title"):continue
                item={"title":a["title"],"note":"대표성 미확인"}
                date=a.get("first-release-date") or ""
                if re.match(r"^\d{4}",date):item["year"]=int(date[:4])
                if item["title"] not in [x["title"] for x in items]:items.append(item)
                if len(items)==2:break
            if items:r["albums"]=items
    except Exception:pass
def counts():
    return {k:sum(bool(r.get(k) or CURATED.get(n,{}).get(k)) for n,r in D["artists"].items()) for k in ("tracks","albums")}
print("Before",counts(),flush=True)
for i,a in enumerate(ARTISTS):
    n=a["name"];r=D["artists"][n];c=CURATED.get(n,{})
    if n!="Insidias":
        if not (r.get("tracks") or c.get("tracks")) or not (r.get("albums") or c.get("albums")):enrich_music(n,r,c)
        if not c.get("year") or not (r.get("albums") or c.get("albums")):mb_enrich(n,r,c)
    if i%20==0:print("Progress",i+1,"/306",counts(),flush=True)
assert set(D["artists"])=={a["name"] for a in ARTISTS}
PATH.write_text(json.dumps(D,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("After",counts(),"formation years",sum(bool(r.get("formationYear")) for r in D["artists"].values()),flush=True)
