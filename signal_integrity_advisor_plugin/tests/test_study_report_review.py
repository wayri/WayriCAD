"""SI independent study report keeps per-case failures and unresolved evidence."""
import unittest
from signal_integrity_advisor_plugin.report_plots import study_html


class SIStudyReportTests(unittest.TestCase):
    def test_failed_and_incomplete_cases_remain_visible_and_escaped(self):
        attack='</script><script>alert(1)</script>'
        report={'schema':'wayricad.quick-si-study/v1','status':'INCOMPLETE','model':'Independent routes; no coupling','cases':[{'id':'A','net':attack,'start':'U1.1','end':'J1.1','status':'ERROR','error':attack}]}
        document=study_html(report)
        self.assertIn('ERROR',document)
        self.assertIn('&lt;script&gt;',document)
        self.assertNotIn(attack,document)
        self.assertIn('no coupling',document)
        self.assertIn('Exact case inputs',document)
        self.assertIn('report-nav',document)


if __name__=='__main__':unittest.main()
