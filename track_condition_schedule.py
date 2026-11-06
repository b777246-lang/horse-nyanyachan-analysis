"""Session-local, JST schedule. Missed intervals are not replayed."""
from datetime import datetime, time, timedelta
from track_conditions import JST, record_key, resolve_record

INTERVAL = timedelta(minutes=15)


def schedule_slot(now, start, end):
    now = now.astimezone(JST)
    begin = datetime.combine(now.date(), start, JST)
    finish = datetime.combine(now.date(), end, JST)
    # End time includes its displayed minute, so a 30-second tick can run it.
    if begin >= finish or not begin <= now < finish + timedelta(minutes=1):
        return None
    return begin + ((now - begin) // INTERVAL) * INTERVAL


def run_scheduled(state, targets, fetcher, *, now=None):
    live_clock = now is None
    now = now or datetime.now(JST)
    records = state.setdefault('track_conditions', {})
    changed = False
    for key in list(records):
        if not resolve_record(records, *key, now=now):
            records.pop(key, None)
            changed = True
    if not state.get('going_auto_enabled', False):
        return changed
    start = state.get('going_auto_start', time(8))
    end = state.get('going_auto_end', time(16,30))
    slot = schedule_slot(now, start, end)
    if slot is None:
        return changed
    day = now.astimezone(JST).strftime('%Y%m%d')
    attempts = state.setdefault('going_auto_attempts', {})
    messages = []
    for target_day, venue in sorted(set(targets)):
        if target_day != day:
            continue
        token = (day, venue, start.isoformat(), end.isoformat())
        if attempts.get(token) == slot.isoformat():
            continue
        attempts[token] = slot.isoformat()
        # A manual fetch in this interval already meets the schedule.
        current = [resolve_record(records, day, venue, s, now=now) for s in ('芝','ダ')]
        if all(r and r.get('source') == 'jra' and
               datetime.fromisoformat(r['fetched_at']) >= slot for r in current):
            continue
        for surface in ('芝','ダ'):
            records.pop(record_key(day,venue,surface),None)
        changed = True
        try:
            fetched = fetcher(day, venue)
            validation_now = datetime.now(JST) if live_clock else now
            # Do not publish a partial, mismatched, or stale response.
            candidate = {record_key(r['race_date'],r['venue'],r['surface']):r for r in fetched}
            if len(candidate) != 2 or any(
                not resolve_record(candidate,day,venue,s,now=validation_now) or
                candidate[record_key(day,venue,s)].get('source') != 'jra' for s in ('芝','ダ')):
                raise ValueError('取得結果の開催日・競馬場・芝/ダートを確認できません。')
            records.update(candidate)
            messages.append(venue+'：取得済み')
        except Exception as error:
            messages.append(venue+'：取得失敗（'+str(error)+'）')
    if messages:
        state['going_auto_status'] = now.astimezone(JST).strftime('%H:%M')+' / '+' / '.join(messages)
    return changed
