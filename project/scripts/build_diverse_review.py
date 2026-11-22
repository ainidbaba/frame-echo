"""Prepare diverse offline feedback forms from saved Top 1 retrieval outputs.

No retrieval is rerun and no participant scores are supplied. Each form has
12 distinct artworks, balanced video/method allocation, four crossed anchors
and eight rotating artworks. Actual collection remains separate from design.
"""
from __future__ import annotations
import argparse,base64,csv,hashlib,io,json,random,sys
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from PIL import Image,ImageOps

SEED=2026111803
METHODS=('colour','clip');VIDEOS=('V04','V05')
CELLS=[(v,m) for v in VIDEOS for m in METHODS]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def csvout(p,rows,fields=None):
 with Path(p).open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)
def uri(p):
 with Image.open(p) as im:x=ImageOps.contain(im.convert('RGB'),(800,700))
 b=io.BytesIO();x.save(b,'JPEG',quality=92);return 'data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode('ascii')

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();root=a.project_root.resolve();out=a.output.resolve()
 if out.exists():raise RuntimeError('Choose a fresh output directory; do not overwrite a study version')
 sys.path.insert(0,str(root))
 from diverse_review_ui import write_assigned_review_page,write_launcher
 source=root/'data/pilots/2026-11-17-self-recorded-r1'
 resultfile=source/'results.json';data=json.loads(resultfile.read_text())
 before=sha(resultfile)
 art={x['asset_id']:x for x in data['artworks']}
 ids=sorted(art,key=lambda s:int(s[1:]));assert len(ids)==100
 order=ids.copy();random.Random(SEED).shuffle(order)
 anchors=order[:4];rotating=order[4:];assert len(rotating)==96
 cases={(x['artwork_id'],x['video_id'],x['method']):x for x in data['cases']}
 assert len(cases)==400 and all(x['matches'] for x in cases.values())
 out.mkdir(parents=True);(out/'forms').mkdir();(out/'organizer').mkdir()
 experiment='frame-echo-diverse-review12-v3-20261118'
 allocations=[];forms=[]
 for n in range(12):
  reviewer=f'N{n+1:02d}';qid=f'Q{n+1:02d}';raw=[]
  for aid,(vid,base_method) in zip(anchors,CELLS):
   method=base_method if n%2==0 else METHODS[1-METHODS.index(base_method)]
   raw.append({'artwork_id':aid,'video_id':vid,'assigned_method':method,'role':'anchor'})
  slots=[cell for cell in CELLS for _ in range(2)]
  random.Random(SEED+100+n).shuffle(slots)
  for aid,(vid,method) in zip(rotating[n*8:(n+1)*8],slots):raw.append({'artwork_id':aid,'video_id':vid,'assigned_method':method,'role':'rotating'})
  random.Random(SEED+1000+n).shuffle(raw)
  assert len(raw)==12 and len({x['artwork_id'] for x in raw})==12
  assert Counter((x['video_id'],x['assigned_method']) for x in raw)==Counter({c:3 for c in CELLS})
  for i,x in enumerate(raw,1):x.update(questionnaire_id=qid,assigned_reviewer_id=reviewer,presentation_order=i)
  allocations.extend(raw)
  forms.append({'reviewer_id':reviewer,'questionnaire_id':qid,'relative_path':f'forms/{reviewer}.html','presentation_seed':SEED+1000+n,'artwork_ids':[x['artwork_id'] for x in raw]})
 assert len({frozenset(f['artwork_ids']) for f in forms})==12
 assert Counter(x['artwork_id'] for x in allocations)==Counter({**{x:12 for x in anchors},**{x:1 for x in rotating}})
 plan={'review_version':'v3-diverse-12','revision_date':'2026-11-18','created_at_utc':datetime.now(timezone.utc).isoformat(),'experiment_id':experiment,'source_experiment_id':data['experiment_id'],'source_results_sha256':before,
 'allocation_seed':SEED,'selection_rule':'Use a seeded permutation of all 100 numeric-sorted artwork IDs. First four are anchors; remaining 96 are partitioned into twelve disjoint rotating blocks of eight. Allocation uses IDs and seeds, not similarity scores, visual success or human ratings.',
 'timing_note':'Existing retrieval rankings were available before this questionnaire revision. The user had reported two earlier fixed-form respondents; their CSVs have not been received or inspected here. This is a new feedback design, not the original pre-ranking plan.',
 'anchor_artwork_ids':anchors,'anchor_base_video_method_cells':CELLS,'anchor_method_policy':'Fixed video per anchor; assigned method switches in alternating consecutive forms. Both methods are represented only when respondents actually complete both form parities.',
 'forms':forms,'allocations':allocations,'planned_form_count':12,'planned_presentations':144,'planned_unique_artworks':100,'actual_v3_responses_supplied':0,
 'per_form_counts':{'different_artworks':12,'anchors':4,'rotating':8,'per_video':6,'per_method':6,'per_video_method_cell':3},
 'interpretation':'Prepared capacity is not a participant count. Distinct artworks occur within each form; four anchors intentionally recur across forms. Anchor method contrasts are between people, not within-person judgements of both methods on the same artwork. Rotating items broaden exploratory coverage and are not the same controlled stimulus set across people.',
 'legacy_data_policy':'Keep earlier 20- and fixed12-pair pages and all raw exports unchanged. Treat pre-revision responses as a separate fixed-form cohort; the fixed12 common-item analysis plan does not automatically apply to v3. Preserve version, actual identities/codes, missingness and uncertainty. Do not pool versions as identical designs.'}
 dump(out/'organizer/allocation-plan.json',plan)
 allocation_hash=sha(out/'organizer/allocation-plan.json')
 cache={};keys=[];forms_summary=[]
 for form in forms:
  chosen=[x for x in allocations if x['questionnaire_id']==form['questionnaire_id']]
  items=[]
  for x in chosen:
   aid=x['artwork_id'];vid=x['video_id'];m=x['assigned_method'];a=art[aid]
   row=cases[aid,vid,m]['matches'][0]
   cid='C'+hashlib.sha256((data['experiment_id']+'|'+aid+'|'+vid+'|'+row['frame_sha256']).encode()).hexdigest()[:12]
   ap=source/a['normalized_path'];fp=source/row['frame_path']
   for path,digest in [(ap,a['normalized_sha256']),(fp,row['frame_sha256'])]:
    if str(path) not in cache:
     assert sha(path)==digest,'Source image changed';cache[str(path)]=uri(path)
   methods=[method for method in METHODS if cases[aid,vid,method]['matches'][0]['frame_sha256']==row['frame_sha256']]
   items.append({'candidate_id':cid,'artwork_id':aid,'artwork_title':a['title'],'artist':a['artist'],'video_id':vid,'frame_sha256':row['frame_sha256'],'presentation_order':x['presentation_order'],'canonical_timestamp':row['timestamp_seconds'],'reference_image':cache[str(ap)],'frame_image':cache[str(fp)]})
   keys.append({**x,'candidate_id':cid,'source_experiment_id':data['experiment_id'],'artwork_title':a['title'],'frame_sha256':row['frame_sha256'],'timestamp_seconds':row['timestamp_seconds'],'timestamp_label':row['timestamp_label'],'assigned_method_rank':1,'assigned_method_score':row['cosine_similarity'],'actual_top1_method_membership':';'.join(methods),'normalized_artwork_path':str(ap.relative_to(root)),'frame_path':str(fp.relative_to(root)),'same_artwork_visible':'unknown'})
  write_assigned_review_page(out/form['relative_path'],items,experiment,form['presentation_seed'],form['reviewer_id'],form['questionnaire_id'],data['experiment_id'])
  forms_summary.append({'questionnaire_id':form['questionnaire_id'],'reviewer_id':form['reviewer_id'],'path':form['relative_path'],'different_artworks':12,'anchor_artworks':';'.join(anchors),'rotating_artworks':';'.join(x['artwork_id'] for x in chosen if x['role']=='rotating'),'status':'prepared; not a collected response'})
 write_launcher(out/'index.html',forms)
 dump(out/'organizer/form-item-key.json',{'experiment_id':experiment,'review_version':'v3-diverse-12','allocation_plan_sha256':allocation_hash,'source_results_sha256':before,'forms':forms,'items':keys,'ratings_collected':0})
 csvout(out/'organizer/form-item-key.csv',keys)
 csvout(out/'organizer/forms.csv',forms_summary)
 csvout(out/'review-response-template.csv',[],['experiment_id','reviewer_id','candidate_id','artwork_id','video_id','frame_sha256','presentation_order','timestamp_seconds','colour','composition','content','overall','relevance','quality_flags','comment','completed','questionnaire_id','review_version','dataset_id','source_experiment_id'])
 assert sha(resultfile)==before
 summary={'prepared_questionnaires':12,'image_pairs_per_questionnaire':12,'distinct_artworks_per_questionnaire':12,'planned_artwork_coverage_if_all_forms_completed':100,'prepared_presentations':144,'actual_responses_generated':0,'source_retrieval_unchanged':True,'anchor_artwork_ids':anchors,'allocation_plan_sha256':allocation_hash,'prior_respondents_user_reported':2,'prior_response_files_inspected':False}
 dump(out/'summary.json',summary)
 print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
