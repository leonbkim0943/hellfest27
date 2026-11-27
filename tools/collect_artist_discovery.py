"""Collect publicly available artist discovery metadata; never read private plans."""
import concurrent.futures as cf
import json, re, time, unicodedata, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
import pycountry
from ytmusicapi import YTMusic

ROOT=Path(__file__).resolve().parent.parent
HTML=(ROOT/"index.html").read_text(encoding="utf-8")
ARTISTS=json.loads(re.search(r"const artists=(\[[\s\S]*?\]);",HTML).group(1))
SCHEDULE=json.loads(re.search(r"const schedule=(\{[^\n]*?\}), stageNames=",HTML).group(1))
assert len(ARTISTS)==len(SCHEDULE)==306
AUDIT=json.loads((ROOT/"audit-input/link-audit.json").read_text(encoding="utf-8"))
AUDIT={x["name"]:x for x in AUDIT["rows"]}
BASE="https://hellfest.fr"
UA="Hellfest27 personal lineup explorer (https://github.com/leonbkim0943/hellfest27)"
def norm(x):
    return "".join(c for c in unicodedata.normalize("NFKD",str(x)).casefold() if c.isalnum())
def slug(x):
    return re.sub(r"[^a-z0-9]+","-",unicodedata.normalize("NFKD",x).encode("ascii","ignore").decode().lower()).strip("-")
def get(url):
    for i in range(2):
        try:
            with urlopen(Request(url,headers={"User-Agent":UA}),timeout=15) as r:
                return r.read()
        except Exception:
            if i: raise
            time.sleep(1)
def soup(url): return BeautifulSoup(get(url),"html.parser")
COUNTRIES={}
for cc,labels in {
"GB":"Royaume-Uni|Angleterre|Ecosse|Pays de Galles|United Kingdom|UK|Grande Bretagne",
"US":"Etats-Unis|USA|United States|Etats Unis|US","FR":"France","DE":"Allemagne|Germany","SE":"Suede|Sweden","NO":"Norvege|Norway","FI":"Finlande|Finland","CH":"Suisse|Switzerland","AT":"Autriche|Austria","BE":"Belgique|Belgium","NL":"Pays-Bas|Hollande|Netherlands","IT":"Italie|Italy","IE":"Irlande|Ireland","CA":"Canada","AU":"Australie|Australia","NZ":"Nouvelle-Zelande|New Zealand","JP":"Japon|Japan","PL":"Pologne|Poland","CZ":"Republique Tcheque|Tchequie|Czech Republic|Czechia","PT":"Portugal","ES":"Espagne|Spain","GR":"Grece|Greece","BR":"Bresil|Brazil","AR":"Argentine|Argentina","CL":"Chili|Chile","BY":"Bielorussie|Belarus","IS":"Islande|Iceland","DK":"Danemark|Denmark","IL":"Israel","IR":"Iran","MX":"Mexique|Mexico","ZA":"Afrique du Sud|South Africa","LU":"Luxembourg","RO":"Roumanie|Romania","HU":"Hongrie|Hungary","SK":"Slovaquie|Slovakia","UA":"Ukraine","RU":"Russie|Russia","CO":"Colombie|Colombia","RS":"Serbie|Serbia","XX":"International|Multinational|Europe|Various|Monde"
}.items():
    for label in labels.split("|"): COUNTRIES[norm(label)]=cc
def country(x):
    if norm(x) in COUNTRIES:return [COUNTRIES[norm(x)]]
    bits=re.split(r"\s*(?:/|,| & | et | and )\s*",x)
    if len(bits)>1 and all(norm(y) in COUNTRIES for y in bits):return list(dict.fromkeys(COUNTRIES[norm(y)] for y in bits))
    return []
def variants(name):
    v={norm(name)}
    aliases={"Slash":["Slash feat. Myles Kennedy & The Conspirators"],"Body Count":["Body Count feat Ice-T"],"Sinister 90":["Sinister"],"Therion":["Therion 40 years"],"Ensiferum":["Ensiferum feat Jari Mäenpää"],"Big Ass Truck I.E.":["Big Ass Truck"],"Jack and the Bearded Fishermen":["Jack & the Bearded Fishermen"],"Me and That Man":["Me & That Man"]}
    v.update(norm(x) for x in aliases.get(name,[]))
    return v
def discover_links():
    urls=set()
    for path in ["/lineup","/artiste/europe","/artiste/ensiferum"]:
        try:
            page=soup(BASE+path)
            for a in page.select("a[href]"):
                u=urljoin(BASE,a["href"])
                if urlparse(u).netloc in {"hellfest.fr","www.hellfest.fr"} and "/artiste/" in urlparse(u).path: urls.add(u.split("?")[0])
        except Exception as e: print("seed",path,str(e)[:100],flush=True)
    return urls
