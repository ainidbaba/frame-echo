"""Compare unchanged colour/CLIP methods on two new self-recorded videos.

The human subset is declared before any new rankings: 5 fixed artwork queries,
both videos, Top 1 from both methods, exact-frame deduplication within each
artwork/video pair, and a recorded shuffle. No human answers are generated.
"""
from __future__ import annotations
import argparse, base64, csv, hashlib, html, importlib.metadata, io, json, math, os
from pathlib import Path
import platform, random, shutil, sys, time
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageFont

METHODS=('colour','clip')
SETTINGS={'interval':1.0,'top_k':6,'min_gap':3.0,'min_score':None,'temporal_quality_gate':False}
REVIEW_IDS=('A07','A18','A28','A43','A54')
SEED=20261117
VIDEO_FILES=(('V04','dog_bar.mp4'),('V05','theweeknd.mp4'))


def now(): return datetime.now(timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
    return h.hexdigest()
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.partial');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def csvout(p,rows,fields=None):
    with Path(p).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def ensure(c,m):
    if not c:raise RuntimeError(m)
def encode(encoder,paths,batch=16,label=''):
    out=[]
    for i in range(0,len(paths),batch):
        ims=[]
        try:
            for p in paths[i:i+batch]:
                with Image.open(p) as im:ims.append(im.convert('RGB'))
            out.append(encoder.encode(ims))
        finally:
            for im in ims:im.close()
        print(f'ENCODE {label}: {min(i+batch,len(paths))}/{len(paths)}',flush=True)
    a=np.concatenate(out)
    ensure(np.isfinite(a).all() and np.allclose(np.linalg.norm(a,axis=1),1,atol=1e-5),'Invalid features')
    return a

def uri(p,size=(800,700)):
    with Image.open(p) as im:
        x=ImageOps.contain(im.convert('RGB'),size)
    out=io.BytesIO();x.save(out,'JPEG',quality=92)
    return 'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode('ascii')

def font(size):
    for p in ['/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Helvetica.ttc']:
        if Path(p).is_file():return ImageFont.truetype(p,size)
    return ImageFont.load_default(size=size)

def tile(board,path,box):
    with Image.open(path) as im:x=ImageOps.contain(im.convert('RGB'),(box[2]-box[0],box[3]-box[1]))
    board.paste(x,((box[0]+box[2]-x.width)//2,(box[1]+box[3]-x.height)//2))

def contacts(output,videos,artworks,cases):
    for v in videos:
        for start in range(0,len(v['frames']),40):
            fs=v['frames'][start:start+40];rows=math.ceil(len(fs)/10)
            im=Image.new('RGB',(1600,rows*225+45),'#f2f2ee');d=ImageDraw.Draw(im)
            d.text((12,10),f"{v['asset_id']} source samples / page {start//40+1}",font=font(17),fill='black')
            for i,f in enumerate(fs):
                col,row=i%10,i//10;x,y=col*160,row*225+45
                tile(im,output/f['path'],(x+5,y,x+155,y+195))
                d.text((x+6,y+199),f['timestamp_label'],font=font(13),fill='black')
            im.save(output/'organizer'/f"source-{v['asset_id']}-{start//40+1:02d}.jpg",quality=94)
    by={(c['artwork_id'],c['video_id'],c['method']):c for c in cases}
    for start in range(0,len(artworks),5):
        arts=artworks[start:start+5]
        im=Image.new('RGB',(1500,len(arts)*240+45),'#f2f2ee');d=ImageDraw.Draw(im)
        d.text((12,10),'Reference | V04 colour / CLIP | V05 colour / CLIP: Top 1, organizer view',font=font(16),fill='black')
        for row,a in enumerate(arts):
            files=[(a['normalized_path'],a['asset_id']+' reference')]
            for v in videos:
                for m in METHODS:
                    x=by[a['asset_id'],v['asset_id'],m]['matches'][0]
                    files.append((x['frame_path'],f"{v['asset_id']} {m} {x['timestamp_label']}"))
            for col,(p,label) in enumerate(files):
                x,y=col*300,row*240+45
                tile(im,output/p,(x+8,y,x+292,y+205))
                d.text((x+8,y+211),label,font=font(15),fill='black')
        im.save(output/'organizer'/f'top1-overview-{start//5+1:02d}.jpg',quality=94)


def report(output,result):
    payload={
      'artworks':[{k:a[k] for k in ['asset_id','title','artist','object_url','normalized_path']} for a in result['artworks']],
      'videos':[{k:v[k] for k in ['asset_id','filename','info']} for v in result['videos']],
      'cases':[{k:c[k] for k in ['artwork_id','video_id','method','matches']} for c in result['cases']]}
    compact=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    template='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame Echo — New video comparison</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f2ec;color:#242922;font:16px/1.6 system-ui}main{max-width:1380px;margin:auto;padding:28px}h1{margin:0}label{display:inline-flex;gap:10px;align-items:center;margin:14px 25px 14px 0}select{padding:8px;font:inherit;max-width:85vw}.note{background:#e6ebdf;padding:15px}.reference{display:flex;align-items:center;gap:25px;margin:18px 0}.reference img{width:280px;height:220px;object-fit:contain}.compare{display:grid;grid-template-columns:1fr 1fr;gap:24px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.match{background:#fffdf9;padding:8px}.match img{width:100%;height:220px;object-fit:contain}.match p{font-size:13px;margin:5px 0}.small{color:#56624f;font-size:13px}a{color:#93472f}@media(max-width:850px){.compare{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,1fr)}.reference{display:block}main{padding:16px}}</style>
<main><h1>New self-recorded video comparison</h1><p class="note">__COUNTS__. Shared sampling: 1 second; up to 6 results, at least 3 seconds apart. Minimum-score filtering and the temporal quality gate are disabled. Scores are raw similarities, not relevance probabilities. Human ratings have not been collected.</p>
<p><a href="review.html">Open the English participant rating page</a> · <a href="rankings.csv">All rankings</a> · <a href="results.json">Run metadata</a> · <a href="organizer/review-key.csv">Organizer key — do not send to participants</a></p>
<label>Video<select id="video"></select></label><label>Artwork<select id="artwork"></select></label>
<div class="reference"><img id="reference" alt="Reference artwork"><div><h2 id="title"></h2><p id="artist"></p><a id="source">Official artwork record</a></div></div><div class="compare"><section><h2>Colour and coarse layout</h2><div class="grid" id="colour"></div></section><section><h2>CLIP image features</h2><div class="grid" id="clip"></div></section></div><p class="small">This organizer view displays method names, ranks and scores. Use review.html alone with participants. The 5 artwork IDs for human review were fixed before ranking; the set is exploratory and is not a representative accuracy estimate. Video capture dates have not been supplied.</p></main><script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);function opt(v,t){let o=document.createElement('option');o.value=v;o.textContent=t;return o;}data.videos.forEach(v=>$('video').append(opt(v.asset_id,v.asset_id+' — '+v.filename)));data.artworks.forEach(a=>$('artwork').append(opt(a.asset_id,a.asset_id+' — '+a.title)));
function draw(){let a=data.artworks.find(x=>x.asset_id===$('artwork').value);$('reference').src=a.normalized_path;$('title').textContent=a.asset_id+': '+a.title;$('artist').textContent=a.artist;$('source').href=a.object_url;for(let m of ['colour','clip']){let g=$(m);g.replaceChildren();let c=data.cases.find(x=>x.artwork_id===a.asset_id&&x.video_id===$('video').value&&x.method===m);for(let x of c.matches){let card=document.createElement('div');card.className='match';let img=document.createElement('img');img.src=x.frame_path;img.alt='Retrieved video frame';let p=document.createElement('p');p.textContent='#'+x.rank+' '+x.timestamp_label+' | '+x.cosine_similarity.toFixed(4);card.append(img,p);g.append(card);}}}for(let id of ['video','artwork'])$(id).addEventListener('change',draw);draw();</script></html>'''
    counts=result['verified_counts']
    label=f"100 artworks × 2 new videos × 2 methods = {counts['conditions']} conditions; {counts['sampled_frames']} sampled frames; {counts['ranked_records']} ranked records"
    (output/'index.html').write_text(template.replace('__COUNTS__',label).replace('__DATA__',compact))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run-id',default='2026-11-17-self-recorded-r1')
    args=p.parse_args();root=args.project_root.resolve();output=args.output.resolve()
    ensure(not output.exists(),'Choose a fresh output directory; prior runs must not be overwritten')
    sys.path.insert(0,str(root))
    from app.retrieval import get_encoder,rank_matches
    from app.video import extract_frames,probe_video,timestamp_label
    from english_review_page import write_english_review_page
    import torch
    torch.set_num_threads(4)
    baseline_file=root/'data/pilots/2026-11-13-expanded-artworks-100/results.json'
    baseline=json.loads(baseline_file.read_text());old_hash=sha(baseline_file)
    model=root/'data/models/open_clip_model.safetensors'
    ensure(sha(model)==baseline['checkpoint']['sha256'],'Checkpoint changed')
    artworks=[]
    for a in baseline['artworks']:
        source=root/a['normalized_path'];ensure(sha(source)==a['normalized_sha256'],'Changed normalized artwork')
        artworks.append({**a,'prior_normalized_path':a['normalized_path'],'normalized_path':f"queries/{a['asset_id']}.png"})
    ensure(len(artworks)==100 and len({a['asset_id'] for a in artworks})==100,'Expected existing 100 artworks')
    videos=[]
    for vid,name in VIDEO_FILES:
        source=root/'data/raw/videos'/name
        ensure(source.is_file(),'Missing declared new video '+name)
        videos.append({'asset_id':vid,'filename':name,'path':str(source.relative_to(root)),'sha256':sha(source),
          'info':probe_video(source),'provenance':'Self-recorded; explicitly confirmed by the student in this chat on 16 November 2026',
          'creator':'Student (self-recorded; user-confirmed)','capture_date':'unknown','source_url':'',
          'first_local_access_date':'2026-11-16','query_artwork_present_in_video':'unknown'})
    output.mkdir(parents=True)
    for name in ['queries','frames','features','organizer','pairs']:(output/name).mkdir()
    plan={'experiment_id':'frame-echo-'+args.run_id,'run_id':args.run_id,'created_at_utc':now(),
      'design':'New-footage development comparison with a predeclared purposive Top 1 subset for future human ratings. No training, human ratings or accuracy estimate.',
      'settings':SETTINGS,'methods':list(METHODS),'artworks':artworks,'videos':videos,
      'selection_frozen_before_ranking':True,'checkpoint':baseline['checkpoint'],
      'baseline_results_sha256':old_hash,
      'code_hashes':{str(x.relative_to(root)):sha(x) for x in [root/'app/retrieval.py',root/'app/video.py']},
      'driver_sha256':sha(Path(__file__)),
      'environment':{'python':sys.version,'platform':platform.platform(),'device':'cpu','torch_threads':torch.get_num_threads(),
        'packages':{n:importlib.metadata.version(n) for n in ['numpy','Pillow','opencv-python-headless','torch','open_clip_torch']}},
      'human_review_plan':{'artwork_ids':list(REVIEW_IDS),'video_ids':['V04','V05'],'methods':list(METHODS),'top_k_per_method':1,
        'selection_rule':'Fixed before new rankings: existing catalogue queries spanning landscape, portrait, still life, music/dance and architecture. This is a purposive exploratory selection, not a random or representative sample; no success-based replacement.',
        'deduplication_key':['artwork_id','video_id','frame_sha256'],'maximum_pairs':20,
        'shuffle_seed':SEED,'presentation_order_policy':'One recorded shuffled order for all reviewers; not counterbalanced.',
        'rating_dimensions':['colour','composition','content','overall'],'ratings_status':'not collected','direct_artwork_appearance':'unknown until inspected'},
      'planned_counts':{'artworks':100,'new_videos':2,'conditions':400,'maximum_ranked_records':2400}}
    dump(output/'plan.json',plan)
    plan_hash=sha(output/'plan.json')
    print('PLAN FROZEN before ranking:',plan_hash,flush=True)
    for a in artworks:shutil.copy2(root/a['prior_normalized_path'],output/a['normalized_path'])
    timings=[]
    for v in videos:
        start=time.perf_counter()
        info,fs=extract_frames(root/v['path'],output/'frames'/v['asset_id'],SETTINGS['interval'])
        v['info']=info;v['frames']=[{'path':str(f['path'].relative_to(output)),'timestamp':f['timestamp'],'timestamp_label':timestamp_label(f['timestamp']),'sha256':sha(f['path'])} for f in fs]
        dump(output/'frames'/v['asset_id']/'index.json',{'video_sha256':v['sha256'],'interval_seconds':1.0,'info':info,'frames':v['frames']})
        timings.append({'stage':'decode_video','method':'','video_id':v['asset_id'],'seconds':time.perf_counter()-start})
        print('DECODE',v['asset_id'],len(fs),'frames',round(info['duration'],3),'seconds',info['timestamp_source'],flush=True)
    rows=[];cases=[]
    for method in METHODS:
        start=time.perf_counter();enc=get_encoder(method,model)
        timings.append({'stage':'load_encoder','method':method,'video_id':'','seconds':time.perf_counter()-start})
        preprocess=str(getattr(enc,'preprocess','RGB -> resize144x144 -> HSV global+3x3 histograms'))
        start=time.perf_counter();queries=encode(enc,[output/a['normalized_path'] for a in artworks],16,method+' artwork')
        timings.append({'stage':'encode_queries','method':method,'video_id':'','seconds':time.perf_counter()-start})
        for v in videos:
            start=time.perf_counter();features=encode(enc,[output/f['path'] for f in v['frames']],16,method+' '+v['asset_id'])
            times=[f['timestamp'] for f in v['frames']]
            timings.append({'stage':'encode_video','method':method,'video_id':v['asset_id'],'seconds':time.perf_counter()-start})
            np.savez_compressed(output/'features'/f"{v['asset_id']}_{method}.npz",frames=features,queries=queries,timestamps=np.asarray(times))
            for a,q in zip(artworks,queries):
                matches=rank_matches(q,features,times,6,3.0,min_score=None)
                ensure(0<len(matches)<=6,'Unexpected match count')
                records=[]
                for rank,m in enumerate(matches,1):
                    f=v['frames'][m['index']]
                    x={'experiment_id':plan['experiment_id'],'video_id':v['asset_id'],'artwork_id':a['asset_id'],'artwork_title':a['title'],'method':method,'model_id':enc.model_id,'rank':rank,
                      'timestamp_seconds':m['timestamp'],'timestamp_label':timestamp_label(m['timestamp']),'cosine_similarity':m['score'],'interval_seconds':1.0,'minimum_gap_seconds':3.0,'minimum_score':'','requested_top_k':6,
                      'sampled_frames':len(times),'frame_path':f['path'],'frame_sha256':f['sha256'],'video_sha256':v['sha256'],'artwork_sha256':a['original_sha256'],'normalized_query_sha256':a['normalized_sha256'],
                      'timestamp_source':v['info']['timestamp_source'],'synthetic':False,'identity_match_status':'not assessed','human_relevance_label':'not collected'}
                    records.append(x);rows.append(x)
                ensure(all(records[i]['cosine_similarity']>=records[i+1]['cosine_similarity'] for i in range(len(records)-1)),'Ranking not sorted')
                ensure(all(abs(x['timestamp_seconds']-y['timestamp_seconds'])+1e-9>=3.0 for i,x in enumerate(records) for y in records[i+1:]),'Temporal spacing failed')
                cases.append({'video_id':v['asset_id'],'artwork_id':a['asset_id'],'method':method,'preprocess':preprocess,'matches':records})
            print('RANKED',v['asset_id'],method,'100 conditions; top-count distribution',dict(Counter(len(c['matches']) for c in cases if c['video_id']==v['asset_id'] and c['method']==method)),flush=True)
        del enc
    expected={(a['asset_id'],v['asset_id'],m) for a in artworks for v in videos for m in METHODS}
    ensure({(c['artwork_id'],c['video_id'],c['method']) for c in cases}==expected and len(cases)==400,'Incomplete or duplicate conditions')
    ensure(sha(output/'plan.json')==plan_hash,'Frozen plan was modified')
    ensure(sha(baseline_file)==old_hash,'Earlier expanded experiment changed')
    for v in videos:ensure(sha(root/v['path'])==v['sha256'],'Source video changed during run')
    counts={'artworks':100,'videos':2,'conditions':len(cases),'sampled_frames':sum(len(v['frames']) for v in videos),'frames_by_video':{v['asset_id']:len(v['frames']) for v in videos},'ranked_records':len(rows)}
    result={**plan,'videos':videos,'status':'complete','completed_at_utc':now(),'plan_sha256':plan_hash,'verified_counts':counts,'cases':cases,'timings':timings,'human_evaluation_status':'not collected','accuracy_status':'not estimated','earlier_expanded_experiment_unchanged':True}
    dump(output/'results.json',result);csvout(output/'rankings.csv',rows);csvout(output/'timings.csv',timings)
    csvout(output/'artworks.csv',[{k:a.get(k,'') for k in ['asset_id','title','artist','date','institution','object_url','original_path','original_sha256','normalized_path','normalized_sha256']} for a in artworks])
    by={(c['artwork_id'],c['video_id'],c['method']):c for c in cases}
    art_by={a['asset_id']:a for a in artworks};groups={}
    for aid in REVIEW_IDS:
        for v in videos:
            for m in METHODS:
                x=by[aid,v['asset_id'],m]['matches'][0]
                key=(aid,v['asset_id'],x['frame_sha256'])
                if key not in groups:groups[key]={'artwork_id':aid,'video_id':v['asset_id'],'frame_sha256':x['frame_sha256'],'frame_path':x['frame_path'],'memberships':[]}
                groups[key]['memberships'].append({k:x[k] for k in ['method','rank','timestamp_seconds','timestamp_label','cosine_similarity']})
    chosen=list(groups.values());random.Random(SEED).shuffle(chosen)
    items=[];keyrows=[]
    for i,g in enumerate(chosen,1):
        aid=g['artwork_id'];a=art_by[aid]
        cid='C'+hashlib.sha256((plan['experiment_id']+'|'+aid+'|'+g['video_id']+'|'+g['frame_sha256']).encode()).hexdigest()[:12]
        stamp=min(m['timestamp_seconds'] for m in g['memberships'])
        g.update(candidate_id=cid,presentation_order=i,canonical_timestamp=stamp,artwork_title=a['title'],artist=a['artist'],normalized_artwork_path=a['normalized_path'],same_artwork_visible='unknown')
        items.append({k:g[k] for k in ['candidate_id','artwork_id','artwork_title','artist','video_id','frame_sha256','presentation_order','canonical_timestamp']} | {'reference_image':uri(output/a['normalized_path']),'frame_image':uri(output/g['frame_path'])})
        keyrows.append({'candidate_id':cid,'presentation_order':i,'artwork_id':aid,'video_id':g['video_id'],'timestamp_seconds':stamp,'frame_sha256':g['frame_sha256'],'method_membership':';'.join(m['method'] for m in g['memberships']),'source_ranks':';'.join(f"{m['method']}:{m['rank']}" for m in g['memberships']),'source_scores':';'.join(f"{m['method']}:{m['cosine_similarity']:.9f}" for m in g['memberships']),'same_artwork_visible':'unknown','artwork_title':a['title'],'frame_path':g['frame_path'],'normalized_artwork_path':a['normalized_path']})
        image=Image.new('RGB',(1200,710),'#f4f2ec');d=ImageDraw.Draw(image)
        d.text((20,15),f'Pair {i:02d} / {cid}',font=font(22),fill='black')
        d.text((20,55),'Reference artwork',font=font(18),fill='black');d.text((620,55),'Video frame',font=font(18),fill='black')
        tile(image,output/a['normalized_path'],(20,90,580,680));tile(image,output/g['frame_path'],(620,90,1180,680))
        image.save(output/'pairs'/f'{i:02d}_{cid}.png')
    ensure(10<=len(items)<=20,'Unexpected review subset size')
    dump(output/'organizer'/'review-key.json',{'experiment_id':plan['experiment_id'],'plan_sha256':plan_hash,'seed':SEED,'selection':plan['human_review_plan'],'items':chosen})
    csvout(output/'organizer'/'review-key.csv',keyrows)
    csvout(output/'review-response-template.csv',[],fields=['experiment_id','reviewer_id','candidate_id','artwork_id','video_id','frame_sha256','presentation_order','timestamp_seconds','colour','composition','content','overall','relevance','quality_flags','comment','completed'])
    write_english_review_page(output/'review.html',items,plan['experiment_id'],SEED)
    contacts(output,videos,artworks,cases)
    report(output,result)
    summary={'experiment_id':plan['experiment_id'],'counts':counts,'review_artwork_ids':list(REVIEW_IDS),'review_query_video_pairs':10,'review_unique_image_pairs':len(items),'review_method_top1_records':20,'duplicate_top1_records_collapsed':20-len(items),'ratings_collected':0,'scores_are_not_relevance_probabilities':True}
    dump(output/'summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
