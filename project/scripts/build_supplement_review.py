"""Build a separate fixed 12-work English feedback instrument from saved results.

Condition allocation uses fixed counts and recorded seeds, not score/visual
success. Source rankings already existed; this is a new feedback design.
"""
from __future__ import annotations
import argparse,base64,csv,hashlib,html,io,json,random,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from PIL import Image,ImageOps,ImageDraw,ImageFont

sys.dont_write_bytecode=True
ALLOCATION_SEED=2026111805
PRESENTATION_SEED=2026112805
VERSION='style-supplement-12-v1'
QUESTIONNAIRE_ID='SUP12'
EXPERIMENT_ID='frame-echo-supplement-review12-v1-20261118'
SLOTS=[('V01','colour'),('V01','clip'),('V02','colour'),('V02','clip'),('V03','colour'),('V03','clip'),
       ('V04','colour'),('V04','colour'),('V04','clip'),('V05','colour'),('V05','clip'),('V05','clip')]

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()
def dump(path,value):
 Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
def csvout(path,rows,columns=None):
 with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=columns or list(rows[0]));writer.writeheader();writer.writerows(rows)
def image_uri(path):
 with Image.open(path) as im:shown=ImageOps.contain(im.convert('RGB'),(800,700))
 memory=io.BytesIO();shown.save(memory,'JPEG',quality=92)
 return 'data:image/jpeg;base64,'+base64.b64encode(memory.getvalue()).decode('ascii')
