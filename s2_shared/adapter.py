"""TARGET CSV21 input adapter. No rankings, index thresholds, or condition membership."""
import argparse,base64,csv,hashlib,importlib.util,io,json,os,re,uuid
from decimal import Decimal,InvalidOperation
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter
from . import course_registry as registry
ROOT=Path(__file__).resolve().parent
OLD=ROOT/'data'
CORE_SHA='b7b1bbe72b1aadc726568ae7184635245e6fb93f52b4ad80bbe55468f6976d71'
EIGHT_SHA='06075d76e6c4924e8cae5097cdcac6826ca27251f4cf00b749577b0fbc35670d'
VERSION='csv21-adapter-1.0.0';SPEC='target-entry-csv21-v1';PROTOCOL='s2-csv21-input-record-v2'
INDEXES=('arms','arms2','tua','s','f','stable_finish_up')
VENUES={'01':('札幌','札'),'02':('函館','函'),'03':('福島','福'),'04':('新潟','新'),'05':('東京','東'),'06':('中山','中'),'07':('中京','名'),'08':('京都','京'),'09':('阪神','阪'),'10':('小倉','小')}
def sha(b):return hashlib.sha256(b).hexdigest()
if sha((ROOT/'storage.py').read_bytes())!=CORE_SHA:raise RuntimeError('pinned storage core changed')
from . import storage as core
encode=core.encode
def reference_manifest():
 b=(OLD/'manifest.json').read_bytes()
 if sha(b)!=EIGHT_SHA:raise ValueError('original 8-condition manifest changed')
 m=core.read_json(b)
 return {'protocol_id':PROTOCOL,'version':'2.0.0-input-only','input_spec':SPEC,'original_eight_manifest_sha256':EIGHT_SHA,'original_eight_manifest':m,'original_24_manifest_sha256':m['source_sha256'],'conditions_evaluated':False,'registry_version':registry.VERSION}
