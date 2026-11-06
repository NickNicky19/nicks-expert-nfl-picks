"""Finding A5: actual advisory functions, fictional providers, no network.

Scope receipts are not numerical-verifier PASS flags. Historical-average
comparisons remain proxies and cannot establish current-model accuracy.
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'pull')]
import build
import classic_model_v2 as model
import compare_lines as compare
import verify


class DiagnosticContractTests(unittest.TestCase):
    def test_loader_uses_actual_namespace_and_leaves_legacy_bytes_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cache=root/'data/cache'
            cache.mkdir(parents=True)
            legacy=cache/'stats_2099_01.json'
            legacy.write_bytes(b'{"unqualified-old": {"stats":{"gp":1}}}')
            before=legacy.read_bytes()
            typed=cache/build.STATS_CACHE_VERSION
            typed.mkdir()
            actual={'p':{'stats':{'gp':1,'rec':None}}}
            (typed/'stats_2099_02.json').write_text(json.dumps(actual))
            with patch.object(compare,'ROOT',root):
                self.assertEqual(compare.load_weeks(),{(2099,2):actual})
            self.assertEqual(legacy.read_bytes(),before)

    def test_unknown_history_and_actual_are_not_zero_or_mean_inputs(self):
        rows=lambda value:{'p':dict(team='AAA',opp='BBB',stats={'gp':1,'rec':value})}
        weeks={(2099,w):rows(v) for w,v in [(1,None),(2,0),(3,4),(4,None)]}
        scoreboard={'events':[{'id':'fictional','status':{'type':{'completed':True}}}]}
        with patch.object(compare.sources,'scoreboard',return_value=scoreboard),\
             patch.object(compare.books,'week_lines',return_value={'p':{'rec':{'close':.5,'open':.5}}}):
            result,_,_=compare.rows_for_week(2099,4,weeks,{'p':{'position':'WR'}})
        self.assertEqual(result[0]['known_prior_components'],2)
        self.assertEqual(result[0]['plain'],2)
        # The real matchup rule admits the played-zero comparison against the
        # other observed4; its n=1 shrink gives .889, without using the null.
        self.assertEqual(result[0]['ours'],1.778)
        self.assertIsNone(result[0]['actual'])
        self.assertFalse(compare.scorable(result[0]))

    def run_proxy(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'proxy.json'
            with patch.object(sys,'argv',['compare_lines.py','--json',str(output)]),\
                 patch.object(compare,'load_weeks',return_value={(2099,1):{}}),\
                 patch.object(compare.sources,'players',return_value={}),\
                 patch.object(compare.sources,'nfl_state',return_value={'season':'2099','week':'1'}),\
                 patch.object(compare,'rows_for_week',return_value=(rows,1,1)),\
                 patch.object(compare.sources,'get_json',side_effect=AssertionError('NETWORK_FORBIDDEN')),\
                 redirect_stdout(io.StringIO()):
                compare.main()
            return json.loads(output.read_bytes())

    def test_proxy_denominators_preserve_unknowns_and_valid_zero(self):
        row=dict(key='rec',week=1,pid='fictional',dk=.5,dk_open=.5,plain=0,ours=0,actual=0)
        report=self.run_proxy([row,dict(row,actual=None),dict(row,ours=None,plain=None)])
        self.assertEqual(report['props'],1)
        self.assertEqual(report['coverage'],dict(rows=3,scored=1,unresolved_actual=1,unavailable_proxy=1,non_scorable=2))
        # A .5 reception gap is below the unchanged .5*1.2 signal margin.
        self.assertEqual(report['below_n'],0)
        self.assertIsNone(report['below_under'])
        self.assertEqual(report['our_side'],100)
        self.assertEqual(report['status'],'PROXY_ONLY')
        self.assertIn('NOT_CURRENT_OR_ISSUED',report['comparison_kind'])
        self.assertIs(report['quote_timing_verified'],False)

    def test_empty_or_all_unknown_proxy_reports_have_no_fabricated_error_score(self):
        for rows in [[],[dict(key='rec',dk=.5,plain=None,ours=None,actual=None)]]:
            with self.subTest(rows=len(rows)):
                report=self.run_proxy(rows)
                self.assertEqual(report['props'],0)
                self.assertEqual(report['status'],'NO_SCORABLE_PROXY_ROWS')
                for key in ['mae_plain','mae_ours','mae_dk','our_side']:
                    self.assertIsNone(report[key])

    def test_invalid_and_nonfinite_values_never_enter_proxy_arithmetic(self):
        row=dict(dk=.5,plain=0,ours=0,actual=0)
        self.assertTrue(compare.scorable(row))
        for key in row:
            for value in [None,False,'0',float('nan'),float('inf')]:
                self.assertFalse(compare.scorable(dict(row,**{key:value})))

    def test_current_profile_refuses_legacy_parity_without_exact_inputs(self):
        data=dict(execution_model=model.contract(ROOT))
        result=verify.current_profile_status(data,root=ROOT)
        self.assertEqual(result['status'],'NOT_EVALUATED_CURRENT_MODEL_INPUT_CLOSURE_REQUIRED')
        self.assertIs(result['numerical_parity_passed'],False)
        self.assertEqual(result['provider_requests'],0)
        self.assertIsNone(verify.current_profile_status({},root=ROOT))
        with self.assertRaisesRegex(ValueError,'ADVISORY_CURRENT_SOURCE_BINDING_REJECTED'):
            verify.current_profile_status({'execution_model':{'model':'unknown'}},root=ROOT)

    def test_current_source_cannot_be_aliased_or_corrupted_into_legacy_success(self):
        data=dict(execution_model=model.contract(ROOT))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in model.ENGINE:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
            altered=root/'pull/scoring.py'
            raw=altered.read_bytes();altered.write_bytes(b'!'+raw[1:])
            with self.assertRaisesRegex(ValueError,'UNRECOGNIZED_CLASSIC_CURRENT_SOURCE'):
                verify.current_profile_status(data,root=root)

    def test_current_verifier_writes_honest_non_success_receipt_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in model.ENGINE:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
            path=root/'output/data/week.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(season=2099,week=1,execution_model=model.contract(root))))
            report=root/'scope.json'
            capture=io.StringIO()
            with patch.object(sys,'argv',['verify.py','--json',str(report)]),patch.object(verify,'ROOT',root),\
                 patch.object(verify,'check_ppr',side_effect=AssertionError('LEGACY_CHECK_MUST_NOT_IMPERSONATE_CURRENT')),\
                 patch.object(verify.requests.sessions.Session,'request',side_effect=AssertionError('NETWORK_FORBIDDEN')),\
                 redirect_stdout(capture),self.assertRaises(SystemExit) as stopped:
                verify.main()
            self.assertEqual(stopped.exception.code,2)
            self.assertNotIn('ALL CHECKS PASSED',capture.getvalue())
            self.assertIs(json.loads(report.read_bytes())['numerical_parity_passed'],False)


if __name__=='__main__': unittest.main()
