"""Metadata rules only. No index/rank/AND predicates."""
import re,unicodedata
VERSION='csv21-course-kind-1.0.0'
SOURCES={v:'https://www.jra.go.jp/facilities/race/'+e+'/course/' for v,e in [('東京','tokyo'),('中山','nakayama'),('阪神','hanshin'),('中京','chukyo'),('小倉','kokura'),('京都','kyoto'),('新潟','niigata')]}
# Limited, explicit registry: unlisted combinations remain unconfirmed.
FLAT={
 ('東京','芝'):{1400,1600,1800,2000,2300,2400,2500,2600,3400},
 ('東京','ダ'):{1200,1300,1400,1600,2100,2400},
 ('京都','芝'):{1100,1200,1400,1600,1800,2000,2200,2400,3000,3200},
 ('京都','ダ'):{1000,1100,1200,1400,1800,1900,2600},
 ('新潟','芝'):{1000,1200,1400,1600,1800,2000,2200,2400,3000,3200},
 ('新潟','ダ'):{1000,1200,1700,1800,2500},
 ('中山','芝'):{1800},('阪神','芝'):{2000,3000},('中京','芝'):{2000,3000},('小倉','芝'):{1800}}
JUMP={('東京','芝'):{3110,3300},('東京','ダ'):{3000,3100,3300},('京都','芝'):{3170,3180,3930},('京都','ダ'):{2910,3170,3760},('新潟','芝'):{2850,2890,3250,3290},('阪神','芝'):{3000,3140,3800,3900},('中京','芝'):{3000}}
ROUTES={('東京','芝',d):('単一',) for d in FLAT[('東京','芝')]}
for d in (1100,1200):ROUTES['京都','芝',d]=('内',)
for d in (1400,1600,2000):ROUTES['京都','芝',d]=('内','外')
for d in (1800,2200,2400,3000,3200):ROUTES['京都','芝',d]=('外',)
ROUTES['新潟','芝',1000]=('直線',)
for d in (1200,2200,2400):ROUTES['新潟','芝',d]=('内',)
for d in (1400,2000):ROUTES['新潟','芝',d]=('内','外')
for d in (1600,1800,3000,3200):ROUTES['新潟','芝',d]=('外',)
ROUTES.update({('中山','芝',1800):('内',),('阪神','芝',2000):('内',),('中京','芝',2000):('単一',),('小倉','芝',1800):('単一',)})
# Original historical keys are retained; these are representation bridges, not predicates.
BRIDGES={('東京','芝',2000):'UNKNOWN',('中山','芝',1800):'UNKNOWN',('阪神','芝',2000):'内',('中京','芝',2000):'UNKNOWN',('小倉','芝',1800):'UNKNOWN'}
JG=re.compile(r'(?<![A-Z0-9])J[・.\-]?G(?:III|II|I|[123])(?![A-Z0-9IV])')
def normalize(text):return re.sub(r'\s+','',unicodedata.normalize('NFKC',text).upper())
def race_kind(label,venue,surface,distance):
 n=normalize(label);flat=distance in FLAT.get((venue,surface),set());jump=distance in JUMP.get((venue,surface),set())
 explicit='障害' in n or bool(JG.search(n))
 if explicit:
  return {'state':'conflict' if flat and not jump else 'jump','reason':'explicit_jump_label','normalized_label':n,'registry_version':VERSION}
 if jump and not flat:return {'state':'jump','reason':'listed_jump_only_distance','normalized_label':n,'registry_version':VERSION}
 if flat and not jump:return {'state':'flat','reason':'listed_flat_only_distance','normalized_label':n,'registry_version':VERSION}
 # No bare J, no default-flat, and no assumption that the registry is exhaustive.
 return {'state':'unconfirmed','reason':'shared_distance_or_unlisted_combination','normalized_label':n,'registry_version':VERSION}
def course(outer_raw,venue,surface,distance,kind):
 token=outer_raw.strip();state='OUTER' if token=='外' else 'NOT_SPECIFIED_AS_OUTER' if token=='' else 'UNDEFINED'
 out={'csv_outer_raw':outer_raw,'csv_outer_state':state,'resolved':None,'resolution_status':'unconfirmed','registry_version':VERSION,'source':SOURCES.get(venue),'historical_key':None,'bridge_rule_id':None}
 if state=='UNDEFINED':out['resolution_status']='invalid';return out
 if kind!='flat':return out
 if surface=='ダ':
  out.update(resolved='NOT_APPLICABLE' if state!='OUTER' else None,resolution_status='confirmed' if state!='OUTER' else 'conflict');return out
 routes=ROUTES.get((venue,surface,distance))
 if routes:
  selected='外' if state=='OUTER' else next((r for r in routes if r!='外'),None)
  if selected is None or selected not in routes:out['resolution_status']='conflict';return out
  out.update(resolved=selected,resolution_status='confirmed')
 else:
  if state=='OUTER':out['resolved']='外';out['resolution_status']='explicit_outer_unchecked'
  return out
 key=(venue,surface,distance)
 if key in BRIDGES:
  out.update(historical_key=BRIDGES[key],bridge_rule_id='csv21-physical-history-'+venue+'-'+str(distance)+'-v1')
 return out