def convert_bytes(raw,metadata=None):
 errors=[]
 def err(line,code,field=None):errors.append({'line':line,'code':code,'field':field})
 if len(raw)>8*1024**2:raise ValueError('8MiB input limit')
 try:rows=list(csv.reader(io.StringIO(raw.decode('cp932'),newline=''),strict=True))
 except (UnicodeError,csv.Error) as e:return {'complete':False,'errors':[{'line':None,'code':'CP932_OR_CSV_ERROR','detail':str(e)}],'document':None}
 if not rows:err(0,'EMPTY_CSV')
 meta={'acquired_at':None,'time_basis':'unknown'}
 if metadata:
  if set(metadata)-{'acquired_at','time_basis'}:raise ValueError('metadata keys not allowed; no outcome fields')
  meta.update(metadata)
 if meta['time_basis'] not in ('unknown','operator_declared','machine_log_unreviewed'):raise ValueError('unknown time basis')
 if meta['acquired_at'] is not None:
  t=core.stamp(meta['acquired_at'])
  if t>datetime.now(timezone.utc):raise ValueError('acquisition timestamp in future')
  if meta['time_basis']=='unknown':raise ValueError('timestamp basis required')
 races={};seen=set();horse_ids=set();numbers=Counter();sire_present=0
 for line,r in enumerate(rows,1):
  if len(r)!=21:err(line,'COLUMN_COUNT',len(r));continue
  eid=r[15];hid=r[16]
  if not re.fullmatch(r'[0-9]{18}',eid):err(line,'ENTRY_ID_FORMAT');continue
  rid=eid[:16];date=rid[:8];code=rid[8:10]
  try:datetime.strptime(date,'%Y%m%d')
  except ValueError:err(line,'INVALID_DATE')
  if code not in VENUES:err(line,'UNKNOWN_VENUE');continue
  venue,abbr=VENUES[code]
  def integer(s,lo,hi,field):
   if not re.fullmatch('[0-9]+',s) or not lo<=int(s)<=hi:err(line,'INTEGER_RANGE',field);return None
   return int(s)
  race_no=integer(rid[14:16],1,12,'race_no');integer(rid[10:12],1,99,'meeting');integer(rid[12:14],1,99,'meeting_day')
  hn=integer(r[5].strip(),1,99,'horse_no');frame=integer(r[4].strip(),1,8,'frame');dist=integer(r[3].strip(),100,10000,'distance')
  label=registry.normalize(r[0]);valid_labels={abbr+str(race_no),venue+str(race_no)}
  if venue=='中京':valid_labels.add('中京'+str(race_no))
  if label not in valid_labels:err(line,'RACE_LABEL_ID_MISMATCH')
  if hn!=int(eid[-2:]):err(line,'HORSE_NUMBER_ID_MISMATCH')
  if eid in seen:err(line,'DUPLICATE_ENTRY_ID')
  seen.add(eid);numbers[rid,hn]+=1
  if numbers[rid,hn]>1:err(line,'DUPLICATE_HORSE_NUMBER')
  if not re.fullmatch('[0-9]{10}',hid):err(line,'HORSE_ID_FORMAT')
  if hid in horse_ids:err(line,'DUPLICATE_HORSE_ID')
  horse_ids.add(hid)
  if not r[7].strip():err(line,'HORSE_NAME_EMPTY')
  if not r[1].strip():err(line,'RACE_CONDITION_EMPTY')
  if r[2] not in ('芝','ダ'):err(line,'SURFACE_UNDEFINED')
  ix={}
  for k,val in zip(INDEXES,r[8:14]):
   state='observed';number=None
   try:
    if not val.strip():raise ValueError('blank')
    n=Decimal(val)
    if not n.is_finite():raise ValueError('nonfinite')
    number=str(n)
    if k=='stable_finish_up' and n not in tuple(map(Decimal,range(1,8))):state='scale_error';err(line,'FUP_SCALE',k)
   except (InvalidOperation,ValueError):state='blank' if not val.strip() else 'invalid';err(line,'INDEX_'+state.upper(),k)
   ix[k]={'raw_value':val,'decimal_exact':number,'state':state}
  if dist is None:continue
  kind=registry.race_kind(r[1],venue,r[2],dist)
  course=registry.course(r[20],venue,r[2],dist,kind['state'])
  if course['resolution_status'] in ('invalid','conflict'):err(line,'COURSE_'+course['resolution_status'].upper())
  if kind['state']=='conflict':err(line,'RACE_KIND_CONFLICT')
  signature=(r[1],r[2],dist,r[20])
  if rid not in races:
   races[rid]={'race_id':rid,'date':date,'venue':venue,'race_no':race_no,'condition_raw':r[1],'surface':r[2],'distance':dist,'course':course,'race_kind':kind,'registered_entry_ids':[],'horses':[],'acquired_at':meta['acquired_at'],'scheduled_start_at':None,'official_roster_checked':False,'coverage_basis':'TARGET_FULL_EXPORT_USER_DECLARED','_signature':signature}
  elif races[rid]['_signature']!=signature:err(line,'RACE_METADATA_CONFLICT')
  races[rid]['registered_entry_ids'].append(eid)
  races[rid]['horses'].append({'entry_id':eid,'horse_id':hid,'horse_no':hn,'horse_name_raw':r[7],'frame':frame,'source_line':line,'raw_columns':r,'indexes':ix,'planned_status':'unknown','acquired_at':meta['acquired_at']})
  sire_present+=bool(r[19].strip())
 for race in races.values():
  del race['_signature'];race['registered_count']=len(race['registered_entry_ids']);race['registered_set_sha256']=sha(encode(sorted(race['registered_entry_ids'])))
  race['input_state']='jump_recorded_out_of_scope' if race['race_kind']['state']=='jump' else 'flat_recorded' if race['race_kind']['state']=='flat' else 'race_kind_unconfirmed'
  if meta['acquired_at'] and core.stamp(meta['acquired_at']).astimezone(timezone(timedelta(hours=9))).strftime('%Y%m%d')>race['date']:err(None,'ACQUIRED_AFTER_RACE_DATE',race['race_id'])
 doc={'schema_version':'csv21-record-2.0','protocol_id':PROTOCOL,'input_spec_version':SPEC,'adapter_version':VERSION,'source':{'sha256':sha(raw),'bytes':len(raw),'encoding':'cp932','raw_base64':base64.b64encode(raw).decode('ascii')},'acquisition':meta,'time_status':'NOT_INDEPENDENTLY_VERIFIED','prospective_verified':False,'registry_version':registry.VERSION,'registry_sha256':sha(Path(registry.__file__).read_bytes()),'races':list(races.values()),'rows':len(rows),'sire_nonempty_rows':sire_present,'outer_counts':dict(Counter(r[20] for r in rows if len(r)==21)),'ranks_calculated':False,'conditions_evaluated':False}
 return {'complete':not errors,'errors':errors,'status':'INPUT_ARCHIVE_VALID_TIME_UNVERIFIED' if not errors else 'REJECTED_INVALID_INPUT','document':doc,'unconfirmed_race_ids':[r['race_id'] for r in doc['races'] if r['race_kind']['state']=='unconfirmed'],'prospective_ready':False}