def protected_paths(root):
 paths=[]
 for rel in ['data/pilots','data/evaluation','data/raw','data/models','docs/thesis','app','scripts']:
  paths.extend(p for p in (root/rel).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store' and not p.name.startswith('~$'))
 manifest=json.loads((root/'data/evaluation/2026-11-18-human-feedback-r1/provenance/input-manifest.json').read_text())
 paths.extend(Path(x['original_path']) for x in manifest)
 return {str(p.resolve()):sha(p) for p in sorted(set(paths))}
def assert_unchanged(protected):
 for name,digest in protected.items():assert Path(name).is_file() and sha(name)==digest,name
def font(size):return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',size)
def tile(board,path,box):
 with Image.open(path) as im:image=ImageOps.contain(im.convert('RGB'),(box[2]-box[0],box[3]-box[1]))
 board.paste(image,((box[0]+box[2]-image.width)//2,(box[1]+box[3]-image.height)//2))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--project-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 args=p.parse_args();root=args.project_root.resolve();out=args.output.resolve()
 assert not out.exists(),'Use a new questionnaire directory, never overwrite an existing study'
 sys.path.insert(0,str(root));sys.path.insert(0,str(Path(__file__).parent))
 from style_review_ui import write_supplement_review_page
 source=root/'data/pilots/2026-11-18-style-supplement-r1'
 result_path=source/'results.json';source_hash=sha(result_path)
 result=json.loads(result_path.read_text())
 assert result['verified_counts']['conditions']==120 and result['verified_counts']['artworks']==12
 old_results=json.loads((root/'data/pilots/2026-11-13-expanded-artworks-100/results.json').read_text())
 old_queries={a['normalized_sha256'] for a in old_results['artworks']}
 artworks={a['asset_id']:a for a in result['artworks']}
 ids=sorted(artworks,key=lambda a:int(a[1:]));assert ids==[f'S{i:02d}' for i in range(1,13)]
 cases={(c['artwork_id'],c['video_id'],c['method']):c for c in result['cases']}
 assert len(cases)==120
 protected=protected_paths(root)
 slots=SLOTS.copy();random.Random(ALLOCATION_SEED).shuffle(slots)
 choices=[]
 for aid,(vid,assigned) in zip(ids,slots):
  art=artworks[aid];match=cases[aid,vid,assigned]['matches'][0]
  assert match['rank']==1
  ap,fp=source/art['normalized_path'],source/match['frame_path']
  assert sha(ap)==art['normalized_sha256'] and sha(fp)==match['frame_sha256']
  assert art['normalized_sha256'] not in old_queries
  membership=[m for m in ['colour','clip'] if cases[aid,vid,m]['matches'][0]['frame_sha256']==match['frame_sha256']]
  candidate='C'+hashlib.sha256((result['experiment_id']+'|'+aid+'|'+vid+'|'+match['frame_sha256']).encode()).hexdigest()[:12]
  choices.append({'artwork_id':aid,'artwork_title':art['title'],'artist':art['artist'],'video_id':vid,'assigned_method':assigned,
    'actual_top1_method_membership':';'.join(membership),'source_rank':1,'source_score':match['cosine_similarity'],
    'timestamp_seconds':match['timestamp_seconds'],'timestamp_label':match['timestamp_label'],'candidate_id':candidate,
    'frame_sha256':match['frame_sha256'],'normalized_artwork_sha256':art['normalized_sha256'],
    'normalized_artwork_path':str(ap.relative_to(root)),'frame_path':str(fp.relative_to(root)),
    'source_experiment_id':result['experiment_id'],'questionnaire_id':QUESTIONNAIRE_ID,'review_version':VERSION})
 assert Counter(c['assigned_method'] for c in choices)=={'colour':6,'clip':6}
 assert Counter(c['video_id'] for c in choices)=={'V01':2,'V02':2,'V03':2,'V04':3,'V05':3}
 random.Random(PRESENTATION_SEED).shuffle(choices)
 for i,c in enumerate(choices,1):c['presentation_order']=i
 out.mkdir(parents=True);(out/'organizer').mkdir();(out/'provenance').mkdir()
 plan={'experiment_id':EXPERIMENT_ID,'review_version':VERSION,'questionnaire_id':QUESTIONNAIRE_ID,'created_at_utc':datetime.now(timezone.utc).isoformat(),
   'source_experiment_id':result['experiment_id'],'source_results_path':str(result_path.relative_to(root)),'source_results_sha256':source_hash,
   'selection_timing':'Source retrieval and researcher case inspection already existed. This fixed questionnaire is selected before any ratings for this new version, not preregistered before retrieval.',
   'selection_rule':'Sort S01–S12 numerically. Shuffle the recorded 12 video/method slots once with the allocation seed, assign one slot to each artwork, and use that condition’s saved Top1. Shuffle presentation order once with a separate seed. Do not search seeds or replace pairs based on scores, perceived success or old participant ratings.',
   'allocation_seed':ALLOCATION_SEED,'presentation_seed':PRESENTATION_SEED,'fixed_slots_before_shuffle':SLOTS,
   'counts':{'fixed_questionnaires':1,'pairs':12,'distinct_artworks':12,'assigned_colour':6,'assigned_clip':6,'per_video':{'V01':2,'V02':2,'V03':2,'V04':3,'V05':3}},
   'why_video_counts_differ':'Twelve slots cannot be split equally across five videos. The three online references each contribute two and the two self-recorded videos each contribute three.',
   'participant_policy':'Every reviewer sees the same 12pairs and saved shuffled order. Use a separate anonymous ID per person; returning people can retain their existing anonymous ID. A new experiment/dataset separates this instrument from earlier versions.',
   'measurement':'Four separate 1–5/unsure visual ratings. Optional connection, frame-quality flags and comment. Blank answers remain blank; no scores are generated.',
   'analysis_limits':'Method balancing does not remove artwork/video confounding. The same artwork is not judged under both methods here. Compare item/reviewer judgments descriptively and retain actual membership when both methods return the same image. Do not pool earlier versions as identical material.',
   'fixed_order_limit':'The order is shuffled once and shared, not counterbalanced across reviewers.',
   'new_ratings_collected':0,'prior_questionnaires_and_four_exports':'Preserved unchanged, including browser records. QA uses only a temporary browser profile.',
   'items':choices}
 dump(out/'organizer/selection-plan.json',plan);plan_hash=sha(out/'organizer/selection-plan.json')
 items=[];embedding=[]
 for c in choices:
  reference=image_uri(root/c['normalized_artwork_path']);frame=image_uri(root/c['frame_path'])
  items.append({key:c[key] for key in ['candidate_id','artwork_id','artwork_title','artist','video_id','frame_sha256','presentation_order']}|
   {'reference_image':reference,'frame_image':frame,'canonical_timestamp':c['timestamp_seconds']})
  embedding.append({'candidate_id':c['candidate_id'],'reference_jpeg_sha256':hashlib.sha256(base64.b64decode(reference.split(',',1)[1])).hexdigest(),
    'frame_jpeg_sha256':hashlib.sha256(base64.b64decode(frame.split(',',1)[1])).hexdigest(),'display_rule':'Contain within800x700, preserve aspect ratio, no cropping, JPEGquality92; source originals retain their recorded SHA256.'})
 ui=write_supplement_review_page(out/'review.html',items,EXPERIMENT_ID,PRESENTATION_SEED,QUESTIONNAIRE_ID,result['experiment_id'],plan_hash)
 page=(out/'review.html').read_text()
 import re
 payload=json.loads(re.search(r'<script id="review-data" type="application/json">(.*?)</script>',page,re.S).group(1))
 assert len(payload['items'])==len({i['artwork_id'] for i in payload['items']})==12
 forbidden={'method','assigned_method','actual_top1_method_membership','rank','source_rank','score','source_score','cosine_similarity','visual_direction','selection_rationale','human_label'}
 assert all(not(set(i)&forbidden) for i in payload['items'])
 assert payload['experiment_id']==EXPERIMENT_ID and payload['questionnaire_id']==QUESTIONNAIRE_ID
 for c in choices:c['dataset_id']=payload['dataset_id']
 dump(out/'organizer/review-key.json',{'experiment_id':EXPERIMENT_ID,'review_version':VERSION,'questionnaire_id':QUESTIONNAIRE_ID,'source_experiment_id':result['experiment_id'],
   'source_results_sha256':source_hash,'selection_plan_sha256':plan_hash,'dataset_id':payload['dataset_id'],'items':choices,'ratings_collected':0})
 csvout(out/'organizer/review-key.csv',choices)
 columns=['experiment_id','reviewer_id','candidate_id','artwork_id','video_id','frame_sha256','presentation_order','timestamp_seconds','colour','composition','content','overall','relevance','quality_flags','comment','completed','questionnaire_id','review_version','dataset_id','source_experiment_id']
 csvout(out/'review-response-template.csv',[],columns)
 dump(out/'provenance/display-image-hashes.json',embedding)
 dump(out/'provenance/protected-files-before.json',protected)
 # Organizer overview is separate from the participant HTML and contains the
 # hidden retrieval mapping. Participant instructions link only to review.html.
 board=Image.new('RGB',(1500,6*250+48),'#f5f2e9');draw=ImageDraw.Draw(board)
 draw.text((12,10),'Organizer overview — selected12pairs, no participant ratings',font=font(21),fill='black')
 for n,c in enumerate(choices):
  x,y=(n%2)*750,(n//2)*250+48
  tile(board,root/c['normalized_artwork_path'],(x+6,y,x+365,y+190));tile(board,root/c['frame_path'],(x+380,y,x+740,y+190))
  draw.text((x+10,y+194),f"{n+1:02d} {c['artwork_id']} / {c['video_id']} {c['assigned_method']} {c['timestamp_label']}",font=font(17),fill='black')
  draw.text((x+10,y+219),c['artwork_title'][:65],font=font(15),fill='#4a5544')
 board.save(out/'organizer/selection-overview.jpg',quality=95)
 esc=lambda t:html.escape(str(t),quote=True)
 body='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame Echo — Supplemental12-pair feedback</title><style>*{box-sizing:border-box}body{margin:0;background:#f5f2e9;color:#252a25;font:16px/1.65 system-ui,-apple-system,sans-serif}main{max-width:830px;margin:7vh auto;padding:26px}h1{font-size:34px;line-height:1.2}a{color:#96472f}.button{display:inline-block;background:#96472f;color:white;padding:11px 18px;text-decoration:none;border-radius:3px}.note{font-size:14px;color:#606b59}li{margin:12px 0}@media(max-width:600px){main{margin:20px auto;padding:18px}}</style><main><p class="note">FRAME ECHO / SEPARATE SUPPLEMENTAL FEEDBACK</p><h1>Rate12different artworks and video frames</h1><p>This questionnaire contains12pairs, with a different artwork in each pair. Every reviewer sees the same materials. There is no correct or expected response.</p><p><a class="button" href="review.html">Open rating questionnaire</a></p><ol><li>Enter your assigned anonymous reviewer ID and select Start / resume. New reviewers can use R01, R02 and so on. Returning reviewers can retain their previous anonymous ID.</li><li>Rate colour, composition, content and overall connection separately. Choose Not sure when needed. Comments and the connection question are optional.</li><li>Export a CSV before switching reviewer IDs or closing the page. Use the same ID to resume saved progress.</li></ol><p class="note">This is a separate questionnaire version. Earlier completed forms and responses remain unchanged. Responses stay on this computer unless you export and share them.</p></main></html>'''
 (out/'index.html').write_text(body.replace('Supplemental12','Supplemental 12').replace('Rate12','Rate 12').replace('contains12','contains 12'))
 rows=''.join('<tr>'+''.join('<td>'+esc(c[k])+'</td>' for k in ['presentation_order','artwork_id','artwork_title','video_id','assigned_method','actual_top1_method_membership','timestamp_label','source_score'])+'</tr>' for c in choices)
 (out/'organizer/index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Organizer key — Supplemental 12 pairs</title><style>body{font:15px/1.6 system-ui;margin:28px;color:#252a25}img{max-width:100%;height:auto}table{border-collapse:collapse}th,td{padding:9px;border:1px solid #d4d8cd;text-align:left}th{background:#eef0e8}.wrap{overflow:auto}a{color:#95472f}</style><h1>Organizer key — do not show this page during ratings</h1><p>Prepared: 12 distinct artworks, 6 assigned colour and 6 assigned CLIP. V01–V03 each contribute 2 pairs; V04/V05 each contribute 3. Source frames happen to be unique in this fixed selection. S11 is assigned to CLIP but its frame is Top 1 for both methods.</p><p>Allocation uses one recorded seed without score/visual-success search. Sources and researcher case observations existed before this selection, so this is a new exploratory feedback design rather than pre-ranking registration. Method-wide mean differences would remain confounded by artwork and video.</p><p><a href="../review.html">Participant page</a> · <a href="review-key.csv">Key CSV</a> · <a href="selection-plan.json">Selection plan</a></p><img src="selection-overview.jpg" alt="Twelve selected image pairs"><div class="wrap"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in ['Order','Artwork','Title','Video','Assigned method','Actual Top 1 membership','Timestamp','Raw source score'])+'</tr></thead><tbody>'+rows+'</tbody></table></div></html>')
 assert sha(result_path)==source_hash
 assert_unchanged(protected)
 validation={'pairs':12,'different_artworks':12,'method_allocation':dict(Counter(c['assigned_method'] for c in choices)),
  'video_allocation':dict(Counter(c['video_id'] for c in choices)),'duplicate_video_frame_count':12-len({(c['video_id'],c['frame_sha256']) for c in choices}),
  'dual_top1_membership_count':sum(';' in c['actual_top1_method_membership'] for c in choices),'source_identifiers_hashes_and_top1_verified':True,
  'embedded_payload_blinded':True,'initial_answers_supplied':0,'protected_existing_files_unchanged':len(protected),'source_results_unchanged':True,
  'dataset_id':payload['dataset_id'],'selection_plan_sha256':plan_hash,'new_experiment_id':EXPERIMENT_ID}
 dump(out/'provenance/validation.json',validation)
 print(json.dumps(validation,indent=2),flush=True)

if __name__=='__main__':main()
