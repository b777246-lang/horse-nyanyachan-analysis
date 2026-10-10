from datetime import datetime
from unittest.mock import MagicMock, patch
import unittest
from zoneinfo import ZoneInfo

from jra_cushion import extract, fetch_jra_cushion, select_current_record

JST = ZoneInfo('Asia/Tokyo')
NOW = datetime(2026, 10, 10, 9, 30, tzinfo=JST)


def html(day=10, value='9.2', venue='東京', weekday='土', time='7時00分'):
    return f'<div id="cushion_data_list"><div title="{venue}"><div class="unit"><div class="time">10月{day}日（{weekday}曜）{time}</div><div class="cushion">{value}</div></div></div></div>'


class JraCushionTests(unittest.TestCase):
    def test_only_today_exact_venue_and_checked_weekday(self):
        result = select_current_record(extract(html()), '20261010', '東京', NOW)
        self.assertEqual(result['value'], '9.2')
        self.assertIn('年なし', result['year_basis'])
        for rows in (extract(html(day=9, weekday='金')), extract(html(venue='京都'))):
            result = select_current_record(rows, '20261010', '東京', NOW)
            self.assertEqual(result['status'], 'not_published')
            self.assertIsNone(result['value'])
        for bad in (html(value='6.45'), html(weekday='日'), html(time='10時00分')):
            with self.assertRaises(ValueError):
                select_current_record(extract(bad), '20261010', '東京', NOW)
        with self.assertRaises(ValueError):
            extract(html() + html())

    def test_historical_future_and_jst_date_rejected_before_network(self):
        with patch('jra_cushion.requests.Session') as session:
            for day in ('20261009', '20261011', '20251010'):
                self.assertIsNone(fetch_jra_cushion(day, '東京', now=NOW)['value'])
            session.assert_not_called()
        # UTC late evening is already the following day in Japan.
        utc = datetime.fromisoformat('2026-10-09T23:30:00+00:00')
        self.assertEqual(select_current_record(extract(html()), '20261010', '東京', utc)['value'], '9.2')

    def test_official_response_and_redirect_validation(self):
        response = MagicMock(is_redirect=False, content=html().encode('cp932'))
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        with patch('jra_cushion.requests.Session', return_value=session):
            self.assertEqual(fetch_jra_cushion('20261010', '東京', now=NOW)['value'], '9.2')
            self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        response.is_redirect = True
        response.headers = {'Location': 'https://example.com/cushion'}
        with patch('jra_cushion.requests.Session', return_value=session):
            with self.assertRaises(ValueError):
                fetch_jra_cushion('20261010', '東京', now=NOW)


if __name__ == '__main__':
    unittest.main()
