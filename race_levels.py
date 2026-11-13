"""Shared normalization and validation for current/previous race levels."""
import unicodedata

R_LEVELS=frozenset(("低－","低＋","普通","高－","高＋","低★","高★"))

def normalize_r_level(value):
    text=unicodedata.normalize("NFKC",str(value or "")).strip()
    if not text or text.lower()=="nan":return ""
    text=text.replace("-","－").replace("ー","－").replace("−","－").replace("+","＋")
    if text not in R_LEVELS:raise ValueError("Rレベルの値が不正です: "+text)
    return text

def validate_current_levels(frame):
    if 'race_level' not in frame.columns:frame['race_level']=''
    frame['race_level']=frame['race_level'].map(normalize_r_level)
    groups={}
    for _,row in frame.iterrows():
        rid=str(row.get('race_id','') or '').strip()[:16];level=row.get('race_level','')
        if rid and level:groups.setdefault(rid,set()).add(level)
    bad=[rid for rid,levels in groups.items() if len(levels)>1]
    if bad:raise ValueError('同一レース内で今走Rレベルが一致しません: '+', '.join(bad[:3]))
    return frame

def previous_r_level(previous):
    if not previous or previous.get('r_level_status') not in (None,'','AVAILABLE'):return ''
    try:return normalize_r_level(previous.get('r_level'))
    except ValueError:return ''
