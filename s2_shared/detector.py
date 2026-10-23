"""Portable binding of the pinned research detector; calculation functions unchanged."""
import hashlib,json,os,uuid
from collections import Counter
from decimal import Decimal,InvalidOperation
from pathlib import Path
from . import adapter as a
ROOT=Path(__file__).resolve().parent
FORMAL=ROOT/'data/formal24.json'
FORMAL_SHA='bf10b6d686ffa9a96ba0f48ce9229d4ed0d54fa4f2315038141e790c7fbab3c6'
EIGHT=ROOT/'data/manifest.json'
EIGHT_SHA='06075d76e6c4924e8cae5097cdcac6826ca27251f4cf00b749577b0fbc35670d'
NUMBERS=(22,18,17,1,2,3,4,8);VERSION='s2-fixed8-decimal-1.0.0'
encode=a.encode

def sha(b):return hashlib.sha256(b).hexdigest()

def definitions(path=FORMAL,expected_sha=FORMAL_SHA):
 raw=Path(path).read_bytes()
 if sha(raw)!=expected_sha:raise ValueError('formal manifest SHA256 mismatch')
 if sha(EIGHT.read_bytes())!=EIGHT_SHA:raise ValueError('8-condition reference changed')
 m=json.loads(raw.decode('utf-8'),parse_float=Decimal);eight=json.loads(EIGHT.read_text(encoding='utf-8'))
 out=[]
 for no in NUMBERS:
  found=[p for p in m['pairs'] if p['sequence']==no]
  if len(found)!=1:raise ValueError('definition not unique: '+str(no))
  p=found[0];ref=next(x for x in eight['conditions'] if x['number']==no)
  if p['fixed_id']!=ref['condition_id'] or p['scope']!=ref['original_pair']['scope']:raise ValueError('reference definition mismatch')
  rank=ref['rank_contract']
  if rank!={'population':'all_registered_nonmissing_per_index','order':'descending','ties':'RANK_min_competition','min':1,'max':3}:raise ValueError('rank contract changed')
  parents={}
  for side in ('a','b'):
   x=p[side];threshold=x['threshold'];decimal_text=None if threshold is None else str(threshold)
   if x['code'] not in a.INDEXES or x['model'] not in ('A','B','C') or x['scope']!=p['scope']:raise ValueError('unsupported formal parent')
   if decimal_text!=ref['threshold_decimal'][side]:raise ValueError('exact threshold mismatch')
   if (x['model']=='A')!=(threshold is None):raise ValueError('model threshold mismatch')
   parents[side]={'code':x['code'],'model':x['model'],'rank_min':1,'rank_max':3,'rank_operator':'<=','value_operator':None if threshold is None else '>=','threshold':decimal_text,'candidate_id':x['candidate_id']}
  out.append({'number':no,'condition_id':p['fixed_id'],'scope':p['scope'],'parents':parents,'historical_periods_reference_only':p['periods'],'historical_period_family':p['period_family']})
 return out

def ranks(race):
 """All registered CSV rows before scope, validity intersection or AND."""
 out={}
 for code in a.INDEXES:
  values=[];bad=[]
  for h in race['horses']:
   v=h.get('indexes',{}).get(code)
   try:
    if not v or v.get('state')!='observed':raise ValueError()
    n=Decimal(v['raw_value'])
    if not n.is_finite():raise ValueError()
    values.append((h['entry_id'],n))
   except (ValueError,InvalidOperation,TypeError):bad.append(h['entry_id'])
  if bad:
   out[code]={'valid':False,'reason':'registered_index_invalid_ranking_incomplete','invalid_entry_ids':bad,'entries':{h['entry_id']:{'rank':None,'tie_size':None} for h in race['horses']}};continue
  ordered=sorted(values,key=lambda v:v[1],reverse=True);counts=Counter(v for _,v in ordered);entries={};prev=None;rank=None
  for pos,(eid,val) in enumerate(ordered,1):
   if pos==1 or val!=prev:rank=pos
   entries[eid]={'rank':rank,'tie_size':counts[val]};prev=val
  out[code]={'valid':True,'reason':None,'invalid_entry_ids':[],'entries':entries}
 return out

