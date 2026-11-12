import unittest
from pathlib import Path
import pandas as pd
WEB=Path(__file__).parent.name=='tests'
A='★福島芝2600特注★'
G='★ゴルシ軸特注★'
class Fukushima2600Tests(unittest.TestCase):
 def evaluate(self,ctx):
  if WEB:
   from signals import DEFAULT_REGISTRY
   return {r.comment for r in DEFAULT_REGISTRY.evaluate(ctx)}
  from special_rules import evaluate_pre_specials
  return {r.comment for r in evaluate_pre_specials(ctx)}
 def test_boundaries(self):
  base=dict(venue='福島',surface='芝',distance=2600,arms=110,arms_rank=2,track_condition='良',TUA=180,TUA_rank=1,sire_name='ゴールドシップ')
  self.assertTrue({A,G}<=self.evaluate(base))
  for field,value in [('arms',109.99),('arms_rank',3),('arms_rank',0),('track_condition',None),('track_condition','重')]:
   self.assertNotIn(A,self.evaluate(dict(base,**{field:value})))
  for field,value in [('TUA',179.99),('TUA_rank',2),('sire_name','オルフェーヴル'),('sire_name',''),('sire_name',None)]:
   self.assertNotIn(G,self.evaluate(dict(base,**{field:value})))
  for field,value in [('venue','東京'),('surface','ダ'),('distance',2500)]:
   self.assertFalse({A,G}&self.evaluate(dict(base,**{field:value})))
  self.assertIn(G,self.evaluate(dict(base,track_condition=None,frame=8)))
 def test_pipeline(self):
  from track_conditions import make_record,record_key
  raw=pd.DataFrame([['福1','1勝クラス','芝','2600',8,n,'',f'試験馬{n}',arms,100,tua,50,60,1,10,f'2026110703030101{n:02d}',f'20230000{n:02d}','騎手',3,sire,''] for n,(arms,tua,sire) in enumerate([(120,180,'ゴールドシップ'),(110,180,'オルフェーヴル'),(109,179,'ゴールドシップ')],1)])
  k=record_key('20261107','福島','芝')
  for going in ['良','重',None]:
   records={} if going is None else {k:make_record(*k,going)}
   if WEB:
    from analysis import analyze_csv
    comments=analyze_csv(raw,{}, {},track_conditions=records).frame['総合評価・コース相性判定'].tolist()
   else:
    from qt_data_bridge import QtDataBridge
    bridge=QtDataBridge(course_stats={},qualified_jockeys=set(),frame_colors={});bridge.track_conditions=records
    comments=[r['comment'] for r in bridge.evaluate_frame(raw)]
   self.assertEqual([A in c for c in comments],[going=='良',going=='良',False])
   self.assertEqual([G in c for c in comments],[True,False,False])
