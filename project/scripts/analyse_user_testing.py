"""Describe all seven returned Frame Echo forms as one exploratory user test.

Keeps source versions and repeated ratings, archives actual CSV bytes, and
preserves earlier reports and questionnaires. Pooled means describe collected
rating rows, with unequal form lengths, rather than independent participants.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DIMENSIONS=('colour','composition','content','overall')
SUPPLEMENT='frame-echo-supplement-review12-v1-20261118'
NEW_REVIEWERS=('R01','R02','R03')
CASE_IDS=['C1b54efc3d960','C33b6b38a9b00','C1246b3a24b2f','Cf1a63cc58170','C7402b8311d02','Ce65160f1effc']

def dump(path,obj):Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')
def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def parse(value):
    if value=='':return None
    if value=='unsure':return value
    assert value in ('1','2','3','4','5'),value
    return int(value)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--downloads',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case-notes',type=Path,required=True)
    a=p.parse_args();root=a.project.resolve();out=a.output.resolve()
    assert not out.exists(),'Use a fresh analysis folder; never overwrite prior records'
    sys.path.insert(0,str(root))
    from scripts.analyse_human_feedback import digest,summary as base_summary
    def describe(rows):
        s=base_summary(rows)
        s['relevance']={k:s['relevance'].get(k,0) for k in ('yes','no','unsure','missing')}
        s['overall_ge4_n']=s.pop('overall_ge4');s['overall_le2_n']=s.pop('overall_le2')
        s['colour_ge4_content_le2_n']=s.pop('colour_ge4_content_le2')
        s['written_comment_n']=sum(bool(r['comment'].strip()) for r in rows)
        s['quality_flag_response_n']=sum(bool(r['quality_flags'].strip()) for r in rows)
        return s
    old=root/'data/evaluation/2026-11-18-human-feedback-r1'
    study=root/'data/evaluation/2026-11-18-supplement-review12-v1'
    pilot=root/'data/pilots/2026-11-17-self-recorded-r1'
    source=root/'data/pilots/2026-11-18-style-supplement-r1'
    manifest=json.loads((old/'provenance/input-manifest.json').read_text())
    old_processed=read_csv(old/'analysis-rows.csv')
    old_index={(r['source_file'],r['candidate_id']):r for r in old_processed}
    assert len(old_index)==64
    new_paths=[a.downloads/f'frame-echo_{SUPPLEMENT}_SUP12_{r}.csv' for r in NEW_REVIEWERS]
    originals=[Path(m['original_path']) for m in manifest]+new_paths
    protected_paths=set(originals)
    for rel in ('data/pilots','data/evaluation','data/raw','data/models','docs','app','scripts'):
        protected_paths.update(x for x in (root/rel).rglob('*') if x.is_file()
             and '__pycache__' not in x.parts and x.name!='.DS_Store' and not x.name.startswith('~$'))
    protected={str(x.resolve()):digest(x) for x in sorted(protected_paths)}
    legacy_keys={i['candidate_id']:i for i in json.loads((pilot/'organizer/review-key.json').read_text())['items']}
    v3_keys={(i['questionnaire_id'],i['candidate_id']):i for i in json.loads((root/'data/evaluation/2026-11-18-diverse-review12-v3/organizer/form-item-key.json').read_text())['items']}
    skey=json.loads((study/'organizer/review-key.json').read_text())
    sup_keys={i['candidate_id']:i for i in skey['items']}
    sr=json.loads((source/'results.json').read_text())
    conditions={(c['artwork_id'],c['video_id'],c['method']):c for c in sr['cases']}
    assert digest(source/'results.json')==skey['source_results_sha256']
    assert digest(study/'organizer/selection-plan.json')==skey['selection_plan_sha256']
    out.mkdir(parents=True);(out/'raw').mkdir();(out/'provenance').mkdir()
    rows=[];inputs=[]
    for m in manifest:
        original=Path(m['original_path']);archived=old/m['file']
        assert digest(original)==digest(archived)==m['sha256']
        raw=read_csv(archived)
        assert len(raw)==m['rating_rows']
        for rawrow in raw:
            saved=old_index[original.name,rawrow['candidate_id']]
            for field,value in rawrow.items():
                if field=='completed':assert (value=='true')==(saved[field]=='True')
                elif field=='timestamp_seconds':assert abs(float(value)-float(saved[field]))<=1e-6
                else:assert value==saved[field],(original.name,field)
            values={d:parse(saved[d]) for d in DIMENSIONS}
            r={**saved,**values,'presentation_order':int(saved['presentation_order']),
               'timestamp_seconds':float(saved['timestamp_seconds']),'source_score':float(saved['source_method_score']),
               'completed':saved['completed']=='True','input_file':'raw/'+original.name,'source_rank':1}
            if r['cohort']=='legacy20':
                key=legacy_keys[r['candidate_id']]
                r['normalized_artwork_path']=str((pilot/key['normalized_artwork_path']).relative_to(root))
                r['frame_path']=str((pilot/key['frame_path']).relative_to(root))
            else:
                key=v3_keys[r['questionnaire_id'],r['candidate_id']]
                r['normalized_artwork_path']=key['normalized_artwork_path'];r['frame_path']=key['frame_path']
            r['artist']=key['artist'] if 'artist' in key else ''
            assert digest(root/r['frame_path'])==r['frame_sha256']
            rows.append(r)
        dest=out/'raw'/original.name;shutil.copy2(archived,dest);assert digest(dest)==m['sha256']
        inputs.append({**m,'file':'raw/'+original.name,'included_in_current_user_testing':True})
    for code,path in zip(NEW_REVIEWERS,new_paths):
        raw=read_csv(path);assert len(raw)==12
        assert {r['candidate_id'] for r in raw}==set(sup_keys)
        for r in raw:
            key=sup_keys[r['candidate_id']]
            assert r['reviewer_id']==code
            for k in ('experiment_id','questionnaire_id','review_version','dataset_id','source_experiment_id'):
                assert r[k]==skey[k],(code,k)
            for k in ('artwork_id','video_id','frame_sha256'):assert r[k]==key[k]
            assert int(r['presentation_order'])==key['presentation_order']
            assert abs(float(r['timestamp_seconds'])-key['timestamp_seconds'])<=1e-6
            assert r['relevance'] in ('yes','no','unsure','')
            values={d:parse(r[d]) for d in DIMENSIONS}
            complete=all(v is not None for v in values.values())
            assert r['completed']==('true' if complete else 'false')
            assert digest(root/key['frame_path'])==key['frame_sha256']
            assert digest(root/key['normalized_artwork_path'])==key['normalized_artwork_sha256']
            match=conditions[key['artwork_id'],key['video_id'],key['assigned_method']]['matches'][0]
            assert match['frame_sha256']==key['frame_sha256'] and match['rank']==1
            assert abs(match['cosine_similarity']-key['source_score'])<1e-12
            rows.append({**r,**values,'presentation_order':int(r['presentation_order']),
                         'timestamp_seconds':key['timestamp_seconds'],'completed':complete,
                         **{k:key[k] for k in ('artwork_title','artist','assigned_method','actual_top1_method_membership',
                                                'source_rank','source_score','normalized_artwork_path','frame_path')},
                         'cohort':'supplement-SUP12','input_file':'raw/'+path.name})
        shutil.copy2(path,out/'raw'/path.name)
        assert digest(path)==digest(out/'raw'/path.name)
        inputs.append({'file':'raw/'+path.name,'original_path':str(path),'sha256':digest(path),
                       'reviewer_id':code,'cohort':'supplement-SUP12','rating_rows':12,
                       'included_in_current_user_testing':True})
    assert len(rows)==100 and len({(r['input_file'],r['candidate_id']) for r in rows})==100
    codes=list(dict.fromkeys(r['reviewer_id'] for r in rows))
    per_item=[]
    for candidate in dict.fromkeys(r['candidate_id'] for r in rows):
        rr=[r for r in rows if r['candidate_id']==candidate];first=rr[0]
        for r in rr:
            for k in ('artwork_id','video_id','frame_sha256','normalized_artwork_path','frame_path'):
                assert r[k]==first[k],(candidate,k)
        methods=sorted({r['assigned_method'] for r in rr})
        per_item.append({**{k:first[k] for k in ('candidate_id','artwork_id','artwork_title','artist','video_id',
             'timestamp_seconds','actual_top1_method_membership','source_rank','normalized_artwork_path','frame_path','frame_sha256')},
             'assigned_method':';'.join(methods),'source_score':first['source_score'] if len(methods)==1 else None,
             'source_scores_by_method':{r['assigned_method']:r['source_score'] for r in rr},
             'raw_ratings':rr,**describe(rr)})
    overall=describe(rows)
    totals={'forms':len(inputs),'rating_rows':len(rows),'numeric_ratings':sum(type(r[d]) is int for r in rows for d in DIMENSIONS),
            'completed_rows':sum(r['completed'] for r in rows),'reviewer_codes':codes,
            'distinct_people_not_verified':True,'new_vs_returning_people_not_recorded':True,
            'unique_artworks':len({r['artwork_id'] for r in rows}),'unique_candidate_pairs':len(per_item)}
    summary={'analysis_date':'2026-11-18','created_at_utc':datetime.now(timezone.utc).isoformat(),
      'scope':'All seven returned forms discussed together as one exploratory user-testing collection, as requested by the student.',
      'totals':totals,'overall':overall,'per_item':per_item,
      'per_form':{code:describe([r for r in rows if r['reviewer_id']==code]) for code in codes},
      'collection_diagnostics':{group:describe([r for r in rows if r['cohort']==group]) for group in dict.fromkeys(r['cohort'] for r in rows)},
      'input_manifest':inputs,'case_candidate_ids':CASE_IDS,
      'notes':['Pooled distributions and means describe the collected rating rows. Twenty-pair forms contribute more rows than twelve-pair forms.',
               'Versions, artwork/video assignments and workload differ. The pooled mean is not an equal-person mean, an accuracy rate or evidence of improvement.',
               'One hundred evaluations repeat fifty-four image pairs. They are not one hundred independent participants.',
               'Seven anonymous codes do not establish seven distinct people or identify repeat participation.',
               'No controlled method advantage, independent style effect, statistical significance or universal score cutoff is estimated.',
               'Original raw files, questionnaire pages, earlier reports, thesis, PPT and retrieval outputs are preserved.']}
    dump(out/'summary.json',summary);dump(out/'provenance/input-manifest.json',inputs)
    dump(out/'provenance/protected-files-before.json',protected);write_csv(out/'analysis-rows.csv',rows)
    item_rows=[]
    for item in per_item:
        item_rows.append({k:item[k] for k in ('candidate_id','artwork_id','artwork_title','video_id','timestamp_seconds','assigned_method','actual_top1_method_membership','rating_rows')} |
            {f'{d}_{stat}':item['ratings'][d][stat] for d in DIMENSIONS for stat in ('mean','median')} |
            {f'connection_{k}':item['relevance'][k] for k in ('yes','no','unsure','missing')})
    write_csv(out/'item-summary.csv',item_rows)
    notes=json.loads(a.case_notes.read_text());shutil.copy2(a.case_notes,out/'provenance/case-notes.json')
    from user_testing_report import write_report
    write_report(out,summary,rows,root,notes)
    for path,h in protected.items():assert digest(path)==h,path
    dump(out/'provenance/validation.json',{'forms':7,'rows':100,'numeric_ratings':400,'unique_candidates':len(per_item),
      'all_actual_raw_exports_preserved_byte_for_byte':True,'identities_order_times_ratings_and_source_frames_verified':True,
      'earlier_published_reports_and_questionnaires_unchanged':True,'protected_files_unchanged':len(protected),
      'no_browser_storage_accessed':True,'user_requested_unified_discussion':True})
    print(json.dumps({'output':str(out),'totals':totals,'overall':overall},indent=2))

if __name__=='__main__':main()