def scope_status(race,definition):
 kind=race['race_kind']['state']
 if kind=='jump':return 'OUT_OF_SCOPE','jump_race'
 if kind=='conflict':return 'INVALID_INPUT','race_kind_conflict'
 if kind!='flat':return 'UNCONFIRMED','race_kind_unconfirmed'
 s=definition['scope']
 if s[1]=='surface':
  return ('READY',None) if race['surface']==s[2] else ('OUT_OF_SCOPE','surface_outside_scope')
 if s[1]!='course':return 'UNCONFIRMED','unsupported_scope_definition'
 if (race['venue'],race['surface'],race['distance'])!=tuple(s[2:5]):return 'OUT_OF_SCOPE','venue_surface_distance_outside_scope'
 c=race['course']
 if c['resolution_status'] in ('invalid','conflict'):return 'INVALID_INPUT','course_metadata_invalid'
 if c['resolution_status']!='confirmed' or c.get('resolved') is None:return 'UNCONFIRMED','physical_course_unconfirmed'
 if s[5]=='内' and c['resolved']!='内':return 'OUT_OF_SCOPE','inner_course_required'
 if s[5] not in ('内','UNKNOWN'):return 'UNCONFIRMED','unsupported_historical_course_key'
 if c.get('historical_key')!=s[5] or not c.get('bridge_rule_id'):return 'UNCONFIRMED','historical_course_bridge_unconfirmed'
 return 'READY',None

def parent_pass(raw,rank,parent):
 return parent['rank_min']<=rank<=parent['rank_max'] and (parent['threshold'] is None or Decimal(raw)>=Decimal(parent['threshold']))

def evaluate_document(doc,defs=None,provenance=None):
 """Internal pure calculation. Public entry points verify snapshots/conversion first."""
 defs=definitions() if defs is None else defs
 if [d['number'] for d in defs]!=list(NUMBERS):raise ValueError('only approved fixed eight definitions allowed')
 rr=[];hh=[];rank_rows=[];unique={}
 for race in doc['races']:
  ranked=ranks(race)
  for h in race['horses']:
   rank_rows.append({'race_id':race['race_id'],'entry_id':h['entry_id'],'indexes':{code:{'raw_value':h.get('indexes',{}).get(code,{}).get('raw_value'),'valid_population':ranked[code]['valid'],**ranked[code]['entries'][h['entry_id']]} for code in a.INDEXES}})
  for d in defs:
   state,reason=scope_status(race,d)
   if state=='READY':
    bad=[p['code'] for p in d['parents'].values() if not ranked[p['code']]['valid']]
    if bad:state='INVALID_INPUT';reason='invalid_required_rank_population:'+','.join(bad)
   evaluated=state=='READY';matched=0
   for h in race['horses']:
    details={}
    for side,p in d['parents'].items():
     code=p['code'];raw=h.get('indexes',{}).get(code,{}).get('raw_value');rk=ranked[code]['entries'][h['entry_id']]['rank']
     details[side]={'index_code':code,'model':p['model'],'raw_value':raw,'rank':rk,'rank_min':p['rank_min'],'rank_max':p['rank_max'],'threshold':p['threshold'],'operator':p['value_operator'],'passed':parent_pass(raw,rk,p) if evaluated else None}
    passed=all(x['passed'] is True for x in details.values()) if evaluated else None
    hs=('MATCH' if passed else 'NO_MATCH') if evaluated else state
    matched+=int(passed is True)
    hh.append({'race_id':race['race_id'],'entry_id':h['entry_id'],'horse_id':h['horse_id'],'horse_no':h['horse_no'],'horse_name_raw':h['horse_name_raw'],'condition_number':d['number'],'condition_id':d['condition_id'],'parents':details,'state':hs,'and_passed':passed,'reason':reason})
    if passed:
     if h['entry_id'] not in unique:unique[h['entry_id']]={'entry_id':h['entry_id'],'race_id':race['race_id'],'horse_id':h['horse_id'],'horse_no':h['horse_no'],'horse_name_raw':h['horse_name_raw'],'condition_numbers':[],'condition_ids':[]}
     unique[h['entry_id']]['condition_numbers'].append(d['number']);unique[h['entry_id']]['condition_ids'].append(d['condition_id'])
   rr.append({'race_id':race['race_id'],'date':race['date'],'venue':race['venue'],'race_no':race['race_no'],'surface':race['surface'],'distance':race['distance'],'race_kind':race['race_kind']['state'],'physical_course':race['course'].get('resolved'),'historical_course_key':race['course'].get('historical_key'),'condition_number':d['number'],'condition_id':d['condition_id'],'state':('MATCH' if matched else 'NO_MATCH') if evaluated else state,'evaluated':evaluated,'all_registered_horses':len(race['horses']),'matched_count':matched if evaluated else None,'reason':reason})
 summaries=[]
 for d in defs:
  rs=[r for r in rr if r['condition_number']==d['number']];hs=[h for h in hh if h['condition_number']==d['number']]
  summaries.append({'number':d['number'],'condition_id':d['condition_id'],'evaluated_races':sum(r['evaluated'] for r in rs),'matched_races':sum(r['state']=='MATCH' for r in rs),'zero_match_races':sum(r['state']=='NO_MATCH' for r in rs),'out_of_scope_races':sum(r['state']=='OUT_OF_SCOPE' for r in rs),'unconfirmed_races':sum(r['state']=='UNCONFIRMED' for r in rs),'invalid_races':sum(r['state']=='INVALID_INPUT' for r in rs),'matched_horses':sum(h['state']=='MATCH' for h in hs),'no_match_horses':sum(h['state']=='NO_MATCH' for h in hs),'unconfirmed_horses':sum(h['state']=='UNCONFIRMED' for h in hs),'invalid_horses':sum(h['state']=='INVALID_INPUT' for h in hs)})
 return {'schema':'fixed8-research-result-1.0','run_kind':'retrospective_test','detector_version':VERSION,'prospective_ready':False,'prospective_verified':False,'provenance':provenance or {},'definitions':defs,'summary':summaries,'race_conditions':rr,'horse_conditions':hh,'all_registered_ranks':rank_rows,'unique_matches':list(unique.values()),'unique_matched_horses':len(unique),'future_window_status':'NOT_STARTED','historical_windows_are_provenance_not_input_date_filters':True}

