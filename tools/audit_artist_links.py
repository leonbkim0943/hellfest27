"""Audit all festival artists. Public music metadata only; no credentials.
Produces link-audit.json. Does not edit index.html. Run from repository root.
MusicBrainz requests are paced at <= 1/s. YouTube Music is optional.
"""
import json, re, time, unicodedata, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import datetime, timezone
import argparse

ROOT=Path(__file__).resolve().parent.parent
HTML=ROOT/"index.html"
OUT=ROOT/"link-audit.json"
AGENT="Hellfest27LinkAudit/1.0 (https://github.com/leonbkim0943/hellfest27)"
LAST=0.0

def norm(s):
    return ''.join(c for c in unicodedata.normalize("NFKD",str(s)).casefold() if c.isalnum())
def get(url, mb=False):
    global LAST
    for attempt in range(3):
        if mb:
            time.sleep(max(0,1.15-(time.monotonic()-LAST)))
            LAST=time.monotonic()
        try:
            req=urllib.request.Request(url,headers={"User-Agent":AGENT,"Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=20) as r:
                return json.load(r)
        except (OSError, ValueError) as e:
            if attempt==2: raise
            time.sleep(2**(attempt+1))
def mb(path,params):
    return get("https://musicbrainz.org/ws/2/"+path+"?"+urllib.parse.urlencode(dict(params,fmt="json")),True)
def urls(row):
    out={"sp":[],"yt":[],"youtube_channels":[]}
    for rel in row.get("relations",[]):
        u=rel.get("url",{}).get("resource","")
        p=urllib.parse.urlparse(u)
        host=p.hostname or ""
        m=re.fullmatch(r"/artist/([A-Za-z0-9]{22})/?",p.path)
        if host=="open.spotify.com" and m: out["sp"].append("https://open.spotify.com/artist/"+m[1])
        m=re.fullmatch(r"/channel/(UC[A-Za-z0-9_-]{22})/?",p.path)
        if m and host=="music.youtube.com": out["yt"].append("https://music.youtube.com/channel/"+m[1])
        if m and host in {"music.youtube.com","www.youtube.com","youtube.com"}: out["youtube_channels"].append(m[1])
    return {k:sorted(set(v)) for k,v in out.items()}
def musical(a):
    labels=[a.get("disambiguation","")]+[x.get("name","") for x in a.get("tags",[])]
    return bool(re.search(r"metal|rock|punk|core|goth|industrial|folk|electronic|grind|doom|sludge|hip.hop|rap|ambient|noise|jazz|blues|alternative|shoegaze|darkwave|synth|grunge|psychedelic|country", " ".join(labels), re.I))
def exact(a,name):
    return norm(name) in {norm(a.get("name","")),norm(a.get("sort-name",""))}|{norm(x.get("name","")) for x in a.get("aliases",[])}
def artist_name(x):
    return x.get("artist") or x.get("name") or x.get("title") or ""
def snapshot(x):
    return {k:x.get(k) for k in ("id","name","disambiguation","type","country","score","tags")}
def write_report(rows,total):
    OUT.write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"total":total,"processed":len(rows),"rows":rows},ensure_ascii=False,indent=2),encoding="utf-8")
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--no-ytmusic",action="store_true")
    p.add_argument("--resume",action="store_true",help="reuse previously completed report rows")
    args=p.parse_args()
    match=re.search(r"const DATA=(\[[\s\S]*?\]);",HTML.read_text(encoding="utf-8"))
    if not match: raise ValueError("V5.4 DATA array not found")
    data=json.loads(match.group(1))
    assert len(data)==306 and len({a["name"] for a in data})==306
    ytm=None
    if not args.no_ytmusic:
        try:
            from ytmusicapi import YTMusic
            ytm=YTMusic()
        except Exception as e: print("YouTube Music search unavailable:",str(e),flush=True)
    rows=[]
    if args.resume and OUT.exists():
        rows=json.loads(OUT.read_text(encoding="utf-8")).get("rows",[])
        rows=[x for x in rows if not x.get("error") and not x.get("yt_error")]
    done={x["name"] for x in rows}
    for a in data:
        name=a["name"]
        if name in done: continue
        if args.limit and len(rows)>=args.limit: break
        row={"name":name,"genre":a["cat"],"previous_sp":a.get("sp"),"previous_yt":a.get("yt"),"musicbrainz_candidates":[],"ytmusic_candidates":[],"recommended":{},"notes":[]}
        try:
            query='artist:"'+name.replace("\\","\\\\").replace('"','\\"')+'"'
            sr=mb("artist",{"query":query,"limit":100})
            exacts=[x for x in sr.get("artists",[]) if exact(x,name) and x.get("type") in ("Group","Person","Other","Character",None)]
            row["musicbrainz_candidates"]=[snapshot(x) for x in exacts]
            # Do not silently select a namesake or use existing potentially incorrect links as proof.
            selected=exacts[0] if len(exacts)==1 and sr.get("count",0)<=100 and musical(exacts[0]) else None
            if selected:
                info=mb("artist/"+selected["id"],{"inc":"url-rels+release-groups"})
                row["musicbrainz_id"]=selected["id"]
                links=urls(info)
                row["musicbrainz_links"]=links
                albums={norm(x.get("title","")) for x in info.get("release-groups",[]) if x.get("primary-type")=="Album"}
                albums.discard("")
                row["album_titles"]=[x.get("title") for x in info.get("release-groups",[]) if x.get("primary-type")=="Album"]
                if len(links["sp"])==1:
                    row["recommended"]["sp"]={"url":links["sp"][0],"evidence":"Unique exact MusicBrainz artist with relevant music tag and explicit Spotify relationship; review official badge separately."}
                if len(links["yt"])==1:
                    row["recommended"]["yt"]={"url":links["yt"][0],"evidence":"Unique exact MusicBrainz artist with relevant music tag and explicit YouTube Music relationship; official badge not checked."}
            else:
                links={"youtube_channels":[]}
                albums=set()
                row["notes"].append("MusicBrainz artist not safely unique with a music genre signal; review candidates manually.")
            if ytm:
                try:
                    results=ytm.search(name,filter="artists",limit=12,ignore_spelling=True)
                    matches=[x for x in results if norm(artist_name(x))==norm(name) and re.fullmatch(r"UC[A-Za-z0-9_-]{22}",str(x.get("browseId","")))]
                    for x in matches:
                        cid=x["browseId"]
                        cand={"name":artist_name(x),"url":"https://music.youtube.com/channel/"+cid,"subscribers":x.get("subscribers"),"album_overlap":[]}
                        row["ytmusic_candidates"].append(cand)
                        if not selected: continue
                        try:
                            detail=ytm.get_artist(cid)
                            if norm(detail.get("name",""))!=norm(name): continue
                            y_albums={norm(z.get("title","")) for z in (detail.get("albums") or {}).get("results",[]) if isinstance(z,dict)}
                            cand["album_overlap"]=sorted(albums & y_albums)
                            cand["matching_link"]=cid in links["youtube_channels"]
                            if cand["matching_link"] or len(cand["album_overlap"])>=2:
                                cand["corroborated"]=True
                        except Exception as e: cand["error"]=str(e)[:250]
                    corroborated=[x for x in row["ytmusic_candidates"] if x.get("corroborated")]
                    if len(corroborated)==1 and "yt" not in row["recommended"]:
                        row["recommended"]["yt"]={"url":corroborated[0]["url"],"evidence":"Exact YouTube Music artist name and matching MusicBrainz channel or at least two album titles; official badge not checked."}
                except Exception as e: row["yt_error"]=str(e)[:300]
        except Exception as e: row["error"]=str(e)[:300]
        rows.append(row)
        write_report(rows,len(data))
        print(f'{len(rows)}/{len(data)} {name}: {",".join(row["recommended"]) or "review"}',flush=True)
    write_report(rows,len(data))
    print("Report complete:",len(rows),"artists;",sum(len(r["recommended"]) for r in rows),"corroborated link candidates",flush=True)
if __name__=="__main__":
    main()
