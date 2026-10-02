import unittest

from jra_odds import JRA_ACCESS_URL, _find_race_select_cname, _find_race_url


class MeetingSelectionTests(unittest.TestCase):
    def test_current_meeting_links_select_exact_date_and_venue(self):
        # 2026-10-03にJRA開催選択ページで確認したリンク。
        html = """
        <a onclick="doAction('/JRADB/accessD.html','pw01drl00052026040120261003/EC')">東京1日</a>
        <a onclick="doAction('/JRADB/accessD.html','pw01drl00082026040120261003/CA')">京都1日</a>
        <a onclick="doAction('/JRADB/accessD.html','pw01drl00052026040220261004/DA')">東京2日</a>
        """
        self.assertEqual(
            _find_race_select_cname(html, JRA_ACCESS_URL, "20261003", "東京"),
            (JRA_ACCESS_URL, "pw01drl00052026040120261003/EC"),
        )
        with self.assertRaisesRegex(RuntimeError, "開催が見つかりません"):
            _find_race_select_cname(html, JRA_ACCESS_URL, "20261003", "中山")

    def test_previous_link_format_is_supported(self):
        html = """<a onclick="doAction('/JRADB/accessD.html','pw01drl10062026040920260927/FC')">中山</a>"""
        self.assertEqual(
            _find_race_select_cname(html, JRA_ACCESS_URL, "20260927", "中山"),
            (JRA_ACCESS_URL, "pw01drl10062026040920260927/FC"),
        )

    def test_ambiguous_links_are_rejected(self):
        html = """
        <a onclick="doAction('/JRADB/accessD.html','pw01drl00052026040120261003/EC')">東京</a>
        <a onclick="doAction('/JRADB/accessD.html','pw01drl10052026040120261003/EC')">東京</a>
        """
        with self.assertRaisesRegex(RuntimeError, "一意に決められません"):
            _find_race_select_cname(html, JRA_ACCESS_URL, "20261003", "東京")

    def test_current_race_links_select_exact_race_date_and_venue(self):
        html = """
        <a href="/JRADB/accessD.html?CNAME=pw01dde0105202604010120261003/43">東京1R</a>
        <a href="/JRADB/accessD.html?CNAME=pw01dde0105202604010120261003/43">出馬表</a>
        <a href="/JRADB/accessD.html?CNAME=pw01dde0105202604010220261003/F8">東京2R</a>
        <a href="/JRADB/accessD.html?CNAME=pw01dde0108202604010120261003/AA">京都1R</a>
        """
        self.assertEqual(
            _find_race_url(html, JRA_ACCESS_URL, "20261003", "東京", 1),
            JRA_ACCESS_URL + "?CNAME=pw01dde0105202604010120261003/43",
        )
        with self.assertRaisesRegex(RuntimeError, "出馬表URLが見つかりません"):
            _find_race_url(html, JRA_ACCESS_URL, "20261004", "東京", 1)

    def test_previous_race_link_formats_are_supported(self):
        for prefix in ("pw01dde106", "pw01dde1006"):
            with self.subTest(prefix=prefix):
                url = JRA_ACCESS_URL + f"?CNAME={prefix}202604090120260927/FC"
                self.assertEqual(
                    _find_race_url(f'<a href="{url}">中山1R</a>', JRA_ACCESS_URL,
                                   "20260927", "中山", 1),
                    url,
                )


if __name__ == "__main__":
    unittest.main()