def evaluate_snapshot(folder,expected_receipt=None):
 folder=Path(folder);a.verify(folder,expected_receipt);doc=a.core.read_json((folder/'input.json').read_bytes())
 prov={'input_csv_sha256':doc['source']['sha256'],'input_snapshot_id':folder.name,'input_snapshot_sha256':sha((folder/'integrity.json').read_bytes()),'input_json_sha256':sha((folder/'input.json').read_bytes()),'formal_manifest_path':str(FORMAL),'formal_manifest_sha256':FORMAL_SHA,'eight_manifest_sha256':EIGHT_SHA,'input_adapter_version':doc['adapter_version'],'metadata_registry_version':doc['registry_version']}
 return evaluate_document(doc,provenance=prov)

def archive_csv(csv_path,store):
 """New-folder wrapper for unchanged adapter contract; never write to old ROOT."""
 converted=a.convert(csv_path)
 if not converted['complete']:return None,converted
 store=Path(store).resolve()
 if not store.is_relative_to(ROOT):raise ValueError('new research directory only')
 store.mkdir(parents=True,exist_ok=True);m=a.reference_manifest();mb=encode(m);b=encode(converted['document'])
 identity={'input_sha256':sha(b),'manifest_sha256':sha(mb),'protocol_id':a.PROTOCOL};sid=sha(encode(identity));dst=store/sid
 if dst.exists():a.verify(dst);return dst,{'reused_existing_verified_snapshot':True}
 stage=store/('.incomplete-'+uuid.uuid4().hex);stage.mkdir()
 record={'snapshot_id':sid,**identity,'source_csv_sha256':converted['document']['source']['sha256'],'saved_at':a.core.now(),'prospective_verified':False,'time_status':'NOT_INDEPENDENTLY_VERIFIED','adapter_version':a.VERSION,'recorder_version':VERSION,'condition_results':None}
 payload={'input.json':b,'manifest.json':mb,'validation.json':encode({k:v for k,v in converted.items() if k!='document'}),'record.json':encode(record)}
 for name,data in payload.items():
  with (stage/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 with (stage/'integrity.json').open('xb') as f:f.write(encode({'files':{k:sha(v) for k,v in payload.items()}}));f.flush();os.fsync(f.fileno())
 os.rename(stage,dst);a.verify(dst);return dst,{'created_new_input_archive':True}
