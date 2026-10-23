"""Research input integrity only. No ranking, condition evaluator, or settlement."""
import argparse,csv,hashlib,io,json,os,re,uuid
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
from pathlib import Path

VERSION='input8-1.0.0'
ROOT=Path(__file__).resolve().parent
CODES=('arms','arms2','tua','s','f','stable_finish_up')
VENUES={'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}
SHA=re.compile(r'[0-9a-f]{64}')
def digest(b):return hashlib.sha256(b).hexdigest()
def encode(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def now():return datetime.now(timezone.utc).isoformat()
def read_json(b):
 def unique(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('duplicate JSON key: '+k)
   d[k]=v
  return d
 return json.loads(b.decode('utf-8-sig'),object_pairs_hook=unique,parse_constant=lambda s:(_ for _ in ()).throw(ValueError(s)))
def stamp(s):
 if not isinstance(s,str):raise ValueError('timestamp absent')
 t=datetime.fromisoformat(s.replace('Z','+00:00'))
 if t.tzinfo is None:raise ValueError('timezone absent')
 return t
def locked_manifest():
 b=(ROOT/'manifest.json').read_bytes();pin=(ROOT/'manifest.sha256').read_text().strip()
 if digest(b)!=pin:raise ValueError('manifest lock mismatch')
 m=read_json(b)
 if m['status']!='DRAFT_INPUT_ONLY_NO_EVALUATION':raise ValueError('manifest status')
 return m,pin

def validate(d,m,at=None):
 """Return structural completeness, never S2 membership or computed ranks."""
 errors=[];warnings=[];at=at or datetime.now(timezone.utc)
 def error(path,code):errors.append({'path':path,'code':code})
 def fields(obj,required,path):
  if not isinstance(obj,dict):error(path,'OBJECT_REQUIRED');return False
  for k in sorted(set(required)-set(obj)):error(path+'.'+k,'MISSING_FIELD')
  for k in sorted(set(obj)-set(required)):error(path+'.'+k,'UNEXPECTED_FIELD_POSTRACE_NOT_ALLOWED')
  return True
 def timefield(v,path):
  try:
   t=stamp(v)
   if t>at:error(path,'FUTURE_ACQUISITION_TIMESTAMP')
   return t
  except (ValueError,TypeError,OverflowError):error(path,'TIME_UNKNOWN_OR_NO_TIMEZONE');return None
 def source(v,path):
  if not fields(v,('name','sha256','acquired_at','time_basis'),path):return None
  if not isinstance(v.get('name'),str) or not v.get('name','').strip():error(path,'SOURCE_NAME_MISSING')
  if not isinstance(v.get('sha256'),str) or not SHA.fullmatch(v['sha256']):error(path,'SOURCE_HASH_INVALID')
  if v.get('time_basis') not in ('operator_declared','machine_log_unreviewed'):error(path,'TIME_BASIS_UNSUPPORTED')
  return timefield(v.get('acquired_at'),path+'.acquired_at')
 if not fields(d,('schema_version','protocol_id','acquired_at','source','races'),'input'):
  return {'complete':False,'errors':errors,'warnings':warnings,'prospective_ready':False}
 if d.get('schema_version')!='1.0':error('schema_version','UNSUPPORTED_VERSION')
 if d.get('protocol_id')!=m['protocol_id']:error('protocol_id','PROTOCOL_MISMATCH')
 acquired=timefield(d.get('acquired_at'),'acquired_at');st=source(d.get('source'),'source')
 if st and acquired and st>acquired:error('source','SOURCE_AFTER_INPUT_ACQUISITION')
 races=d.get('races');seen_races=set();seen_ids=set();seen_horses=set();missing={c:0 for c in CODES}
 if not isinstance(races,list) or not races:error('races','NONEMPTY_ARRAY_REQUIRED');races=[]
 for ri,r in enumerate(races):
  p=f'races[{ri}]'
  if not fields(r,('race_id','date','venue','race_no','surface','distance','course_variant','course_source','race_kind','scheduled_start_at','acquired_at','roster','horses'),p):continue
  rid=r.get('race_id');validid=isinstance(rid,str) and re.fullmatch(r'\d{16}',rid)
  if not validid:error(p,'RACE_ID_INVALID')
  else:
   if rid in seen_races:error(p,'DUPLICATE_RACE_ID')
   seen_races.add(rid)
   try:datetime.strptime(rid[:8],'%Y%m%d')
   except ValueError:error(p,'RACE_DATE_INVALID')
   if r.get('date')!=rid[:8] or r.get('venue')!=VENUES.get(rid[8:10]) or type(r.get('race_no')) is not int or r['race_no']!=int(rid[14:16]) or not 1<=int(rid[14:16])<=12 or int(rid[10:12])<1 or int(rid[12:14])<1:error(p,'RACE_METADATA_ID_MISMATCH')
  if r.get('surface') not in ('芝','ダ'):error(p,'SURFACE_UNKNOWN')
  if type(r.get('distance')) is not int or not 100<=r['distance']<=10000:error(p,'DISTANCE_INVALID')
  if r.get('course_variant') not in ('内','外','直線','単一'):error(p,'COURSE_VARIANT_UNKNOWN')
  cs=source(r.get('course_source'),p+'.course_source')
  if r.get('race_kind')!='flat':error(p,'JUMP_OR_UNKNOWN_NOT_SUPPORTED_IN_PRE_RACE_PROTOCOL')
  rt=timefield(r.get('acquired_at'),p+'.acquired_at')
  try:
   off=stamp(r.get('scheduled_start_at'))
   if validid and off.astimezone(timezone(timedelta(hours=9))).strftime('%Y%m%d')!=rid[:8]:error(p,'SCHEDULE_DATE_MISMATCH')
   if rt and rt>=off:error(p,'RACE_ACQUIRED_NOT_BEFORE_OFF')
   if acquired and acquired>=off:error(p,'INPUT_ACQUIRED_NOT_BEFORE_OFF')
   if at>=off:error(p,'SAVE_NOT_BEFORE_OFF')
  except (ValueError,TypeError):error(p,'SCHEDULE_UNKNOWN');off=None
  if rt and acquired and rt>acquired:error(p,'RACE_AFTER_INPUT_ACQUISITION')
  if cs and rt and cs>rt:error(p,'COURSE_AFTER_RACE_ACQUISITION')
  roster=r.get('roster');expected=[]
  if fields(roster,('registered_entry_ids','registered_count','source'),p+'.roster'):
   roster_time=source(roster.get('source'),p+'.roster.source');expected=roster.get('registered_entry_ids')
   if roster_time and rt and roster_time>rt:error(p,'ROSTER_AFTER_RACE_ACQUISITION')
   if not isinstance(expected,list) or not all(isinstance(x,str) and re.fullmatch(r'\d{18}',x) and validid and x[:16]==rid and 1<=int(x[-2:])<=99 for x in expected):error(p,'ROSTER_IDS_INVALID');expected=[]
   if len(expected)!=len(set(expected)):error(p,'DUPLICATE_ROSTER_ID')
   if type(roster.get('registered_count')) is not int or roster['registered_count']!=len(expected) or not expected:error(p,'ROSTER_COUNT_MISMATCH')
  horses=r.get('horses');entries=[]
  if not isinstance(horses,list) or not horses:error(p,'HORSES_REQUIRED');horses=[]
  for hi,h in enumerate(horses):
   q=p+f'.horses[{hi}]'
   if not fields(h,('entry_id','horse_id','horse_no','horse_name','planned_status','acquired_at','indexes'),q):continue
   eid=h.get('entry_id');hid=h.get('horse_id')
   if not isinstance(eid,str) or not re.fullmatch(r'\d{18}',eid):error(q,'ENTRY_ID_INVALID')
   else:
    entries.append(eid)
    if eid in seen_ids:error(q,'DUPLICATE_ENTRY_ID')
    seen_ids.add(eid)
    if eid[:16]!=rid or type(h.get('horse_no')) is not int or not 1<=h['horse_no']<=99 or h['horse_no']!=int(eid[-2:]):error(q,'ENTRY_RACE_OR_HORSE_NUMBER_MISMATCH')
   if not isinstance(hid,str) or not re.fullmatch(r'\d{10}',hid):error(q,'HORSE_ID_INVALID')
   elif hid in seen_horses:error(q,'DUPLICATE_HORSE_ID')
   else:seen_horses.add(hid)
   if not isinstance(h.get('horse_name'),str) or not h.get('horse_name','').strip():error(q,'HORSE_NAME_REQUIRED')
   if h.get('planned_status') not in ('registered','withdrawn','excluded'):error(q,'PLANNED_STATUS_UNKNOWN')
   ht=timefield(h.get('acquired_at'),q+'.acquired_at')
   if ht and rt and ht>rt:error(q,'HORSE_AFTER_RACE_ACQUISITION')
   idx=h.get('indexes')
   if not fields(idx,CODES,q+'.indexes'):continue
   for code in CODES:
    v=idx.get(code);z=q+'.indexes.'+code
    if not fields(v,('raw_value','missing','source'),z):continue
    it=source(v.get('source'),z+'.source')
    if it and ht and it>ht:error(z,'INDEX_AFTER_HORSE_ACQUISITION')
    if type(v.get('missing')) is not bool:error(z,'MISSING_FLAG_REQUIRED');continue
    raw=v.get('raw_value')
    if v['missing']:
     missing[code]+=1
     if raw is not None:error(z,'MISSING_VALUE_MUST_BE_NULL')
    else:
     try:
      if not isinstance(raw,str) or not raw.strip():raise ValueError()
      n=Decimal(raw)
      if not n.is_finite():raise ValueError()
      if code=='stable_finish_up' and n not in tuple(map(Decimal,range(1,8))):error(z,'FUP_ORDINAL_NOT_1_TO_7')
     except (InvalidOperation,ValueError,TypeError):error(z,'OBSERVED_RAW_VALUE_REQUIRED_NO_ZERO_IMPUTATION')
  if CounterSafe(entries)!=CounterSafe(expected):error(p,'REGISTERED_ENTRY_SET_MISMATCH')
 warnings.append('取得日時・原本完全性は入力元の申告。ハッシュ一致だけでは発走前取得の独立証明にならない。')
 if any(missing.values()):warnings.append('欠損状態は保存可能。将来の判定可否は条件別に扱い、欠損を0補完しない。')
 return {'complete':not errors,'status':'STRUCTURALLY_COMPLETE_TIME_UNVERIFIED' if not errors else 'REJECTED_INCOMPLETE','errors':errors,'warnings':warnings,'time_status':'NOT_INDEPENDENTLY_VERIFIED','prospective_ready':False,'race_count':len(races),'entry_count':len(seen_ids),'known_missing_counts':missing,'ranks_calculated':False,'conditions_evaluated':False}

def CounterSafe(items):
 from collections import Counter
 return Counter(items)

def inspect_web(path):
 b=Path(path).read_bytes();rr=list(csv.reader(io.StringIO(b.decode('utf-8-sig')),strict=True));head=rr[0];rows=rr[1:]
 if len(set(head))!=len(head) or any(len(r)!=len(head) for r in rows):raise ValueError('CSV schema mismatch')
 mapping={'arms':'arms','arms2':'arms2','tua':'TUA','s':'S','f':'F','stable_finish_up':'厩舎F-UP2'}
 return {'input_sha256':digest(b),'rows':len(rows),'header':head,'available_index_columns':{c:n in head for c,n in mapping.items()},'status':'REFERENCE_ONLY_NOT_CANONICAL_INPUT','missing_contract':['平地障害区分','独立した芝ダート距離コース情報','全登録馬集合と原本識別','予定状態','取得日時と版','原欠損状態','発走予定日時'],'snapshot_created':False,'conditions_evaluated':False}

def capture(input_path,store,manifest=None,at=None):
 m,pin=locked_manifest() if manifest is None else manifest
 if Path(input_path).stat().st_size>8*1024**2:raise ValueError('input exceeds 8MiB safety bound')
 b=Path(input_path).read_bytes();d=read_json(b);v=validate(d,m,at)
 result={'validation':v,'input_sha256':digest(b),'manifest_sha256':pin}
 if not v['complete']:return result
 store=Path(store).resolve()
 if not store.is_relative_to(Path(__file__).resolve().parent):raise ValueError('store must remain in this new research folder')
 store.mkdir(parents=True,exist_ok=True)
 identity={'input_sha256':digest(b),'manifest_sha256':pin,'protocol_id':m['protocol_id']};sid=digest(encode(identity));dst=store/sid
 if dst.exists():
  verify(dst);raise FileExistsError('same input already fixed; no overwrite: '+sid)
 stage=store/('.incomplete-'+uuid.uuid4().hex);stage.mkdir()
 payloads={'input.json':b,'manifest.json':encode(m),'validation.json':encode(v),'record.json':encode({'snapshot_id':sid,**identity,'manifest_version':m['version'],'saved_at':now(),'input_acquired_at':d['acquired_at'],'input_recorder_version':VERSION,'input_recorder_sha256':digest(Path(__file__).read_bytes()),'condition_ids':[x['condition_id'] for x in m['conditions']],'condition_results':None,'evaluator_version':None,'settlement_version':None,'postrace_region':'separate_store_not_implemented'})}
 for name,data in payloads.items():
  with (stage/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 integrity={'files':{k:digest(v) for k,v in payloads.items()}}
 with (stage/'integrity.json').open('xb') as f:f.write(encode(integrity));f.flush();os.fsync(f.fileno())
 # Windows rename does not replace an existing destination. Partial writes stay quarantined.
 os.rename(stage,dst)
 result.update(snapshot_id=sid,path=str(dst),integrity_sha256=digest((dst/'integrity.json').read_bytes()))
 verify(dst,expected_integrity_sha256=result['integrity_sha256'])
 return result

def verify(folder,expected_integrity_sha256=None):
 p=Path(folder);integrity_bytes=(p/'integrity.json').read_bytes()
 if expected_integrity_sha256 and digest(integrity_bytes)!=expected_integrity_sha256:raise ValueError('external integrity receipt mismatch')
 i=read_json(integrity_bytes);expected={'input.json','manifest.json','validation.json','record.json'}
 if set(i.get('files',{}))!=expected or {x.name for x in p.iterdir()}!=expected|{'integrity.json'}:raise ValueError('unexpected/missing snapshot files')
 for name,h in i['files'].items():
  if digest((p/name).read_bytes())!=h:raise ValueError('snapshot modified: '+name)
 r=read_json((p/'record.json').read_bytes());m=read_json((p/'manifest.json').read_bytes())
 if digest((p/'input.json').read_bytes())!=r['input_sha256'] or digest((p/'manifest.json').read_bytes())!=r['manifest_sha256']:raise ValueError('snapshot identity mismatch')
 identity={k:r[k] for k in ('input_sha256','manifest_sha256','protocol_id')}
 if digest(encode(identity))!=p.name or r['snapshot_id']!=p.name or r['protocol_id']!=m['protocol_id']:raise ValueError('snapshot directory mismatch')
 return {'verified':True,'snapshot_id':p.name,'integrity_sha256':digest(integrity_bytes),'authentication':'local hash detection only; keep external receipt separately'}

def compare(left,right):
 verify(left);verify(right)
 a=read_json((Path(left)/'input.json').read_bytes());b=read_json((Path(right)/'input.json').read_bytes())
 def flatten(x,path=''):
  if isinstance(x,dict):return {k:v for key,val in x.items() for k,v in flatten(val,path+'/'+key).items()}
  if isinstance(x,list):return {k:v for n,val in enumerate(x) for k,v in flatten(val,path+'/'+str(n)).items()}
  return {path:x}
 x,y=flatten(a),flatten(b)
 return [{'path':k,'before':x.get(k),'after':y.get(k),'before_exists':k in x,'after_exists':k in y} for k in sorted(x.keys()|y.keys()) if k not in x or k not in y or x[k]!=y[k]]

def main():
 p=argparse.ArgumentParser(description='研究用入力保存のみ。S2判定機能なし。');sub=p.add_subparsers(dest='cmd',required=True)
 q=sub.add_parser('validate');q.add_argument('input')
 q=sub.add_parser('capture');q.add_argument('input');q.add_argument('store')
 q=sub.add_parser('verify');q.add_argument('snapshot');q.add_argument('--receipt')
 q=sub.add_parser('diff');q.add_argument('left');q.add_argument('right')
 q=sub.add_parser('inspect-web');q.add_argument('csv')
 a=p.parse_args()
 if a.cmd=='inspect-web':result=inspect_web(a.csv)
 elif a.cmd=='verify':result=verify(a.snapshot,a.receipt)
 elif a.cmd=='diff':result=compare(a.left,a.right)
 elif a.cmd=='capture':result=capture(a.input,a.store)
 else:result=validate(read_json(Path(a.input).read_bytes()),locked_manifest()[0])
 print(json.dumps(result,ensure_ascii=False,indent=2))
 if isinstance(result,dict) and ((result.get('validation') or result).get('complete') is False):raise SystemExit(2)
if __name__=='__main__':main()