def convert(path,metadata=None):return convert_bytes(Path(path).read_bytes(),metadata)
def capture(path,store,metadata=None):
 if Path(path).stat().st_size>8*1024**2:raise ValueError('8MiB input limit')
 result=convert(path,metadata)
 if not result['complete']:return {k:v for k,v in result.items() if k!='document'}
 m=reference_manifest();mb=encode(m);b=encode(result['document']);pin=sha(mb)
 store=Path(store).resolve()
 if not store.is_relative_to(ROOT):raise ValueError('new research folder only')
 store.mkdir(parents=True,exist_ok=True)
 identity={'input_sha256':sha(b),'manifest_sha256':pin,'protocol_id':PROTOCOL};sid=sha(encode(identity));dst=store/sid
 if dst.exists():verify(dst);raise FileExistsError('same input already archived: '+sid)
 stage=store/('.incomplete-'+uuid.uuid4().hex);stage.mkdir()
 validation={k:v for k,v in result.items() if k!='document'}
 record={'snapshot_id':sid,**identity,'source_csv_sha256':result['document']['source']['sha256'],'saved_at':core.now(),'input_acquired_at':result['document']['acquisition']['acquired_at'],'time_status':'NOT_INDEPENDENTLY_VERIFIED','prospective_verified':False,'adapter_version':VERSION,'adapter_sha256':sha(Path(__file__).read_bytes()),'storage_core_sha256':CORE_SHA,'evaluator_version':None,'settlement_version':None,'condition_results':None}
 payloads={'input.json':b,'manifest.json':mb,'validation.json':encode(validation),'record.json':encode(record)}
 for name,data in payloads.items():
  with (stage/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 with (stage/'integrity.json').open('xb') as f:f.write(encode({'files':{n:sha(v) for n,v in payloads.items()}}));f.flush();os.fsync(f.fileno())
 os.rename(stage,dst);receipt=sha((dst/'integrity.json').read_bytes());verify(dst,receipt)
 return {**validation,'snapshot_id':sid,'path':str(dst),'integrity_sha256':receipt}
def verify(folder,receipt=None):
 result=core.verify(folder,receipt);p=Path(folder);d=core.read_json((p/'input.json').read_bytes());m=core.read_json((p/'manifest.json').read_bytes());r=core.read_json((p/'record.json').read_bytes())
 if d.get('schema_version')!='csv21-record-2.0' or m!=reference_manifest():raise ValueError('contract/manifest mismatch')
 raw=base64.b64decode(d['source']['raw_base64'],validate=True)
 if sha(raw)!=d['source']['sha256'] or sha(raw)!=r['source_csv_sha256']:raise ValueError('original CSV mismatch')
 again=convert_bytes(raw,d['acquisition'])
 if not again['complete'] or encode(again['document'])!=encode(d):raise ValueError('conversion mismatch')
 return {**result,'source_csv_sha256':sha(raw),'conversion_verified':True,'prospective_verified':False}
def main():
 p=argparse.ArgumentParser(description='TARGET21列の研究入力保存のみ。順位・S2判定なし。');ss=p.add_subparsers(dest='command',required=True)
 v=ss.add_parser('inspect');v.add_argument('csv')
 c=ss.add_parser('capture');c.add_argument('csv');c.add_argument('store');c.add_argument('--metadata')
 v=ss.add_parser('verify');v.add_argument('snapshot');v.add_argument('--receipt')
 d=ss.add_parser('diff');d.add_argument('left');d.add_argument('right')
 a=p.parse_args()
 if a.command=='inspect':z=convert(a.csv);z={k:v for k,v in z.items() if k!='document'}
 elif a.command=='verify':z=verify(a.snapshot,a.receipt)
 elif a.command=='diff':verify(a.left);verify(a.right);z=core.compare(a.left,a.right)
 else:z=capture(a.csv,a.store,core.read_json(Path(a.metadata).read_bytes()) if a.metadata else None)
 print(json.dumps(z,ensure_ascii=False,indent=2))
 if isinstance(z,dict) and z.get('complete') is False:raise SystemExit(2)
if __name__=='__main__':main()