def parse_official(url,artist):
    page=soup(url)
    h=next((x for x in page.find_all("h1") if norm(x.get_text(" ",strip=True)) in variants(artist["name"])),None)
    if not h:return None
    parts=[]
    for item in h.next_elements:
        if not isinstance(item,str):continue
        if item.parent and item.parent.name in {"script","style"}:continue
        t=" ".join(item.split())
        if t:parts.append(t)
        if len(parts)>=30:break
    day,stage,_=SCHEDULE[artist["name"]]
    d={"17":"jeudi","18":"vendredi","19":"samedi","20":"dimanche"}[day]
    if not any(norm(d+day+"juin") in norm(x) for x in parts[:16]):return None
    if not any(norm(stage)==norm(x) for x in parts[:20]):return None
    # Current artist page has genre then country then date; do not parse footer.
    loc=[]
    for t in parts[1:8]:
        if norm(d+day+"juin") in norm(t):break
        c=country(t)
        if c:loc=c;break
    if not loc:return None
    video=None
    for frame in page.find_all("iframe"):
        src=frame.get("src") or frame.get("data-src") or ""
        m=re.search(r"(?:youtube(?:-nocookie)?\.com/embed/)([A-Za-z0-9_-]{11})",src)
        if m:video="https://www.youtube.com/watch?v="+m[1];break
    return {"countries":loc,"officialUrl":url,"officialVideo":video,"countrySource":"Hellfest 2027 official artist page"}
def official_for(a,links):
    name=a["name"]
    target=variants(name)
    urls=[x for x in links if norm(urlparse(x).path.split("/")[-2] if x.endswith("/") else urlparse(x).path.split("/")[-1]) in target]
    urls+= [BASE+"/artiste/"+slug(name),BASE+"/artiste/"+slug(name).replace("-","")]
    for u in dict.fromkeys(urls):
        try:
            x=parse_official(u,a)
            if x:return x
        except Exception:pass
    return {}
def ytm_for(a):
    r=AUDIT.get(a["name"],{})
    # Only use channels with album or MusicBrainz-channel corroboration.
    matches=[x for x in r.get("ytmusic_candidates",[]) if x.get("corroborated")]
    if len(matches)!=1:return {}
    c=matches[0];cid=c["url"].rsplit("/",1)[-1]
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}",cid):return {}
    try:
        y=YTMusic().get_artist(cid)
        if norm(y.get("name","")) not in variants(a["name"]):return {}
        tracks=[]
        for t in (y.get("songs") or {}).get("results",[]):
            if not isinstance(t,dict) or not t.get("title") or not t.get("videoId"):continue
            names=[norm(x.get("name","")) for x in t.get("artists",[]) if isinstance(x,dict)]
            if names and not set(names)&variants(a["name"]):continue
            title=t["title"]
            if title not in [x["title"] for x in tracks]:tracks.append({"title":title,"note":"YouTube Music 아티스트 추천곡 목록","yt":"https://music.youtube.com/watch?v="+t["videoId"]})
            if len(tracks)==3:break
        albums=[]
        known={norm(x) for x in r.get("album_titles",[]) if isinstance(x,str)}
        for t in (y.get("albums") or {}).get("results",[]):
            if isinstance(t,dict) and norm(t.get("title","")) in known:
                item={"title":t["title"],"note":"MusicBrainz와 YouTube Music에서 일치한 앨범"}
                if re.fullmatch(r"\d{4}",str(t.get("year",""))):item["year"]=int(t["year"])
                if item["title"] not in [x["title"] for x in albums]:albums.append(item)
            if len(albums)==2:break
        return {"tracks":tracks,"albums":albums,"musicSource":c["url"]}
    except Exception:return {}
def main():
    links=discover_links()
    print("Official artist links discovered",len(links),flush=True)
    # Capture exact linked slugs from each verified page too, to cover alternative slugs.
    results={}
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(official_for,a,links):a for a in ARTISTS}
        for f in cf.as_completed(futures):
            a=futures[f];results[a["name"]]=f.result()
            if len(results)%25==0:print("Official",len(results),"/306",flush=True)
    for i,a in enumerate(ARTISTS):
        name=a["name"];r=results[name];audit=AUDIT.get(name,{})
        mbid=audit.get("musicbrainz_id")
        if mbid:
            r["musicbrainzUrl"]="https://musicbrainz.org/artist/"+mbid
        r.update(ytm_for(a))
        if not r.get("albums") and mbid:
            albums=[x for x in audit.get("album_titles",[]) if isinstance(x,str) and x.strip()]
            if albums:r["albums"]=[{"title":x,"note":"MusicBrainz 등록 앨범 (대표성 미검증)"} for x in dict.fromkeys(albums[:2])]
        if i%20==0:print("Music",i+1,"/306",flush=True)
    output={"schema":1,"count":306,"artists":results}
    assert set(results)=={a["name"] for a in ARTISTS}
    assert all(all(re.fullmatch(r"[A-Z]{2}",cc) for cc in r.get("countries",[])) for r in results.values())
    p=ROOT/"data/artist-discovery.json";p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Summary",json.dumps({"official":sum(bool(r.get("officialUrl")) for r in results.values()),"country":sum(bool(r.get("countries")) for r in results.values()),"tracks":sum(bool(r.get("tracks")) for r in results.values()),"albums":sum(bool(r.get("albums")) for r in results.values())}),flush=True)
if __name__=="__main__":main()
