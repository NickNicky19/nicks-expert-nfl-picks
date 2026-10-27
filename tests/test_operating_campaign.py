"""LOCAL proposal unit controls; all CI responses are mocks, never qualification."""
import importlib.util
import copy
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
DEPENDENCY_ROOT=HERE
sys.path.insert(0,str(DEPENDENCY_ROOT/'tools'))
spec=importlib.util.spec_from_file_location('proposed_operating_campaign',HERE/'tools/operating_campaign.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def final_workload_control(source='1'*40,tree='2'*40):
    """Synthetic metric-validator control only, never measured qualification."""
    sample={'opportunities':1,'unique_players':1,'unique_games':1,'unique_weeks':1}
    cohorts=[];captures=[]
    for model in sorted(c.FINAL_ACCURACY_MODELS):
        categories={}
        for category in c.FINAL_ACCURACY_CATEGORIES:
            item={name:dict(sample) for name in ('coverage','paired_coverage','unpaired_coverage')}
            item['unpaired_coverage']={k:0 for k in sample}
            item.update(outcome_status={'resolved':1},paired_resolved=1,adjusted_only_resolved=0)
            if category=='fpts':item['direct_provider_ppr_resolved']=0
            if category=='anytime_td':item['probability']={'originally_recorded_probability':0,'rederived_from_original_count_retained_formula':1}
            categories[category]=item
        cohorts.append(dict(model_version=model,engine_sha256=c.FINAL_ACCURACY_ENGINES[model],period='cumulative',forecast_provenance='original_recorded_pregame_observation',outcome_provenance='saved_cache_descriptive_regrade',statistic_contract_sha256=c._final_statistic_contracts()[model],source_report_sha256='5'*64,coverage={**sample,'opportunities':len(categories)},categories=categories))
        expected=c.FINAL_REFERENCE['accuracy_capture_work'][model]
        captures.append(dict(model_version=model,capture_coverage=dict(unique_receipts=expected['unique_receipts'],duplicate_receipts=0,eligible_capture_rows=copy.deepcopy(expected['eligible_capture_rows']),paired_capture_rows=copy.deepcopy(expected['paired_capture_rows']),excluded={}),unsupported_outcome_counts={}))
    metrics={name:1 for name in c.FINAL_METRICS};metrics.update(c.FINAL_LOAD_FLOORS,**c.FINAL_REFERENCE['informational_descriptor_metrics'],complete_generations=24)
    coverage=dict(categories={k:1 for k in c.seed_v1.REQUIRED_SETS['categories']},sides={'over':1,'under':1},sources={k:1 for k in c.seed_v1.REQUIRED_SETS['sources']},cohorts={k:1 for k in c.FINAL_COHORTS},checkpoints={k:1 for k in c.seed_v1.REQUIRED_SETS['checkpoints']},dimensions={k:1 for k in c.FINAL_DIMENSIONS},results={k:1 for k in c.seed_v1.REQUIRED_SETS['status_counts']},periods={'cumulative':1,'2026-w06':1},strategy_selected={k:1 for k in ('ranked_biggest_lean_v1','ranked_projected_points_v1')})
    value=dict(schema_version='final-candidate-workload-v1',candidate={'commit':source,'tree':tree},publication_source=source,generation_source=source,generation_sha256='6'*64,report_id='7'*64,report_schema_version='selection-report-v4',summary_index_sha256='8'*64,semantics_sha256='9'*64,reference=copy.deepcopy(c.FINAL_REFERENCE),metrics=metrics,coverage=coverage,contexts=dict(ids=sorted(c.FINAL_REFERENCE_CONTEXT_IDS),descriptors_sha256='a'*64,missing_reference_ids=[],extra_reference_ids=[],correspondence='EXACT_DESCRIPTOR_IDS_MISSING_EXTRA_REPORTED_NOT_SYNTHETIC_HISTORY'),accuracy=dict(schema_version='forecast-accuracy-public-v1',content_sha256='b'*64,capture_coverage=captures,cohorts=cohorts))
    value['decisions']=c._final_workload_decisions(value)
    value['applicability']=c._final_applicability(value)
    return value


def permitted_accuracy_control():
    """Actual typed projector on small fictional inputs, not operating evidence."""
    helper=importlib.util.spec_from_file_location('accuracy_workload_unit_helpers',DEPENDENCY_ROOT/'tests/test_accuracy_publication.py')
    helpers=importlib.util.module_from_spec(helper);helper.loader.exec_module(helpers)
    import accuracy_publication
    reports=[]
    for model in sorted(c.FINAL_ACCURACY_MODELS):
        rows=[];td=[]
        for provenance in sorted(accuracy_publication.PROVENANCE):
            for category in sorted(c.FINAL_ACCURACY_CATEGORIES):
                row=helpers.observation('unit-'+provenance+'-'+category,category,actual=1,raw=2,adjusted=1,provenance=provenance,model=model)
                if category=='anytime_td':
                    row.update(raw_projection=.5,adjusted_projection=None,probability=.25,probability_provenance='rederived_from_original_count_retained_formula');td.append(row)
                rows.append(row)
        reports.append(helpers.evaluation(rows,td=td,model=model))
    typed=accuracy_publication.project_accuracy(reports);accuracy_publication.validate_accuracy(typed)
    expected={(model,provenance) for model in c.FINAL_ACCURACY_MODELS
              for provenance in accuracy_publication.PROVENANCE}
    assert set(c.FINAL_ACCURACY_MODELS)<=accuracy_publication.MODELS
    assert len(typed['cohorts'])==len(expected)==12
    assert {(cohort['model_version'],cohort['outcome_provenance'])
            for cohort in typed['cohorts']}==expected
    return typed


class FinalCandidateWorkload(unittest.TestCase):
    def test_current_bound_metric_control_and_honest_zero_probabilities(self):
        value=final_workload_control();c._check_final_workload(value,'1'*40,'2'*40)
        self.assertTrue(value['decisions']['admitted'])
        self.assertEqual(value['accuracy']['cohorts'][0]['categories']['fpts']['direct_provider_ppr_resolved'],0)
        self.assertEqual(value['accuracy']['cohorts'][0]['categories']['anytime_td']['probability']['originally_recorded_probability'],0)

    def test_old_source_or_wrong_current_tree_cannot_borrow_final_counts(self):
        for key,bad in (('commit',c.BASE),('tree','3'*40)):
            value=final_workload_control();value['candidate'][key]=bad
            with self.assertRaisesRegex(RuntimeError,'source/version'):
                c._check_final_workload(value,'1'*40,'2'*40)
        value=final_workload_control();value['publication_source']=c.BASE
        with self.assertRaisesRegex(RuntimeError,'source/version'):c._check_final_workload(value)
        value=final_workload_control();value['report_schema_version']='selection-report-v3';value['decisions']=c._final_workload_decisions(value)
        value['applicability']=c._final_applicability(value)
        with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)

    def test_actual_final_rows_groups_and_outcomes_each_enforce_load_floor(self):
        for name,floor in c.FINAL_LOAD_FLOORS.items():
            value=final_workload_control();value['metrics'][name]=floor-1;value['decisions']=c._final_workload_decisions(value)
            value['applicability']=c._final_applicability(value)
            self.assertFalse(value['decisions']['numeric'][name])
            c._check_final_workload(value,require_admitted=False)
            with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)

    def test_final_missing_metric_or_stale_admitted_flag_is_rejected(self):
        value=final_workload_control();del value['metrics']['groups']
        with self.assertRaisesRegex(RuntimeError,'counts/bytes'):c._check_final_workload(value)
        value=final_workload_control();value['metrics']['groups']=0
        with self.assertRaisesRegex(RuntimeError,'recomputed'):c._check_final_workload(value)

    def test_required_product_contexts_cannot_be_hidden_by_larger_totals(self):
        mutations=[('cohorts','ranked_biggest_lean_v1'),('dimensions','category_side_selection_kickoff_lead'),('sources','sleeper'),('checkpoints','90m'),('categories','rec'),('sides','under')]
        for key,name in mutations:
            value=final_workload_control();del value['coverage'][key][name];value['metrics']['groups']*=10
            value['decisions']=c._final_workload_decisions(value)
            value['applicability']=c._final_applicability(value)
            with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)

    def test_incidental_reference_context_difference_is_reported_not_fabricated(self):
        value=final_workload_control();missing=value['contexts']['ids'].pop();value['metrics']['contexts']-=1
        value['contexts']['missing_reference_ids']=[missing]
        value['decisions']=c._final_workload_decisions(value)
        value['applicability']=c._final_applicability(value)
        c._check_final_workload(value)
        value['contexts']['missing_reference_ids']=[]
        with self.assertRaisesRegex(RuntimeError,'correspondence'):c._check_final_workload(value)

    def test_display_context_alone_cannot_substitute_for_ranked_selection(self):
        value=final_workload_control();value['coverage']['strategy_selected']['ranked_projected_points_v1']=0
        value['decisions']=c._final_workload_decisions(value)
        value['applicability']=c._final_applicability(value)
        with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)

    def test_accuracy_keys_without_real_supported_populations_cannot_pass(self):
        value=final_workload_control()
        for capture in value['accuracy']['capture_coverage']:
            capture['capture_coverage']['eligible_capture_rows']['rec']=0
            capture['capture_coverage']['paired_capture_rows']['rec']=0
        value['decisions']=c._final_workload_decisions(value)
        value['applicability']=c._final_applicability(value)
        with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)
        value=final_workload_control();value['accuracy']['cohorts'][0]['engine_sha256']='f'*64
        with self.assertRaisesRegex(RuntimeError,'engine/cohort'):c._check_final_workload(value)
        value=final_workload_control();value['accuracy']['cohorts'][0]['categories']['rec']['paired_resolved']=2
        with self.assertRaisesRegex(RuntimeError,'reconcile'):c._check_final_workload(value)

    def test_rehashed_unsupported_statistic_contract_fails_private_and_compact(self):
        private=final_workload_control();public=c._public_final_workload(private)
        for cohort in private['accuracy']['cohorts']:cohort['statistic_contract_sha256']='f'*64
        for cohort in public['accuracy']['cohorts']:cohort['statistic_contract_sha256']='f'*64
        public['private_metrics_sha256']=c.sha(c.encoded(private))
        with self.assertRaisesRegex(RuntimeError,'statistic contract'):c._check_final_workload(private)
        with self.assertRaisesRegex(RuntimeError,'statistic contract'):c._check_final_workload(public,projection=True)
        typed=permitted_accuracy_control()
        expected=c._final_statistic_contracts()
        self.assertTrue(all(v['statistic_contract_sha256']==expected[v['model_version']] for v in typed['cohorts']))

    def test_td_bases_cannot_double_count_the_same_resolved_forecast(self):
        value=final_workload_control()
        td=value['accuracy']['cohorts'][0]['categories']['anytime_td']
        td['probability']={'originally_recorded_probability':1,'rederived_from_original_count_retained_formula':1}
        with self.assertRaisesRegex(RuntimeError,'TD probability bases'):c._check_final_workload(value)

    def test_accuracy_capture_and_cohort_bounds_are_preserved(self):
        value=final_workload_control();capture=value['accuracy']['capture_coverage'][0]['capture_coverage']
        capture['paired_capture_rows']['rec']=capture['eligible_capture_rows']['rec']+1
        with self.assertRaisesRegex(RuntimeError,'paired capture'):c._check_final_workload(value)
        value=final_workload_control();value['accuracy']['cohorts'][0]['categories']['rec']['coverage']['unique_players']=2
        with self.assertRaisesRegex(RuntimeError,'sample identities'):c._check_final_workload(value)
        value=final_workload_control();value['accuracy']['cohorts'][0]['coverage']['opportunities']+=1
        with self.assertRaisesRegex(RuntimeError,'category populations'):c._check_final_workload(value)

    def test_nested_reference_values_do_not_alias_source_defined_guard(self):
        value=final_workload_control();original=copy.deepcopy(c.FINAL_REFERENCE)
        value['reference']['accuracy_capture_work']['original_sleeper_matchup_baseline']['unique_receipts']=0
        self.assertEqual(c.FINAL_REFERENCE,original)
        with self.assertRaisesRegex(RuntimeError,'exact final'):c._check_final_workload(value)

    def test_supported_missing_model_preserves_known_metrics_and_unknown_dimensions(self):
        value=final_workload_control()
        value['accuracy']['capture_coverage']=[v for v in value['accuracy']['capture_coverage'] if v['model_version']=='original_sleeper_matchup_baseline']
        value['accuracy']['cohorts']=[v for v in value['accuracy']['cohorts'] if v['model_version']=='original_sleeper_matchup_baseline']
        value['decisions']=c._final_workload_decisions(value);value['applicability']=c._final_applicability(value)
        c._check_final_workload(value,require_admitted=False)
        absent=[value['applicability']['comparisons'][name] for name in value['applicability']['deficiencies'] if value['applicability']['comparisons'][name]['presence']=='ABSENT_UNESTABLISHED']
        self.assertTrue(absent);self.assertTrue(all(v['actual'] is None for v in absent))
        self.assertIn('original_sleeper_matchup_baseline',{v['model_version'] for v in value['accuracy']['cohorts']})
        with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)

    def test_actual_typed_maximum_cohort_population_compacts_losslessly(self):
        value=final_workload_control();value['accuracy']=c._accuracy_workload(permitted_accuracy_control())
        # Boundary telemetry population only: not invented observations/contexts
        # in a seed, report, fixture or application qualification.
        ids=sorted(c.sha(c.encoded(['unit-context-boundary',i])) for i in range(512))
        value['metrics']['contexts']=len(ids);value['contexts'].update(ids=ids,missing_reference_ids=sorted(c.FINAL_REFERENCE_CONTEXT_IDS-set(ids)),extra_reference_ids=sorted(set(ids)-c.FINAL_REFERENCE_CONTEXT_IDS))
        value['decisions']=c._final_workload_decisions(value);value['applicability']=c._final_applicability(value)
        public=c._public_final_workload(value);c._check_final_workload(public,projection=True)
        self.assertEqual(public['private_metrics_sha256'],c.sha(c.encoded(value)))
        self.assertNotIn('ids',public['contexts']);self.assertEqual(public['contexts']['extra_reference_count'],512)
        self.assertEqual(public['contexts']['ids_sha256'],c.sha(c.encoded(ids)))
        self.assertEqual([sorted(c.FINAL_REFERENCE_CONTEXT_IDS)[i] for i in public['contexts']['missing_reference_indices']],value['contexts']['missing_reference_ids'])
        fields=('opportunities','unique_players','unique_games','unique_weeks')
        for before,after in zip(value['accuracy']['cohorts'],public['accuracy']['cohorts']):
            self.assertEqual(dict(zip(fields,after['coverage'])),before['coverage'])
            for category,item in before['categories'].items():
                for name in ('coverage','paired_coverage','unpaired_coverage'):
                    self.assertEqual(dict(zip(fields,after['categories'][category][name])),item[name])
        self.assertLess(len(c.encoded(public)),52*1024) # leaves room inside unchanged outer64KiB.
        public['accuracy']['cohorts'][0]['coverage'].append(0)
        with self.assertRaisesRegex(RuntimeError,'compact accuracy'):c._check_final_workload(public,projection=True)

    def test_smaller_accuracy_scan_is_unknown_applicability_not_new_fictional_floor(self):
        value=final_workload_control()
        for capture in value['accuracy']['capture_coverage']:capture['capture_coverage']['unique_receipts']=277
        value['decisions']=c._final_workload_decisions(value);value['applicability']=c._final_applicability(value)
        self.assertTrue(value['decisions']['admitted']);c._check_final_workload(value)
        self.assertEqual(value['applicability']['status'],'UNKNOWN_ADDITIONAL_MATCHED_REAL_CASE_REQUIRED')
        self.assertEqual(len(value['applicability']['deficiencies']),2)
        self.assertTrue(all(value['applicability']['comparisons'][name]['actual']==277 and value['applicability']['comparisons'][name]['reference']==431 for name in value['applicability']['deficiencies']))
        value['applicability']['status']='CONSERVATIVE_REFERENCE_ENVELOPE_COVERED'
        with self.assertRaisesRegex(RuntimeError,'applicability'):c._check_final_workload(value)

    def test_corrected_pending_does_not_require_invented_resolved_ppr_or_td(self):
        value=final_workload_control()
        for cohort in value['accuracy']['cohorts']:
            if cohort['model_version']=='original_sleeper_matchup_baseline':continue
            for category,item in cohort['categories'].items():
                item.update(paired_resolved=0,adjusted_only_resolved=0,outcome_status={'pending':1})
                if category=='anytime_td':item['probability']={k:0 for k in item['probability']}
        value['decisions']=c._final_workload_decisions(value)
        value['applicability']=c._final_applicability(value)
        c._check_final_workload(value)

    def test_b3_admission_does_not_replace_missing_final_candidate_evidence(self):
        temp=Campaign();value={'admission':{},'correction':{},'advisories':{}}
        with self.assertRaisesRegex(RuntimeError,'missing'):
            c._check_evidence_projection(value)

    def test_commit_collects_after_existing_stage_and_preserves_failure_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'fixture';root.mkdir();result=Path(temp)/'dataflow.json';events=[]
            c.put(result,{'status':'CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING','stages':{}})
            value=final_workload_control();value['metrics']['groups']=1;value['decisions']=c._final_workload_decisions(value)
            value['applicability']=c._final_applicability(value)
            capture=SimpleNamespace(_manifest=lambda *a,**kw:({},{}),_git_archive=lambda *a,**kw:{},stage_pages=lambda *a:events.append('actual-stage-control'),_public_archive_commit=lambda *a:None)
            m={'capture':capture}
            def metrics(*a):events.append('metrics');return value
            with patch.object(c,'require_offline'),patch.object(c,'execution_identity'),patch.object(c,'_sample_context',return_value=(m,None)),patch.object(c,'external',side_effect=lambda *a:contextlib.nullcontext()),patch.object(c,'commit',side_effect=lambda *a:events.append('commit')),patch.object(c,'final_candidate_workload',side_effect=metrics):
                with self.assertRaisesRegex(RuntimeError,'envelope'):c.sample_commit(Path(temp),root,result)
            self.assertEqual(events,['commit','actual-stage-control','metrics'])
            saved=json.loads(result.read_bytes())
            self.assertEqual(saved['final_candidate_workload']['metrics']['groups'],1)
            self.assertEqual(saved['status'],'FINAL_CANDIDATE_WORKLOAD_NOT_ADMITTED')
            self.assertGreaterEqual(saved['stages']['final_candidate_metrics'],0)


    def test_actual_collector_counts_supported_reader_values_without_history_replay(self):
        # Current-graph reader/registry are controlled unit transports; file,
        # descriptor hashing, extraction and decision code are actual. No seed
        # admission, source qualification or application fixture is claimed.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'fixture';base=root/'output/data/selection-grading';base.mkdir(parents=True)
            pages=Path(temp)/'pages';pages.mkdir();(pages/'index.html').write_text('tiny staged unit control')
            descriptor=dict(model_version='original_sleeper_matchup_baseline',provenance_class='local_pregame_membership_observation',engine_sha256=c.FINAL_ACCURACY_ENGINES['original_sleeper_matchup_baseline'],view='top_picks',checkpoint='history',line_source_scope='all',policy_version='phase2-timing-v1',policy_sha256='a'*64)
            context=c.sha(c.encoded(descriptor))
            report='7'*64;namespace=base/report;namespace.mkdir()
            c.put(namespace/'summary.json',dict(report_id=report,row_count=1,source_sha='1'*40,report_schema_version='selection-report-v4',contexts={context:descriptor},summary_partitions=[dict(encoded_bytes=12,decoded_bytes=24)]))
            c.put(namespace/'outcomes.json',dict(report_id=report,outcome_count=1,periods=[dict(encoded_bytes=13,decoded_bytes=26)]));c.put(base/'hosting.json',{'unit':'registry transport'})
            pointer=dict(schema_version='selection-publication-pointer-v4',report_id=report,row_count=1,rows=[dict(encoded_bytes=10,decoded_bytes=20)])
            for name in ('summary','outcomes'):
                path=namespace/(name+'.json');pointer[name]=dict(path=report+'/'+name+'.json',sha256=c.sha(path.read_bytes()),decoded_bytes=path.stat().st_size)
            c.put(base/'latest.json',pointer)
            c.put(root/'output/data/release-identity.json',dict(schema_version='website-generation-v1',source_sha='1'*40,generation_sha256='6'*64,selection_report_id=report))
            for source in (base/'latest.json',namespace/'summary.json',namespace/'outcomes.json',root/'output/data/release-identity.json'):
                destination=pages/source.relative_to(root/'output');destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(source.read_bytes())
            typed=final_workload_control()['accuracy'];raw_accuracy={'schema_version':typed['schema_version'],'capture_coverage':typed['capture_coverage'],'cohorts':[]}
            for cohort in typed['cohorts']:
                raw=copy.deepcopy(cohort)
                for category,item in raw['categories'].items():
                    item['paired']={'raw':{'n':item.pop('paired_resolved')}};item['adjusted_only']={'n':item.pop('adjusted_only_resolved')}
                    if category=='fpts':item['direct_provider_ppr']={'raw':{'n':item.pop('direct_provider_ppr_resolved')}}
                    if category=='anytime_td':item['probability']={k:{'n':n} for k,n in item['probability'].items()}
                raw_accuracy['cohorts'].append(raw)
            rows=[dict(category='rec',side='over',cohort='top_picks',checkpoint='history',result='pending',action='SELECT')]
            tables=[dict(line_source_scope='all',view='top_picks',dimension='overall',period='cumulative')]
            summary={'report_id':report,'summary':{'tables':tables},'forecast_accuracy':raw_accuracy}
            calls=[]
            import selection_publication as actual_publication
            publication=SimpleNamespace(__file__=str(root/'tools/selection_publication.py'),_partition_asset=actual_publication._partition_asset,publication_contents=lambda b,p:(calls.append('publication') or (summary,rows,[{}])))
            capture=SimpleNamespace(__file__=str(root/'tools/phase2_capture.py'),_registry=lambda *a:(calls.append('registry') or {str(i):{} for i in range(24)}))
            marker={'candidate_commit':'1'*40,'candidate_tree':'2'*40}
            with patch.object(c,'execution_identity',return_value=marker),patch.object(c.seed_v1,'workload',side_effect=AssertionError('No diagnostic all-history replay for counts')):
                value=c.final_candidate_workload(Path(temp),root,{'publication':publication,'capture':capture},pages)
            self.assertEqual(calls,['publication','registry'])
            self.assertEqual((value['metrics']['rows'],value['metrics']['groups'],value['metrics']['outcomes']),(1,1,1))
            self.assertEqual(value['metrics']['staged_bytes'],sum(path.stat().st_size for path in pages.rglob('*') if path.is_file()))
            self.assertEqual(value['contexts']['ids'],[context])
            self.assertEqual(json.loads((root.parent/'FINAL_CONTEXT_DESCRIPTORS.private.json').read_bytes()),{context:descriptor})
            self.assertFalse(value['decisions']['admitted'])
            def race(*args):
                (root/'output/data/release-identity.json').write_bytes(b'{"changed":"same-path-final-boundary"}')
                return summary,rows,[{}]
            publication.publication_contents=race
            with patch.object(c,'execution_identity',return_value=marker):
                with self.assertRaisesRegex(RuntimeError,'staged generation'):c.final_candidate_workload(Path(temp),root,{'publication':publication,'capture':capture},pages)
            publication.__file__=str(Path(temp)/'old_B3/selection_publication.py')
            with patch.object(c,'execution_identity',return_value=marker):
                with self.assertRaisesRegex(RuntimeError,'actual installed'):c.final_candidate_workload(Path(temp),root,{'publication':publication,'capture':capture},pages)

    def test_zero_counts_cannot_masquerade_as_required_semantic_keys(self):
        value=final_workload_control();value['coverage']['cohorts']['ranked_biggest_lean_v1']=0
        value['decisions']=c._final_workload_decisions(value)
        value['applicability']=c._final_applicability(value)
        with self.assertRaisesRegex(RuntimeError,'envelope'):c._check_final_workload(value)


class Campaign(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.code=self.base/'candidate';self.root=self.base/'derived';self.result=self.base/'result.json'
        self.fp=dict(commit='1'*40,tree='2'*40,source_manifest_sha256='3'*64,environment={'python':{'version':'3.12.15'},'node':{'version':'22.23.3'},'distributions':[{'name':'certifi','version':'2026.10.19'}]},files=[])
        self.proof=dict(schema_version='source-ci-verification-v1',executed_commit=self.fp['commit'],executed_tree=self.fp['tree'],
            source_manifest_sha256=self.fp['source_manifest_sha256'],source_ci_commit=self.fp['commit'],job_id=456,seal_sha256='c'*64,environment_sha256=c.sha(c.encoded(self.fp['environment'])),
            claim='COMPLETE_SOURCE_CHECKS_ONLY_NOT_GENERATION_OR_OPERATING_QUALIFICATION',run_id=123,run_attempt=1)
    def tearDown(self):
        if hasattr(self,'fixture_env'):self.fixture_env.stop()
        self.temp.cleanup()
    def test_matched_private_binding(self):c._matched_source_ci(self.proof,self.fp)
    def test_changed_source_binding(self):
        self.fp['source_manifest_sha256']='f'*64
        with self.assertRaisesRegex(RuntimeError,'differs'):c._matched_source_ci(self.proof,self.fp)
    def test_changed_runtime_binding(self):
        self.fp['environment']['node']['version']='changed'
        with self.assertRaisesRegex(RuntimeError,'differs'):c._matched_source_ci(self.proof,self.fp)
    def test_source_only_claim_required(self):
        self.proof['claim']='PASS'
        with self.assertRaises(RuntimeError):c._matched_source_ci(self.proof,self.fp)
    def test_cli_uses_fresh_private_prefix_per_child(self):
        observed=[]
        def child(code,action,env):
            path=Path(env['PYTHONPYCACHEPREFIX'])
            self.assertEqual(path.stat().st_mode&0o777,0o700)
            self.assertEqual(list(path.iterdir()),[])
            self.assertEqual(env['PYTHONDONTWRITEBYTECODE'],'1')
            self.assertEqual(action,'fingerprint');observed.append(path)
            return self.fp
        with patch.object(c,'_fresh_cli',side_effect=child),patch.object(c.Path,'cwd',return_value=self.code),patch.dict(os.environ,{'RUNNER_TEMP':str(self.base)}):
            self.assertEqual(c._source_ci_cli(self.code,'fingerprint'),self.fp)
            self.assertEqual(c._source_ci_cli(self.code,'fingerprint'),self.fp)
        self.assertNotEqual(observed[0],observed[1])
        self.assertTrue(all(not p.exists() for p in observed))
    def transport(self):
        return SimpleNamespace(__file__=str(self.code/'tools/operating_seed_transport.py'),
            read_approval=lambda *args:{'seed_manifest_sha256':'a'*64},retrieve=lambda *a,**kw:None)
    def test_cli_rejects_different_cwd_and_actions(self):
        with self.assertRaises(RuntimeError):c._source_ci_cli(self.code,'fingerprint')
        with self.assertRaises(RuntimeError):c._source_ci_cli(self.code,'anything')
    def test_launch_keeps_only_trusted_coordinator_online_and_uses_private_state(self):
        events=[];observed={}
        def cli(code,action):
            events.append(action)
            self.assertTrue(os.environ.get('GH_TOKEN'))
            return self.proof if action=='verify' else self.fp
        def guarded(*args,**kwargs):
            self.assertTrue(os.environ.get('GH_TOKEN'));events.append('isolated-child')
        def job(*args,**kwargs):observed.update(operation=kwargs['_operation']);events.append('job')
        guard=SimpleNamespace(__file__=str(self.code/'tools/diagnostic_network_guard.py'),install=guarded,controls=lambda:events.append('controls'))
        with patch.object(c,'_job_context'),patch.object(c,'_resource_preflight',return_value={'status':'MOCK_ONLY'}),patch.object(c,'_transport_allocation'),patch.object(c,'_restoration_allocation'),patch.dict(sys.modules,{'operating_seed_transport':self.transport()}),patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'OPERATING_ARTIFACT_APPROVAL_SHA256':'a'*64,'SEED_MANIFEST_SHA256':'a'*64}),patch.object(c,'_source_ci_cli',side_effect=cli),patch.object(c,'job',side_effect=job),patch.object(c,'require_offline'),patch.object(c,'_guarded_stage',side_effect=guarded),patch.dict(os.environ,{'GH_TOKEN':'fictional-unit-token'}):
            c.launch_job(self.code,self.root,self.result,1)
        self.assertEqual(events,['verify','fingerprint','isolated-child','job'])
        self.assertNotIn('GH_TOKEN',os.environ)
        self.proof['run_id']=999;self.fp['environment']['node']['version']='later mutation'
        self.assertEqual(observed['operation'][0]['run_id'],123)
        self.assertEqual(observed['operation'][1]['environment']['node']['version'],'22.23.3')
        self.assertLessEqual(observed['operation'][2],observed['operation'][3]['source_ci_online']['end']+observed['operation'][2])
    def test_failed_online_verification_never_enters_data_worker(self):
        with patch.object(c,'_job_context'),patch.object(c,'_resource_preflight',return_value={'status':'MOCK_ONLY'}),patch.object(c,'_transport_allocation'),patch.object(c,'_restoration_allocation'),patch.dict(sys.modules,{'operating_seed_transport':self.transport()}),patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'OPERATING_ARTIFACT_APPROVAL_SHA256':'a'*64,'SEED_MANIFEST_SHA256':'a'*64}),patch.object(c,'_source_ci_cli',side_effect=RuntimeError('mock unavailable')),patch.object(c,'job') as job,patch.object(c,'git',return_value='1'*40),patch.dict(os.environ,{'GH_TOKEN':'fictional-unit-token'}):
            with self.assertRaises(RuntimeError):c.launch_job(self.code,self.root,self.result,1)
            self.assertNotIn('GH_TOKEN',os.environ);job.assert_not_called()
        self.assertEqual(json.loads(self.result.read_bytes())['status'],'SOURCE_CI_OR_ISOLATION_SETUP_FAILED')
    def test_changed_after_online_stops_before_guard(self):
        self.fp['environment']['node']['version']='changed'
        with patch.object(c,'_job_context'),patch.object(c,'_resource_preflight',return_value={'status':'MOCK_ONLY'}),patch.object(c,'_transport_allocation'),patch.object(c,'_restoration_allocation'),patch.dict(sys.modules,{'operating_seed_transport':self.transport()}),patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'OPERATING_ARTIFACT_APPROVAL_SHA256':'a'*64,'SEED_MANIFEST_SHA256':'a'*64}),patch.object(c,'_source_ci_cli',side_effect=[self.proof,self.fp]),patch.object(c,'job') as job,patch.object(c,'git',return_value='1'*40):
            with self.assertRaises(RuntimeError):c.launch_job(self.code,self.root,self.result,1)
            job.assert_not_called()
    def test_direct_job_cannot_use_disk_pass_or_flag(self):
        with patch.object(c,'_job_context'):
            with self.assertRaisesRegex(RuntimeError,'trusted'):c.job(self.code,self.root,self.result,1)
    def test_pending_packaging_cannot_run_connected_update(self):
        with patch.object(c,'execution_identity',side_effect=RuntimeError('packaging pending')),patch.object(c.seed_v1,'sample') as sample:
            with self.assertRaises(RuntimeError):c.sample_capture(self.code,self.root,self.result)
            sample.assert_not_called()
    def test_unrelated_credential_rejected_before_any_child(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fictional-not-a-key'}),patch.object(c.subprocess,'check_output') as child:
            with self.assertRaisesRegex(RuntimeError,'Unrelated'):c._job_context(self.code,self.root,self.result,1)
            child.assert_not_called()
    def fixture(self):
        for root in (self.code,self.root):
            root.mkdir()
            for lane in ('pull','tools','config','data','output'): (root/lane).mkdir()
            (root/'output/data').mkdir()
            (root/'pull/build.py').write_text('# identical fictional arithmetic\n')
            (root/'config/unchanged.json').write_text('{"same":true}\n')
            (root/'config/phase2.json').write_text('{"fictional":true}\n' if root==self.root else '{"production":true}\n')
            if root==self.root:(root/'output/data/week.json').write_text('{"unit":"original fictional role"}\n')
            (root/'tools/old.py').write_text('# candidate\n' if root==self.code else '# retained old\n')
            (root/'output/app.js').write_text('// candidate\n' if root==self.code else '// retained old\n')
            (root/'output/index.html').write_text('<html>same</html>\n')
            for command in (('init','-q'),('add','.'),('-c','user.name=FictionalUnit','-c','user.email=fictional@example.invalid','commit','-qm','Wholly fictional unit control')):
                subprocess.run(['git','-C',str(root),*command],check=True)
        (self.root/'data/original.json').write_text('{"immutable":"fictional"}\n')
        (self.root/'FICTIONAL_ONLY.json').write_text(json.dumps(dict(reviewed_source=c.BASE,construction_code=c.BASE,campaign=c.CAMPAIGN,dimensions=c.seed_v1.SMALL,notice=c.NOTICE)))
        c.git(self.root,'add','.');c.git(self.root,'commit','-qm','Wholly fictional unit evidence')
        fp=dict(self.fp);fp['commit']=c.git(self.code,'rev-parse','HEAD');fp['tree']=c.git(self.code,'rev-parse','HEAD^{tree}');fp['files']=[]
        for p in sorted(self.code.rglob('*')):
            if p.is_file() and '.git' not in p.parts:
                raw=p.read_bytes();fp['files'].append(dict(path=p.relative_to(self.code).as_posix(),mode='100644',bytes=len(raw),sha256=c.sha(raw),blob=c.git(self.code,'hash-object',str(p))))
        seed=self.root.parent/'retrieved-seed';seed.mkdir()
        raw=c.encoded(dict(schema_version='fictional-operating-seed-v1',full_admitted=True,application_source=c.BASE,
            harness_sha256=c.SEED_HARNESS_SHA256,roots={'fictional_head':c.git(self.root,'rev-parse','HEAD')},
            files={name:dict(sha256=c._hash_file(self.root/name),bytes=(self.root/name).stat().st_size,mode=0o644)
                for name in ('config/phase2.json','output/data/week.json')}))
        (seed/'SEED_MANIFEST.json').write_bytes(raw)
        self.fixture_env=patch.dict(os.environ,{'SEED_MANIFEST_SHA256':c.sha(raw)});self.fixture_env.start()
        return fp
    def test_derived_install_preserves_config_data_and_defers_app(self):
        fp=self.fixture();before=(self.root/'data/original.json').read_bytes();config=(self.root/'config/phase2.json').read_bytes()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root)
            c.execution_identity(self.code,self.root,packaged=False)
            with self.assertRaisesRegex(RuntimeError,'bytes differ'):c.execution_identity(self.code,self.root)
        self.assertEqual((self.root/'tools/old.py').read_bytes(),(self.code/'tools/old.py').read_bytes())
        self.assertEqual((self.root/'data/original.json').read_bytes(),before);self.assertEqual((self.root/'config/phase2.json').read_bytes(),config)
        self.assertEqual((self.root/'output/app.js').read_text(),'// retained old\n')
        self.assertEqual(json.loads((self.root/'DIAGNOSTIC_EXECUTION_SOURCE.json').read_bytes())['fixture_construction_source'],c.BASE)
    def test_changed_pull_requires_separate_decision(self):
        fp=self.fixture();(self.root/'pull/build.py').write_text('# different formula\n')
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            with self.assertRaisesRegex(RuntimeError,'model/static'):c.install_execution_source(self.code,self.root)
    def test_extra_executable_is_not_silently_retained(self):
        fp=self.fixture();(self.root/'tools/unknown.py').write_text('# unknown\n')
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            with self.assertRaisesRegex(RuntimeError,'extra executable'):c.install_execution_source(self.code,self.root)
    def test_nonactivation_config_difference_rejected(self):
        fp=self.fixture();(self.root/'config/unchanged.json').write_text('{"same":false}\n')
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            with self.assertRaisesRegex(RuntimeError,'configuration difference'):c.install_execution_source(self.code,self.root)
    def weekly_fixture(self):
        """Tiny Git/copy control; patched hash registry is not source qualification."""
        fp=self.fixture();registered={}
        for name in c.WEEKLY_EXECUTION_ADDITIONS:
            raw=('// fictional copy control\n' if name.endswith('.js') else '{"fictional_copy_control":true}\n').encode()
            path=self.code/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            registered[name]=c.sha(raw)
        c.git(self.code,'add','.');c.git(self.code,'commit','-qm','Wholly fictional registered-copy controls')
        fp['commit']=c.git(self.code,'rev-parse','HEAD');fp['tree']=c.git(self.code,'rev-parse','HEAD^{tree}')
        fp['files'] += [dict(path=name,mode='100644',bytes=(self.code/name).stat().st_size,
            sha256=registered[name],blob=c.git(self.code,'hash-object',str(self.code/name))) for name in registered]
        return fp,registered
    def test_weekly_absent_only_source_bound_additions_preserve_originals_and_are_committed(self):
        fp,registered=self.weekly_fixture();before=c._evidence_inventory(self.root);config=(self.root/'config/phase2.json').read_bytes()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp),patch.dict(c.WEEKLY_EXECUTION_ADDITIONS,registered),patch.object(c,'_install_weekly_registrations') as transport:
            c.install_execution_source(self.code,self.root);c.execution_identity(self.code,self.root,packaged=False)
            transport.assert_called_once_with(self.code,self.root,fp)
        self.assertEqual(c._evidence_inventory(self.root),before);self.assertEqual((self.root/'config/phase2.json').read_bytes(),config)
        tracked=set(c.git(self.root,'ls-tree','-r','--name-only','HEAD').splitlines())
        self.assertTrue(set(registered)<=tracked)
        self.assertEqual((self.root/'output/app.js').read_text(),'// retained old\n')
    def test_weekly_existing_different_policy_is_not_replaced(self):
        fp,registered=self.weekly_fixture();name='config/weekly-derived-selected-policy-v1.json'
        original=b'{"fictional_existing_different":true}\n';(self.root/name).write_bytes(original)
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp),patch.dict(c.WEEKLY_EXECUTION_ADDITIONS,registered),patch.object(c,'_install_weekly_registrations'):
            with self.assertRaisesRegex(RuntimeError,'configuration difference'):c.install_execution_source(self.code,self.root)
        self.assertEqual((self.root/name).read_bytes(),original)
    def test_weekly_changed_candidate_same_size_restored_mtime_is_not_copied(self):
        fp,registered=self.weekly_fixture();path=self.code/'config/weekly-derived-selected-policy-v1.json';info=path.stat()
        raw=bytearray(path.read_bytes());raw[0]^=1;path.write_bytes(raw);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp),patch.dict(c.WEEKLY_EXECUTION_ADDITIONS,registered),patch.object(c,'_install_weekly_registrations'):
            with self.assertRaisesRegex(RuntimeError,'configuration changed before copying'):c.install_execution_source(self.code,self.root)
        self.assertFalse((self.root/'config/weekly-derived-selected-policy-v1.json').exists())
    def test_weekly_installed_static_mutation_is_rejected_independently(self):
        fp,registered=self.weekly_fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp),patch.dict(c.WEEKLY_EXECUTION_ADDITIONS,registered),patch.object(c,'_install_weekly_registrations'):
            c.install_execution_source(self.code,self.root)
            path=self.root/'output/weekly-adaptive-overlay.js';info=path.stat();raw=bytearray(path.read_bytes());raw[0]^=1;path.write_bytes(raw);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError,'bytes differ'):c.execution_identity(self.code,self.root,packaged=False)
    def test_added_dependency_after_install_is_not_trusted(self):
        fp=self.fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root);(self.root/'tools/late.py').write_text('# changed inventory\n')
            with self.assertRaisesRegex(RuntimeError,'inventory changed'):c.execution_identity(self.code,self.root,packaged=False)
    def test_changed_config_after_install_is_not_trusted(self):
        fp=self.fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root);(self.root/'config/unchanged.json').write_text('{"same":false}\n')
            with self.assertRaisesRegex(RuntimeError,'configuration bytes'):c.execution_identity(self.code,self.root,packaged=False)
    def test_v3_marker_preserves_exact_original_git_roles(self):
        fp=self.fixture();original=(self.root/'config/phase2.json').read_bytes()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root)
            marker=c._source_marker(self.root)
            self.assertEqual(marker['schema_version'],'diagnostic-execution-source-v3')
            self.assertIsNone(marker['phase2_transition'])
            _,raw=c._seed_json(self.root,marker,'config/phase2.json')
            self.assertEqual(raw,original)
            # The original role is read from the pinned Git closure, even when
            # the later derived configuration is different.
            (self.root/'config/phase2.json').write_text('{"derived":true}\n')
            self.assertEqual(c._seed_json(self.root,marker,'config/phase2.json')[1],original)
            with self.assertRaisesRegex(RuntimeError,'Unsupported original seed role'):
                c._seed_json(self.root,marker,'data/unrelated.json')
            marker['prior_fixture_commit']=fp['commit']
            with self.assertRaisesRegex(RuntimeError,'differs from approved seed'):
                c._seed_json(self.root,marker,'config/phase2.json')
    def test_strict_v2_marker_reader_is_retained(self):
        fp=self.fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root)
            marker=c._source_marker(self.root);marker.pop('phase2_transition')
            marker['schema_version']='diagnostic-execution-source-v2'
            c.put(self.root/'DIAGNOSTIC_EXECUTION_SOURCE.json',marker)
            self.assertEqual(c.execution_identity(self.code,self.root,packaged=False),marker)
            marker['phase2_transition']=None;c.put(self.root/'DIAGNOSTIC_EXECUTION_SOURCE.json',marker)
            with self.assertRaisesRegex(RuntimeError,'Invalid versioned execution marker'):c._source_marker(self.root)
    def test_pending_plan_transition_stops_before_build(self):
        fp=self.fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root)
            (self.root/'output/app.js').write_bytes((self.code/'output/app.js').read_bytes())
            with self.assertRaisesRegex(RuntimeError,'transition required'):c.sample_capture(self.code,self.root,self.result)
    def test_unsupported_transition_descriptor_is_rejected(self):
        fp=self.fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root)
        marker=c._source_marker(self.root)
        for descriptor in ({'path':'other.json','bytes':1,'sha256':'a'*64},
                {'path':c.TRANSITION_PATH,'bytes':True,'sha256':'a'*64},
                {'path':c.TRANSITION_PATH,'bytes':1,'sha256':'a'*64,'pass':True}):
            marker['phase2_transition']=descriptor;c.put(self.root/'DIAGNOSTIC_EXECUTION_SOURCE.json',marker)
            with self.subTest(descriptor=descriptor),self.assertRaises(RuntimeError):c._source_marker(self.root)

    def _retry_control(self,completed=False):
        """Unit ordering scaffold; it does not qualify a real generation."""
        fp=self.fixture()
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            c.install_execution_source(self.code,self.root)
        (self.root/'output/app.js').write_bytes((self.code/'output/app.js').read_bytes())
        packaging=dict(schema_version='diagnostic-execution-packaging-v2',fixture_construction_source=c.BASE,
            candidate_commit=fp['commit'],generation='d'*64,original_capture_preserved=True)
        c.put(self.root/'DIAGNOSTIC_EXECUTION_PACKAGING.json',packaging)
        c.put(self.root/c.TRANSITION_PATH,{'unit':'retained transition bytes, not a qualification'})
        if completed:
            marker=c._source_marker(self.root);raw=(self.root/c.TRANSITION_PATH).read_bytes()
            marker['phase2_transition']={'path':c.TRANSITION_PATH,'sha256':c.sha(raw),'bytes':len(raw)}
            c.put(self.root/'DIAGNOSTIC_EXECUTION_SOURCE.json',marker)
            c.put(self.root/'config/phase2.json',{'unit':'derived configuration'})
        capture=SimpleNamespace(_manifest=lambda *a,**kw:({},{}),_git_archive=lambda *a,**kw:{},_public_archive_commit=lambda *args:None)
        return fp,packaging,{'capture':capture}

    def test_saved_packaging_helper_freshly_checks_generation_and_every_alias(self):
        import phase2_capture
        base=self.root/'output/data/selection-grading';base.mkdir(parents=True)
        c.put(base/'hosting.json',{'latest':{'unit':'saved descriptor'}})
        snapshots={name:(b'{}' if name.endswith('.json') else b'fictional static bytes')
            for name in phase2_capture.HOST_SNAPSHOTS}
        for name,raw in snapshots.items():
            path=self.root/'output'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        events=[];contexts=[];manifest={'generation_sha256':'d'*64}
        def registry(base,working,*,_checked):events.append('registry');contexts.append(_checked)
        def read(base,descriptor,*,root,_checked):
            self.assertIs(_checked,contexts[-1]);events.append('manifest');return manifest,snapshots
        capture=SimpleNamespace(_registry=registry,_manifest=read,HOST_SNAPSHOTS=phase2_capture.HOST_SNAPSHOTS,
            _same_generation_snapshot=phase2_capture._same_generation_snapshot)
        c._saved_packaging_identity(self.root,{'capture':capture},{'generation':'d'*64})
        for name in phase2_capture.HOST_SNAPSHOTS:
            path=self.root/'output'/name;path.write_bytes(b'{"changed":true}' if name.endswith('.json') else b'corrupt')
            with self.subTest(alias=name),self.assertRaisesRegex(RuntimeError,'aliases changed'):
                c._saved_packaging_identity(self.root,{'capture':capture},{'generation':'d'*64})
            path.write_bytes(snapshots[name])
        manifest['generation_sha256']='e'*64
        with self.assertRaisesRegex(RuntimeError,'Changed saved packaging'):
            c._saved_packaging_identity(self.root,{'capture':capture},{'generation':'d'*64})
        self.assertEqual(events,['registry','manifest']*(len(phase2_capture.HOST_SNAPSHOTS)+2))
        self.assertEqual(len({id(value) for value in contexts}),len(contexts))

    def _reject_corrupt_retry(self,completed):
        fp,_,m=self._retry_control(completed)
        base=self.root/'output/data/selection-grading';base.mkdir(parents=True)
        (base/'hosting.json').write_bytes(b'{"latest":')
        names=('config/phase2.json','DIAGNOSTIC_EXECUTION_SOURCE.json',c.TRANSITION_PATH,'data/original.json')
        before={name:(self.root/name).read_bytes() for name in names}
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp), \
                patch.object(c,'bind',return_value=m),patch.object(c,'external',return_value=contextlib.nullcontext()), \
                patch.object(c,'_transition_binding') as plan:
            with self.assertRaises(RuntimeError):c.transition_execution_plan(self.code,self.root)
            plan.assert_not_called()
        self.assertEqual({name:(self.root/name).read_bytes() for name in names},before)
        self.assertEqual(c.git(self.root,'diff','--cached','--name-only'),'')
        self.assertEqual(list((self.root/'data').rglob('*')), [self.root/'data/original.json'])

    def test_interrupted_transition_retry_rejects_corrupt_hosting_before_plan_writes(self):
        self._reject_corrupt_retry(False)

    def test_completed_transition_retry_rejects_corrupt_hosting_before_plan_writes(self):
        self._reject_corrupt_retry(True)

    def test_transition_commit_failure_restores_config_marker_and_only_owned_index(self):
        fp,_,m=self._retry_control(False)
        names=('config/phase2.json','DIAGNOSTIC_EXECUTION_SOURCE.json',c.TRANSITION_PATH,'data/original.json')
        before={name:(self.root/name).read_bytes() for name in names}
        target={'unit':'new derived configuration'}
        # Qualification is deliberately controlled here: this is an index and
        # file transaction test, never evidence of source/bundle acceptance.
        binding=c._decoded(before[c.TRANSITION_PATH]);actual_git=c.git
        def fail_commit(root,*args):
            if args and args[0]=='commit':
                staged=set(actual_git(root,'diff','--cached','--name-only').splitlines())
                self.assertTrue(staged)
                self.assertTrue(staged<={'config/phase2.json','DIAGNOSTIC_EXECUTION_SOURCE.json',c.TRANSITION_PATH})
                raise RuntimeError('intentional unit commit failure after staging')
            return actual_git(root,*args)
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp), \
                patch.object(c,'bind',return_value=m),patch.object(c,'external',return_value=contextlib.nullcontext()), \
                patch.object(c,'_saved_packaging_identity'),patch.object(c,'execution_identity'), \
                patch.object(c,'_transition_binding',return_value=(target,before['config/phase2.json'],binding)), \
                patch.object(c,'git',side_effect=fail_commit):
            with self.assertRaisesRegex(RuntimeError,'intentional unit commit failure'):
                c.transition_execution_plan(self.code,self.root)
        self.assertEqual({name:(self.root/name).read_bytes() for name in names},before)
        self.assertEqual(c.git(self.root,'diff','--cached','--name-only'),'')
    def test_legacy_builder_dependency_is_unchanged(self):
        self.assertEqual(c.sha((DEPENDENCY_ROOT/'tools/operating_diagnostic.py').read_bytes()),c.SEED_HARNESS_SHA256)
        integrity=json.loads((DEPENDENCY_ROOT/'tools/cloud-seed-integrity.json').read_bytes())
        self.assertEqual(integrity['files']['operating_diagnostic.py'],c.SEED_HARNESS_SHA256)
    def test_campaign_and_source_ci_workflows_are_distinct(self):
        import source_ci
        self.assertNotEqual(c.CAMPAIGN_WORKFLOW,source_ci.WORKFLOW_PATH)

    def test_invalid_runtime_does_not_use_seed_version_fallback(self):
        with self.assertRaisesRegex(RuntimeError,'runtime'):c._runtime_identity({'unit':'fictional'})
        env={'python':{'version':'3.12.15'},'node':{'version':'22.23.3'},'distributions':[{'name':'certifi','version':'2026.10.19'}]}
        self.assertEqual(c._runtime_identity(env)['distributions'][0]['version'],'2026.10.19')
    def test_flat_bytecode_and_native_extras_are_not_ignored(self):
        self.fixture()
        for name in ('tools/active.pyc','tools/active.so'):
            (self.root/name).write_bytes(b'not executable')
        actual=c._installed_names(self.root,('tools',))
        self.assertIn('tools/active.pyc',actual);self.assertIn('tools/active.so',actual)
    def test_inventory_prunes_data_before_descending(self):
        self.fixture();(self.root/'output/data/irrelevant-link').symlink_to('/nonexistent')
        self.assertEqual(c._installed_names(self.root,('output',)),{'output/app.js','output/index.html'})
    def test_directory_and_symlink_budgets_are_enforced(self):
        self.fixture();(self.root/'tools/extra').mkdir()
        with patch.object(c,'ENTRY_LIMIT',1):
            with self.assertRaisesRegex(RuntimeError,'inventory'):c._installed_names(self.root,('tools',))
        (self.root/'tools/linked').symlink_to(self.code/'pull/build.py')
        with self.assertRaisesRegex(RuntimeError,'Symlink'):c._installed_names(self.root,('tools',))
    def test_strict_bounded_duplicate_nonfinite_and_file_types(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'[]'):
            self.result.write_bytes(raw)
            with self.assertRaises(RuntimeError):c._load(self.result)
        self.result.write_bytes(b'x'*64)
        with self.assertRaises(RuntimeError):c._bounded_file(self.result,16)
        self.result.unlink();self.result.symlink_to(self.code)
        with self.assertRaises(OSError):c._bounded_file(self.result)
    def test_early_resource_failure_stops_all_online_work(self):
        with patch.object(c,'_job_context'),patch.object(c,'_resource_preflight',side_effect=RuntimeError('HOSTED_PREFLIGHT_REQUIRED')),patch.object(c,'_source_ci_cli') as online:
            with self.assertRaisesRegex(RuntimeError,'HOSTED_PREFLIGHT_REQUIRED'):c.launch_job(self.code,self.root,self.result,1)
            online.assert_not_called()
        self.assertEqual(c._load(self.result)['failure_class'],'RuntimeError')
    def test_unknown_transport_is_not_replaced_with_git_route(self):
        self.assertNotIn("elif a.action=='retrieve'",(HERE/'tools/operating_campaign.py').read_text())

    def test_original_failure_is_preserved_and_failed_fixture_is_not_deleted(self):
        code=HERE;work=self.base/'nfl-operating-1';root=work/'fixture';result=work/'RESULT.json'
        fp=dict(self.fp);fp['files']=[dict(path='tools/operating_campaign.py',sha256='a'*64)]
        proof=dict(self.proof)
        def command(*a,**kw):
            root.mkdir();(root/'retained-failure.txt').write_text('fictional failure retained')
            raise ValueError('original-stage-error')
        monitor=SimpleNamespace(start=lambda:None,finish=lambda:(_ for _ in ()).throw(OSError('monitor-error')))
        env={'RUNNER_TEMP':str(self.base),'DIAGNOSTIC_RESOURCE_BACKEND':'root-supervised-cgroup-v1',
            'CAMPAIGN_ID':c.CAMPAIGN,'GITHUB_ACTOR_ID':'208912933','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
            'OPERATING_ARTIFACT_APPROVAL_SHA256':'b'*64}
        with patch.dict(os.environ,env),patch.object(c,'_job_context'),patch.object(c,'require_offline'),patch.object(c,'_hash_file',return_value='a'*64),patch.object(c,'_critical_paths',return_value=[]),patch.object(c,'Resources',return_value=monitor),patch.object(c,'_source_ci_cli',return_value=fp),patch.object(c,'_guarded_stage',side_effect=command):
            with self.assertRaisesRegex(ValueError,'original-stage-error'):
                c.job(code,root,result,1,_operation=(proof,fp,c.time.monotonic(),{},{}))
        self.assertTrue((root/'retained-failure.txt').is_file())
        recorded=c._load(result)
        self.assertEqual(recorded['failure_class'],'ValueError')
        self.assertEqual(recorded['retention']['status'],'FAILED_WORKSPACE_RETAINED_NO_EXPORT')
        self.assertIn('monitor:OSError',recorded['finalization_errors'])

    def test_fresh_prefix_reaches_actual_child_before_startup(self):
        self.code.mkdir();(self.code/'tools').mkdir()
        (self.code/'tools/source_ci.py').write_text('import json,sys,os;print(json.dumps(dict(prefix=sys.pycache_prefix,no_write=sys.dont_write_bytecode,mode=os.stat(sys.pycache_prefix).st_mode&511)))')
        with patch.object(c.Path,'cwd',return_value=self.code),patch.dict(os.environ,{'RUNNER_TEMP':str(self.base)}):
            result=c._source_ci_cli(self.code,'fingerprint')
        self.assertTrue(result['no_write']);self.assertEqual(result['mode'],0o700)
        self.assertFalse(Path(result['prefix']).exists())
    def test_stage_log_is_bounded_without_limiting_child_assets(self):
        log=self.base/'bounded.log'
        c._bounded_stage([sys.executable,'-c','import sys;sys.stdout.write("x"*100000)'],self.base,log,5,log_limit=1024)
        self.assertEqual(log.stat().st_size,1024)
        with self.assertRaises(subprocess.CalledProcessError):
            c._bounded_stage([sys.executable,'-c','raise SystemExit(7)'],self.base,self.base/'failed.log',5)

    def test_derived_configuration_is_bound_to_actual_saved_seed_manifest(self):
        fp=self.fixture();(self.root/'config/phase2.json').write_text('{"fictional":"changed"}')
        with patch.object(c,'require_offline'),patch.object(c,'_source_ci_cli',return_value=fp):
            with self.assertRaisesRegex(RuntimeError,'approved frozen seed'):c.install_execution_source(self.code,self.root)
    def test_seed_manifest_cannot_be_rehashed_by_caller_without_approved_digest(self):
        self.fixture();path=self.root.parent/'retrieved-seed/SEED_MANIFEST.json'
        value=c._load(path);value['files']['config/phase2.json']['sha256']='f'*64;path.write_bytes(c.encoded(value))
        with self.assertRaisesRegex(RuntimeError,'manifest changed'):c._frozen_seed_manifest(self.root)

    def test_actual_guard_denies_child_and_grandchild_and_scrubs_credentials(self):
        log=self.base/'network-controls.log'
        with patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'GH_TOKEN':'fictional-not-a-token'}):
            c._guarded_stage(HERE,[sys.executable,'-c',"import os;assert not os.environ.get('GH_TOKEN');assert not os.environ.get('GITHUB_TOKEN')"],log,15)
            self.assertEqual(os.environ['GH_TOKEN'],'fictional-not-a-token')
        facts=json.loads(log.read_text().splitlines()[0]);self.assertEqual(facts['network_isolation'],'PASS')
        self.assertIn('python_grandchild',facts['controls']);self.assertEqual(facts['provider_contacts'],0)
    def test_three_fixed_source_ci_boundaries_surround_commit_pages_and_tar(self):
        code=HERE;work=self.base/'nfl-operating-1';root=work/'fixture';result=work/'RESULT.json';events=[]
        fp=dict(self.fp);fp['files']=[dict(path='tools/operating_campaign.py',sha256='a'*64)]
        monitor=SimpleNamespace(start=lambda:None,finish=lambda:{'resource_verdict':'UNKNOWN'})
        def child(code,argv,*a,**kw):
            action=argv[2];events.append(action)
            if action=='restore':root.mkdir()
            if action=='admit':(work/'admission.json').write_bytes(c.encoded({'status':'ADMITTED'}))
        def cli(code,action,run_id=None):
            if action=='verify':self.assertEqual(run_id,123);events.append('online-check');return dict(self.proof)
            return fp
        env={'RUNNER_TEMP':str(self.base),'DIAGNOSTIC_RESOURCE_BACKEND':'root-supervised-cgroup-v1','CAMPAIGN_ID':c.CAMPAIGN,
            'GITHUB_ACTOR_ID':'208912933','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','OPERATING_ARTIFACT_APPROVAL_SHA256':'b'*64,'GH_TOKEN':'fictional'}
        with patch.dict(os.environ,env),patch.object(c,'_job_context'),patch.object(c,'_hash_file',return_value='a'*64),patch.object(c,'_critical_paths',return_value=[]),patch.object(c,'Resources',return_value=monitor),patch.object(c,'_source_ci_cli',side_effect=cli),patch.object(c,'_guarded_stage',side_effect=child):
            report=c.job(code,root,result,1,_operation=(dict(self.proof),fp,c.time.monotonic(),{},{}))
        self.assertEqual(events[-5:],['capture-stage','online-check','commit-stage','online-check','tar-stage'])
        self.assertEqual(set(report['source_ci_boundaries']),{'initial','before_data_commit','after_pages_stage'})
    def test_actual_advisory_scripts_keep_continue_on_error_and_health_outcomes(self):
        (self.root/'output/data').mkdir(parents=True);(self.root/'output/data/health.json').write_text('{}')
        def script(path,args,clock):
            self.assertEqual(clock,'fictional-clock')
            if str(path).endswith('verify.py'):raise SystemExit(1)
        with patch.object(c,'_advisory_script',side_effect=script):
            result=c._advisories(self.root,{'capture':SimpleNamespace(datetime='fictional-clock')},None)
        self.assertEqual(result['outcomes']['legacy_verifier']['returncode'],1)
        self.assertEqual(c._load(self.root/'output/data/health.json'),{'legacy_verifier':'failure','historical_comparison':'success'})

    def evidence(self):
        categorical=set(c.seed_v1.REQUIRED_SETS)|{'outcome_revisions','original_contexts','recorders_inactive','original_schema','corrected_schema','archives','scope_schema','original_comparator'}
        return {'final_candidate_workload':c._public_final_workload(final_workload_control()),'advisories':{'outcomes':{'legacy_verifier':{'outcome':'failure','returncode':1},'historical_comparison':{'outcome':'success','returncode':0}},'remote_continuation':'UNMEASURED','unsupported_raw_http_calls':2},'admission':{'numeric_floors':{k:{'actual':v,'required':v,'meets':True} for k,v in c.seed_v1.ENVELOPE.items()},
            'categorical':{k:True for k in categorical},'population_pass':True,'game_states':{'post':2,'in':7,'pre':5},
            'qualification_counts':{'retained_legacy_original_proof_missing':9,'new_pregame_original_inputs_verified':5},
            'public_semantics_sha256':'a'*64,'original_file_sha256':'b'*64},
            'correction':{'before':3,'after':8,'expected_affected_count':2,'actual_changed_count':2,'original_outcome_count':5,'new_outcome_count':6,
            'expected_set_sha256':'c'*64,'declaration_sha256':'d'*64,'original_file_sha256':'e'*64}}
    def test_derived_admission_floors_are_recomputed_not_flag_only(self):
        value=self.evidence();c._check_evidence_projection(value)
        value['admission']['numeric_floors']['rows']['actual']=0
        with self.assertRaisesRegex(RuntimeError,'floor'):c._check_evidence_projection(value)

    def measurement_fixture(self):
        leaf='/sys/fs/cgroup/system.slice/nfl-operating-123-1.service/nfl-diagnostic-123-1-99'
        measured=dict(status='COMPLETE',complete_tree=True,peak_reset_verified=True,scope_closure_verified=True,
            privilege_drop_verified=True,failures=[],returncode=0,minimum_free_bytes=2*1024**3,minimum_free_fraction=.2,
            resource_verdict='PASS',supervisor_seconds=12,run_id=123,sample=1,source='1'*40,harness_sha256=c.SEED_HARNESS_SHA256,
            seed_manifest_sha256='b'*64,kernel_peaks={leaf:{'kernel_peak':4*1024**3,'limit':16*1024**3}},
            event_deltas={leaf:{'oom':0,'oom_kill':0,'oom_group_kill':0}},
            filesystem_minima={'1':{'free':10*1024**3,'total':20*1024**3,'paths':['/private/path']}})
        fp=dict(self.fp);fp['files']=[{'path':'tools/operating_campaign.py','sha256':'a'*64,'bytes':10}]
        report=dict(status='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING',run_id=123,run_attempt=1,sample=1,
            source='1'*40,source_tree='2'*40,source_manifest_sha256='3'*64,source_ci=dict(self.proof),
            source_ci_boundaries={k:dict(self.proof) for k in ('initial','before_data_commit','after_pages_stage')},
            harness_sha256='a'*64,fixture_harness_sha256=c.SEED_HARNESS_SHA256,fixture_construction_source=c.BASE,
            seed_manifest_sha256='b'*64,dependency_hashes={k:'a'*64 for k in c.DEPENDENCIES},
            runtime=c._runtime_identity(fp['environment']),environment_sha256=self.proof['environment_sha256'],
            stages={},harness_wall_seconds=12,failure_class=None,retention={'status':'SUCCESS_JOB_COPY_CLEANED_ORIGINAL_SEED_UNCHANGED'},
            capability_before_online={'current':leaf,'filesystems':{'1':{}}},worker_argv=['actual','worker'],transport_approval_sha256='c'*64)
        files={'tools/operating_campaign.py':{'sha256':'a'*64,'bytes':10}}
        outer=dict(schema_version='operating-root-execution-v1',mode='campaign',purpose='operating',root_uid=0,worker_uid=1001,
            run_id=123,sample=1,run_attempt=1,repository='NickNicky19/nicks-expert-nfl-picks',repository_id=1411185749,
            actor_id=208912933,event='workflow_dispatch',branch='upgrade/phase2-reproducible-comparison',workflow_path=c.CAMPAIGN_WORKFLOW,
            source={'commit':'1'*40,'tree':'2'*40,'files':files,'source_closure_sha256':c.sha(c.encoded(files))},
            resource_p5_harness_sha256=c.SEED_HARNESS_SHA256,resource_report={'sha256':c.sha(c.encoded(measured)),'bytes':len(c.encoded(measured))},
            worker_argv=report['worker_argv'],worker_argv_sha256=c.sha(c.encoded(report['worker_argv'])),
            supervisor_argv=['supervisor','--',*report['worker_argv']],resource_supervisor_returncode=0,resource_supervisor_pid=99,
            cgroup={'unit':'nfl-operating-123-1.service','scopes':[{'path':'/sys/fs/cgroup'},{'path':str(Path(leaf).parent)},{'path':'supervisor'}]},
            monitored_leaf_path=leaf,complete_tree=True,privilege_drop_verified=True,
            status='COMPLETE_RESOURCE_REVIEW_STILL_REQUIRES_JOB_TIMESTAMPS',resource_verdict='PASS',transport_approval={'sha256':'c'*64})
        outer['supervisor_argv_sha256']=c.sha(c.encoded(outer['supervisor_argv']))
        return measured,outer,report,fp
    def test_in_run_projection_is_numeric_derived_and_omits_private_paths(self):
        measured,outer,report,fp=self.measurement_fixture();work=self.base/'nfl-operating-1';work.mkdir();root=work/'fixture';result=work/'RESULT.json'
        result.write_bytes(c.encoded(report))
        records=[(measured,{'sha256':c.sha(c.encoded(measured)),'bytes':len(c.encoded(measured))}),(outer,{'sha256':'d'*64,'bytes':100})]
        with patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'GITHUB_RUN_ID':'123','GITHUB_SHA':'1'*40,'GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch','SEED_MANIFEST_SHA256':'b'*64}),patch.object(c,'_protected_report',side_effect=records),patch.object(c,'_evidence_aggregates',return_value=self.evidence()),patch.object(c,'_source_ci_cli',return_value=fp),patch.object(c,'_hash_file',return_value='a'*64):
            projection=c.project(self.code,root,result,1)
        self.assertEqual(projection['resources'],'PASS');self.assertTrue(all(projection['checks'].values()))
        self.assertNotIn('/private/path',c.encoded(projection).decode());self.assertNotIn('/sys/fs/cgroup',c.encoded(projection).decode())
        self.assertEqual(projection['claim'],'DERIVED_MEASUREMENTS_NOT_ORIGINAL_RECORD_BYTES')
    def test_failed_final_workload_projects_actual_counts_without_qualifying(self):
        measured,outer,report,fp=self.measurement_fixture();work=self.base/'nfl-operating-1';work.mkdir();root=work/'fixture';result=work/'RESULT.json'
        report['status']='FAIL';report['failure_class']='RuntimeError';result.write_bytes(c.encoded(report))
        final=final_workload_control();final['metrics']['groups']=12;final['decisions']=c._final_workload_decisions(final)
        final['applicability']=c._final_applicability(final)
        c.put(work/'dataflow.json',{'final_candidate_workload':final})
        records=[(measured,{'sha256':c.sha(c.encoded(measured)),'bytes':len(c.encoded(measured))}),(outer,{'sha256':'d'*64,'bytes':100})]
        with patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'GITHUB_RUN_ID':'123','GITHUB_SHA':'1'*40,'GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch','SEED_MANIFEST_SHA256':'b'*64}),patch.object(c,'_protected_report',side_effect=records),patch.object(c,'_source_ci_cli',return_value=fp),patch.object(c,'_hash_file',return_value='a'*64):
            value=c.project(self.code,root,result,1)
        self.assertEqual(value['status'],'FAIL');self.assertIsNone(value['workload_evidence'])
        self.assertEqual(value['final_candidate_workload']['metrics']['groups'],12)
        self.assertFalse(value['final_candidate_workload']['decisions']['admitted'])
        self.assertLessEqual(len(c.encoded(value)),64*1024)

    def test_full_permitted_typed_cohort_projection_remains_bounded_once(self):
        measured,outer,report,fp=self.measurement_fixture();work=self.base/'nfl-operating-1';work.mkdir();root=work/'fixture';result=work/'RESULT.json';result.write_bytes(c.encoded(report))
        final=final_workload_control();final['accuracy']=c._accuracy_workload(permitted_accuracy_control())
        ids=sorted(c.sha(c.encoded(['unit-context-boundary',i])) for i in range(512))
        final['metrics']['contexts']=len(ids);final['contexts'].update(ids=ids,missing_reference_ids=sorted(c.FINAL_REFERENCE_CONTEXT_IDS-set(ids)),extra_reference_ids=sorted(set(ids)-c.FINAL_REFERENCE_CONTEXT_IDS))
        final['decisions']=c._final_workload_decisions(final);final['applicability']=c._final_applicability(final)
        evidence=self.evidence();evidence['final_candidate_workload']=c._public_final_workload(final)
        records=[(measured,{'sha256':c.sha(c.encoded(measured)),'bytes':len(c.encoded(measured))}),(outer,{'sha256':'d'*64,'bytes':100})]
        with patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'GITHUB_RUN_ID':'123','GITHUB_SHA':'1'*40,'GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch','SEED_MANIFEST_SHA256':'b'*64}),patch.object(c,'_protected_report',side_effect=records),patch.object(c,'_evidence_aggregates',return_value=evidence),patch.object(c,'_source_ci_cli',return_value=fp),patch.object(c,'_hash_file',return_value='a'*64):
            value=c.project(self.code,root,result,1)
        self.assertEqual(value['status'],'LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING')
        self.assertIsNone(value['final_candidate_workload']) # no duplicate success payload.
        self.assertLessEqual(len(c.encoded(value)),64*1024)
        self.assertEqual(value['workload_evidence']['final_candidate_workload']['private_metrics_sha256'],c.sha(c.encoded(final)))

    def project_stage_control(self,stages):
        # Actual projector with controlled source/root measurement inputs;
        # never evidence that a resource backend or hosted workload ran.
        measured,outer,report,fp=self.measurement_fixture()
        work=self.base/'nfl-operating-1';work.mkdir()
        root=work/'fixture';result=work/'RESULT.json'
        report['stages']=stages;result.write_bytes(c.encoded(report))
        records=[(measured,{'sha256':c.sha(c.encoded(measured)),'bytes':len(c.encoded(measured))}),
                 (outer,{'sha256':'d'*64,'bytes':100})]
        with patch.dict(os.environ,{'RUNNER_TEMP':str(self.base),'GITHUB_RUN_ID':'123',
                'GITHUB_SHA':'1'*40,'GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch',
                'SEED_MANIFEST_SHA256':'b'*64}),patch.object(c,'_protected_report',side_effect=records), \
                patch.object(c,'_evidence_aggregates',return_value=self.evidence()), \
                patch.object(c,'_source_ci_cli',return_value=fp),patch.object(c,'_hash_file',return_value='a'*64):
            return c.project(self.code,root,result,1)
    def test_complete_declared_job_stages_project_including_plan_transition(self):
        names=('resource_capability','transport_allocation_admission','restoration_allocation_admission',
            'seed_retrieval','source_ci_online','source_ci_private_binding','network_isolation',
            'source_ci_isolated_entry','seed_restoration','workload_admission','execution_source_install',
            'execution_saved_packaging','execution_fictional_plan_transition','retained_cheap_checks',
            'capture_and_advisories','source_ci_before_data_commit','local_commit_and_pages_stage',
            'source_ci_after_pages_stage','uploader_tar','source_ci_isolated_final','cleanup')
        stages={n:dict(start=i,end=i+.5,seconds=.5) for i,n in enumerate(names)}
        value=self.project_stage_control(stages)
        self.assertEqual(value['status'],'LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING')
        self.assertEqual(value['stages'],stages)
        self.assertTrue(all(value['checks'].values()))
    def test_unknown_stage_is_not_accepted_as_supported_transition(self):
        value=self.project_stage_control({'unapproved_plan_transition':dict(start=0,end=1,seconds=1)})
        self.assertEqual(value['status'],'PROJECTION_INCOMPLETE')
        self.assertEqual(value['resources'],'UNKNOWN')
    def test_supported_transition_cannot_project_malformed_measurements(self):
        value=self.project_stage_control({'execution_fictional_plan_transition':dict(start=0,end=1,seconds='1')})
        self.assertEqual(value['status'],'PROJECTION_INCOMPLETE')
        self.assertEqual(value['resources'],'UNKNOWN')
    def test_changed_root_binding_cannot_project_resource_pass(self):
        measured,outer,report,fp=self.measurement_fixture();outer['worker_argv_sha256']='0'*64
        self.assertFalse(c._resource_binding(measured,outer,report,123,1,'1'*40))
        measured['failures']=['/private/not-a-code']
        with self.assertRaises(RuntimeError):c._measurements(measured)
    def test_actual_log_assessment_recomputes_three_samples_and_rejects_duplicate(self):
        import copy
        measured,outer,report,fp=self.measurement_fixture();facts=c._measurements(measured)
        stage_names={'resource_capability','transport_allocation_admission','restoration_allocation_admission','seed_retrieval','source_ci_online','source_ci_private_binding','network_isolation',
            'source_ci_isolated_entry','seed_restoration','workload_admission','execution_source_install','execution_saved_packaging','execution_fictional_plan_transition',
            'retained_cheap_checks','capture_and_advisories','source_ci_before_data_commit','local_commit_and_pages_stage',
            'source_ci_after_pages_stage','uploader_tar','source_ci_isolated_final','cleanup'}
        stages={k:{'start':i,'end':i+.5,'seconds':.5} for i,k in enumerate(sorted(stage_names))}
        proof=copy.deepcopy(self.proof);sealed={k:proof[k] for k in ('run_id','run_attempt','job_id','seal_sha256','environment_sha256')}
        approval=dict(schema_version='operating-campaign-approval-v1',campaign=c.CAMPAIGN,repository='NickNicky19/nicks-expert-nfl-picks',repository_id=1411185749,
            run_id=123,head_sha='1'*40,workflow_id=99,workflow_path=c.CAMPAIGN_WORKFLOW,actor_id=208912933,attempt=1,seed_manifest_sha256='b'*64,
            wrapper_sha256='a'*64,dependency_hashes=report['dependency_hashes'],source_manifest_sha256='3'*64,source_ci_identity=sealed,runtime_environment_sha256=proof['environment_sha256'])
        self.result.write_bytes(c.encoded(approval));run=dict(id=123,head_sha='1'*40,workflow_id=99,path=c.CAMPAIGN_WORKFLOW,event='workflow_dispatch',run_attempt=1,status='completed',
            head_branch='upgrade/phase2-reproducible-comparison',actor={'id':208912933},repository={'id':1411185749},conclusion='success',created_at='2026-10-22T00:00:00Z',run_started_at='2026-10-22T00:00:01Z')
        jobs=[];logs={}
        for n in (1,2,3):
            jobs.append(dict(id=n,name='Operating sample '+str(n),status='completed',run_id=123,head_sha='1'*40,conclusion='success',
                started_at=f'2026-10-22T00:{n:02}:00Z',completed_at=f'2026-10-22T00:{n:02}:30Z'))
            projection=dict(schema_version='operating-measurement-projection-v1',claim='DERIVED_MEASUREMENTS_NOT_ORIGINAL_RECORD_BYTES',run_id=123,run_attempt=1,sample=n,source='1'*40,source_tree='2'*40,
                status=report['status'],source_ci=proof,source_ci_boundary_count=3,environment_sha256=proof['environment_sha256'],seed_manifest_sha256='b'*64,
                wrapper_sha256='a'*64,dependency_hashes=report['dependency_hashes'],source_manifest_sha256='3'*64,
                fixture_harness_sha256=c.SEED_HARNESS_SHA256,fixture_construction_source=c.BASE,harness_wall_seconds=len(stage_names),stages=stages,
                workload_evidence=self.evidence(),checks={k:True for k in ('fresh_source_ci_binding','root_record_source_bytes','root_execution_and_resource_binding','protected_original_records','resource_measurements_recomputed')},resource_measurements=facts)
            logs[n]=b'2026-10-22T00:00:01Z NFL_OPERATING_MEASUREMENT '+c.encoded(projection)+b'\n'
        inventory={'total_count':3,'jobs':jobs}
        def get(route,logs=False):
            if route.endswith('/logs'):return log_records[int(route.split('/')[3])]
            return inventory if '/jobs?' in route else run
        log_records=logs;api=SimpleNamespace(get=get);out=self.base/'assessment.json'
        value=c.assess(self.result,out,api=api);self.assertEqual(value['operating'],'PASS_FICTIONAL_COMPUTE_ONLY')
        original_log=log_records[1]
        unqualified=json.loads(original_log.decode().split('NFL_OPERATING_MEASUREMENT ',1)[1])
        final=final_workload_control()
        for capture in final['accuracy']['capture_coverage']:capture['capture_coverage']['unique_receipts']=277
        final['applicability']=c._final_applicability(final)
        unqualified['workload_evidence']['final_candidate_workload']=c._public_final_workload(final)
        log_records[1]=b'NFL_OPERATING_MEASUREMENT '+c.encoded(unqualified)+b'\n'
        unmatched=c.assess(self.result,out,api=api)
        self.assertEqual(unmatched['operating'],'NOT_QUALIFIED')
        self.assertEqual(unmatched['samples'][0]['planning'],'PASS')
        self.assertEqual(unmatched['samples'][0]['resources'],'PASS')
        self.assertEqual(unmatched['samples'][0]['applicability'],'UNKNOWN_ADDITIONAL_MATCHED_REAL_CASE_REQUIRED')
        log_records[1]=original_log
        log_records[1]+=log_records[1]
        failed=c.assess(self.result,out,api=api);self.assertEqual(failed['operating'],'NOT_QUALIFIED')
        self.assertEqual(len(failed['samples']),3);self.assertEqual(failed['samples'][0]['resources'],'UNKNOWN')
        log_records[1]=b''
        missing=c.assess(self.result,out,api=api);self.assertEqual(len(missing['samples']),3)
        self.assertEqual(missing['samples'][0]['failure'],'MEASUREMENT_RECORD_MISSING')
        log_records[1]=b'NFL_OPERATING_MEASUREMENT {corrupt-json}\n'
        corrupt=c.assess(self.result,out,api=api);self.assertEqual(len(corrupt['samples']),3)
        self.assertEqual(corrupt['operating'],'NOT_QUALIFIED')

    def test_no_seed_capability_projection_never_claims_operating_or_drop_pass(self):
        measured,outer,report,fp=self.measurement_fixture()
        measured.update(status='CAPABILITY_READY',complete_tree=True,resource_verdict='NOT_RUN_CAPABILITY_ONLY',
            capability={'filesystems':{'1':{'free':10*1024**3,'total':20*1024**3}},'ancestor_limits':{'private':'17179869184'}})
        outer.update(mode='capability',status='CAPABILITY_READY',resource_verdict='NOT_RUN_CAPABILITY_ONLY',worker_argv=None,
            seed_manifest_sha256=None,transport_approval='NOT_REQUIRED_CAPABILITY_ONLY',resource_report={'sha256':c.sha(c.encoded(measured)),'bytes':len(c.encoded(measured))})
        value=c._capability_projection(measured,outer,fp,123,1)
        self.assertEqual(value['resources'],'NOT_RUN_CAPABILITY_ONLY');self.assertFalse(value['capability']['privilege_drop_tested'])
        outer['seed_manifest_sha256']='a'*64
        with self.assertRaises(RuntimeError):c._capability_projection(measured,outer,fp,123,1)

class TransitionValues(unittest.TestCase):
    """Actual value validators; not a full fixture, registration or admission."""
    def setUp(self):
        import data_integrity_v2 as api
        import partial_week
        import reliability as rel
        import source_evidence
        self.api,self.rel=api,rel
        # This value-builder control intentionally retains its original model.
        # Supply that model's actual checked source, never current Classic bytes
        # under the old identity. No new helper file or forecast is introduced.
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.source_root=Path(self.temporary.name)
        source=api.RETAINED_CORRECTED_SOURCE
        api._source_commit(HERE,source)
        self.assertEqual(api._git(HERE,'rev-parse',source+'^{tree}').decode().strip(),api.RETAINED_CORRECTED_TREE)
        for name,expected in api.source_hashes(api.MODEL).items():
            raw=api._source_file(HERE,source,name)
            self.assertEqual(c.sha(raw),expected)
            target=self.source_root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        self.assertEqual(api.active_model(self.source_root),api.MODEL)
        self.at=c._transition_clock();self.source='0'*40
        provider=c.Provider({},c.seed_v1.SMALL,self.at)
        games=[dict(id=f'99202606{index:02}',home=f'F{index*2:02}',away=f'F{index*2+1:02}',
            kickoff=rel.stamp(provider.kick(2026,6,index))) for index in range(14)]
        self.board=dict(season=2026,week=6,generated_at=rel.stamp(c.START+c.timedelta(hours=c.SEED_HOUR,seconds=120)),
            games=games,players=[],picks={'over':[],'under':[]})
        plan=dict(schema_version=api.PLAN,plan_id='FICTIONAL_DIAGNOSTIC_V2',model=api.MODEL,season=2026,week=6,
            plan_prepared_at=rel.stamp(c.START+c.timedelta(hours=c.SEED_HOUR)),
            effective_not_before=rel.stamp(c.START+c.timedelta(hours=c.SEED_HOUR)),
            expires_at=rel.stamp(c.START+c.timedelta(hours=c.SEED_HOUR,days=3)),
            validator_contract=api.VALIDATOR,engine_files=copy.deepcopy(api.V2_SOURCE_SHA256),
            initial_complete_board_sha256=rel.digest(self.board),games=copy.deepcopy(games),
            legacy_exemptions=[dict(game_id=g['id'],forecast_contract_sha256=rel.digest(partial_week.game_contract(self.board,g['id'])),
                reason='FICTIONAL_UNRECORDED_LEGACY_NOT_REAL_EXEMPTION') for g in games[:9]],
            completion_status_max_age_seconds=60,full_board_verified=False,complete_week_qualified=False,experimental_recording_enabled=False)
        self.original=dict(capture_enabled=True,challenger_production_enabled=False,experimental_recording_enabled=False,
            production_model=api.MODEL,verification_mode=api.VALIDATOR,partial_week=dict(plan=plan,plan_sha256=rel.digest(plan),
            validator_sha256=api.RETAINED_CORRECTED_HELPERS['tools/data_integrity_v2.py'],
            owner_authorization='FICTIONAL_ONLY_NOT_A_REAL_ACTIVATION'))
        self.status=source_evidence.record_scoreboard(provider.scoreboard(2026,6),dict(dates=2026,week=6,seasontype=2),self.at)
    def derive(self):return c._transition_spec(self.original,self.board,self.status,self.source,root=self.source_root)[0]
    def rehash(self):self.original['partial_week']['plan_sha256']=self.rel.digest(self.original['partial_week']['plan'])
    def test_fixed_clocks_and_preserved_predecessor_fields(self):
        before=copy.deepcopy(self.original);result=self.derive();old=before['partial_week'];new=result['partial_week']
        self.assertEqual(self.original,before)
        for name in ('expires_at','games','legacy_exemptions','engine_files','model','validator_contract'):
            self.assertEqual(new['plan'][name],old['plan'][name])
        self.assertEqual(new['validator_sha256'],self.api.code_sha256())
        self.assertNotEqual(new['plan_sha256'],old['plan_sha256'])
        self.assertEqual(new['plan']['previous_plan_sha256'],old['plan_sha256'])
        self.assertEqual(new['plan']['source_start'],self.source)
        self.assertEqual(self.rel.utc(new['plan']['effective_not_before']),self.at)
        self.assertEqual((c.START+c.timedelta(hours=77,seconds=c.seed_v1.SAMPLE_SECONDS))-self.at,c.timedelta(seconds=5))
    def test_deterministic_new_plan_and_exact_control_population(self):
        self.assertEqual(self.derive(),self.derive())
        value=self.derive();self.assertEqual(len(value['partial_week']['plan']['games']),14)
        self.assertEqual(len(value['partial_week']['plan']['legacy_exemptions']),9)
        self.assertEqual({s:sum(g['state']==s for g in self.status['games'].values()) for s in ('post','in','pre')},
            {'post':2,'in':7,'pre':5})
    def test_packaging_clock_follows_full_seed_without_rewriting_original_times(self):
        packaged=c._packaging_clock()
        self.assertEqual(packaged,c.START+c.timedelta(hours=77,seconds=125))
        for generations in (2,24):
            self.assertGreater(packaged,c.START+c.timedelta(hours=77,seconds=5*generations))
        self.assertLess(packaged,self.at)
        self.assertLess(self.at,c.START+c.timedelta(hours=77,seconds=c.seed_v1.SAMPLE_SECONDS))
    def test_packaging_rejects_equal_or_later_saved_publication_before_provider_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);c.put(root/'FICTIONAL_ONLY.json',{'dimensions':{}})
            for delta in (0,1):
                c.put(root/'output/data/selection-grading/latest.json',{'generated_at':self.rel.stamp(c._packaging_clock()+c.timedelta(seconds=delta))})
                with patch.object(c,'require_offline'),patch.object(c,'execution_identity'), \
                        patch.object(c,'bind',return_value={'rel':self.rel}), \
                        patch.object(c,'Provider',side_effect=AssertionError('Late packaging must stop before provider setup')):
                    with self.assertRaisesRegex(RuntimeError,'fixed packaging clock'):
                        c.package_execution_source(root,root)
    def test_unknown_original_helper_and_source_rejected(self):
        self.original['partial_week']['validator_sha256']='f'*64
        with self.assertRaises(RuntimeError):self.derive()
        with self.assertRaises(RuntimeError):c._transition_spec({},self.board,self.status,'not-a-source')
    def test_changed_engine_and_experiment_rejected(self):
        self.original['partial_week']['plan']['engine_files']={};self.rehash()
        with self.assertRaises(RuntimeError):self.derive()
        self.setUp();self.original['experimental_recording_enabled']=True
        with self.assertRaises(RuntimeError):self.derive()
    def test_missing_or_changed_legacy_fingerprint_rejected(self):
        self.original['partial_week']['plan']['legacy_exemptions'].pop();self.rehash()
        with self.assertRaises(RuntimeError):self.derive()
        self.setUp();self.original['partial_week']['plan']['legacy_exemptions'][0]['forecast_contract_sha256']='f'*64;self.rehash()
        with self.assertRaises(RuntimeError):self.derive()
    def test_expired_and_reclocked_board_rejected(self):
        self.original['partial_week']['plan']['expires_at']=self.rel.stamp(self.at);self.rehash()
        with self.assertRaises(RuntimeError):self.derive()
        self.setUp();self.board['generated_at']=self.rel.stamp(self.at)
        with self.assertRaises(RuntimeError):self.derive()
    def test_changed_status_clock_schedule_and_population_rejected(self):
        self.status['collected_at']=self.rel.stamp(self.at-c.timedelta(seconds=1))
        with self.assertRaises(RuntimeError):self.derive()
        self.setUp();self.status['games'].pop(next(iter(self.status['games'])))
        with self.assertRaises(self.rel.IntegrityError):self.derive()
    def test_fixed_transition_clock_cannot_be_slid(self):
        with patch.object(c,'TRANSITION_SECONDS',135),self.assertRaises(RuntimeError):c._transition_clock()

class AllocationTests(unittest.TestCase):
 def seed(self):
  return ({'files':{'data':{'bytes':1000}},'packs':[{'bytes':200,'objects':10}]},
          {k:1000 for k in c.METRICS},{'executable_bytes':10,'git_object_bytes':20,'complete_nonalternate_git_store':True})
 def test_pretransport_keeps_archive_and_decoded_zip_separate(self):
  self.assertEqual(c.pretransport_plan({'archive_bytes':123}),{'artifact_zip':123,'maximum_decoded_zip_members':2*c.GIB})
 def test_missing_declared_metric_stops(self):
  manifest,metrics,source=self.seed();metrics.pop('packed_bytes')
  with self.assertRaisesRegex(RuntimeError,'packed_bytes'):c.seed_plan(manifest,metrics,source)
 def test_unknown_alternate_git_closure_stops(self):
  manifest,metrics,source=self.seed();source['complete_nonalternate_git_store']=False
  with self.assertRaisesRegex(RuntimeError,'Git closure'):c.seed_plan(manifest,metrics,source)
 def test_concurrent_copies_and_representations_remain_explicit(self):
  result=c.seed_plan(*self.seed());self.assertEqual(result['three_pages_roots'],3000)
  self.assertEqual(result['two_uploader_tars'],2000);self.assertIn('independent_restart_checkout',result)
 def check(self,free):
  with patch.object(c.Path,'exists',return_value=True),patch.object(c.Path,'stat',return_value=SimpleNamespace(st_dev=7)), \
       patch.object(c.shutil,'disk_usage',return_value=SimpleNamespace(total=10*c.GIB,free=free)):
   return c.admission_allocation([('first','/fictional/one',100),('second','/fictional/two',200)])
 def test_same_device_sums_different_directories(self):
  value=self.check(2*c.GIB+300);self.assertEqual(len(value['filesystems']),1)
  self.assertEqual(value['filesystems']['7']['additional'],300)
 def test_one_byte_deficient_peak_is_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'headroom'):self.check(2*c.GIB+299)
 def test_boolean_and_negative_sizes_rejected(self):
  for value in (True,-1):
   with self.subTest(value=value),self.assertRaises(RuntimeError):c.pretransport_plan({'archive_bytes':value})



class ProductionCacheLifetimeBoundary(unittest.TestCase):
    """Mocked consumers prove diagnostic adapters cannot alter measured updater calls."""
    def fixture(self, directory):
        root=Path(directory)/'fixture';root.mkdir();result=Path(directory)/'dataflow.json'
        events=[];manifest=lambda *a,**kw:({},{});archive=lambda *a,**kw:{}
        capture=SimpleNamespace(_manifest=manifest,_git_archive=archive,_public_archive_commit=lambda *a:None)
        m={'capture':capture,'rel':SimpleNamespace(load_json=lambda *a:{'games':[{'id':'fictional-game'}]}),
           'partial':SimpleNamespace(game_contract=lambda *a:{'original':'fictional-contract'})}
        def production(name,fail=False):
            def call(*a,**kw):
                self.assertIs(capture._manifest,manifest);self.assertIs(capture._git_archive,archive)
                events.append(name)
                if fail:raise RuntimeError('actual production '+name+' failure')
                return {}
            return call
        capture.run_capture=production('capture');capture.validate_generation=production('validate');capture.stage_pages=production('stage')
        return root,result,m,events,production
    def test_capture_and_validation_keep_original_functions_and_context_lifetimes(self):
        with tempfile.TemporaryDirectory() as directory:
            root,result,m,events,production=self.fixture(directory)
            with patch.object(c,'require_offline'),patch.object(c,'execution_identity',return_value={'schema_version':'diagnostic-execution-source-v3','phase2_transition':{}}),patch.object(c,'_sample_context',return_value=(m,SimpleNamespace(calls=0))),patch.object(c,'external',side_effect=lambda *a:contextlib.nullcontext()),patch.object(c.seed_v1,'correction_declaration',return_value=({},[],[])),patch.object(c.seed_v1,'check_correction',return_value={'status':'CONTROL_ONLY'}),patch.object(c.subprocess,'run',side_effect=lambda *a,**kw:events.append('preserve')),patch.object(c,'_advisories',side_effect=production('advisory')),patch.object(c,'_weekly_display',side_effect=production('weekly')),patch.object(c,'operation_lifetime',side_effect=AssertionError('adapter entered measured capture')):
                c.sample_capture(Path(directory),root,result)
            self.assertEqual(events,['preserve','capture','validate','advisory','weekly'])
            self.assertEqual(json.loads(result.read_bytes())['status'],'CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING')
            self.assertIn('actual_weekly_display_writer_and_graph',json.loads(result.read_bytes())['stages'])
    def test_weekly_failure_stops_before_precommit_and_is_not_replaced_by_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root,result,m,events,production=self.fixture(directory)
            with patch.object(c,'require_offline'),patch.object(c,'execution_identity',return_value={'schema_version':'diagnostic-execution-source-v3','phase2_transition':{}}),patch.object(c,'_sample_context',return_value=(m,SimpleNamespace(calls=0))),patch.object(c,'external',side_effect=lambda *a:contextlib.nullcontext()),patch.object(c.seed_v1,'correction_declaration',return_value=({},[],[])),patch.object(c.seed_v1,'check_correction',return_value={'status':'CONTROL_ONLY'}),patch.object(c.subprocess,'run',side_effect=lambda *a,**kw:events.append('preserve')),patch.object(c,'_advisories',side_effect=production('advisory')),patch.object(c,'_weekly_display',side_effect=production('weekly',True)),patch.object(c,'operation_lifetime',side_effect=AssertionError('adapter entered measured capture')):
                with self.assertRaisesRegex(RuntimeError,'actual production weekly failure'):c.sample_capture(Path(directory),root,result)
            self.assertEqual(events,['preserve','capture','validate','advisory','weekly'])
            self.assertEqual(json.loads(result.read_bytes())['status'],'CAPTURE_RUNNING')
    def test_capture_failure_is_not_replaced_by_diagnostic_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root,result,m,events,production=self.fixture(directory);m['capture'].run_capture=production('capture',True)
            with patch.object(c,'require_offline'),patch.object(c,'execution_identity',return_value={'schema_version':'diagnostic-execution-source-v3','phase2_transition':{}}),patch.object(c,'_sample_context',return_value=(m,SimpleNamespace(calls=0))),patch.object(c,'external',side_effect=lambda *a:contextlib.nullcontext()),patch.object(c.seed_v1,'correction_declaration',return_value=({},[],[])),patch.object(c.subprocess,'run',side_effect=lambda *a,**kw:events.append('preserve')),patch.object(c,'operation_lifetime',side_effect=AssertionError('adapter entered measured capture')):
                with self.assertRaisesRegex(RuntimeError,'actual production capture failure'):c.sample_capture(Path(directory),root,result)
            self.assertEqual(events,['preserve','capture']);self.assertEqual(json.loads(result.read_bytes())['status'],'CAPTURE_RUNNING')
    def test_staging_is_unmodified_and_only_later_inventory_gets_bounded_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root,result,m,events,production=self.fixture(directory);c.put(result,{'status':'CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING','stages':{}})
            original=m['capture']._manifest
            @contextlib.contextmanager
            def diagnostic(*a,**kw):
                events.append('diagnostic-enter')
                with patch.object(m['capture'],'_manifest',new=lambda *a,**kw:None):yield
                events.append('diagnostic-exit')
            def metrics(*a):
                self.assertIsNot(m['capture']._manifest,original);events.append('metrics');return final_workload_control()
            with patch.object(c,'require_offline'),patch.object(c,'execution_identity'),patch.object(c,'_sample_context',return_value=(m,SimpleNamespace(calls=0))),patch.object(c,'external',side_effect=lambda *a:contextlib.nullcontext()),patch.object(c,'commit',side_effect=production('commit')),patch.object(c,'operation_lifetime',side_effect=diagnostic),patch.object(c,'final_candidate_workload',side_effect=metrics):
                c.sample_commit(Path(directory),root,result)
            self.assertIs(m['capture']._manifest,original)
            self.assertEqual(events,['commit','stage','diagnostic-enter','metrics','diagnostic-exit'])
            self.assertEqual(json.loads(result.read_bytes())['status'],'PAGES_STAGED_FINAL_CI_PENDING')
    def test_failed_staging_never_enters_diagnostic_collector(self):
        with tempfile.TemporaryDirectory() as directory:
            root,result,m,events,production=self.fixture(directory);m['capture'].stage_pages=production('stage',True)
            c.put(result,{'status':'CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING','stages':{}})
            with patch.object(c,'require_offline'),patch.object(c,'execution_identity'),patch.object(c,'_sample_context',return_value=(m,SimpleNamespace(calls=0))),patch.object(c,'external',side_effect=lambda *a:contextlib.nullcontext()),patch.object(c,'commit',side_effect=production('commit')),patch.object(c,'operation_lifetime',side_effect=AssertionError('adapter entered production stage')),patch.object(c,'final_candidate_workload') as collector:
                with self.assertRaisesRegex(RuntimeError,'actual production stage failure'):c.sample_commit(Path(directory),root,result)
                collector.assert_not_called()
            self.assertEqual(events,['commit','stage']);self.assertEqual(json.loads(result.read_bytes())['status'],'CAPTURE_COMPLETE_PRECOMMIT_CI_PENDING')


class WeeklyDisplayExecution(unittest.TestCase):
    """Wrapper/typed-reader controls; not a full updater or selected-feed PASS."""
    def test_closed_weekly_additions_and_each_deficient_descriptor(self):
        files=[dict(path=name,mode='100644',bytes=1,sha256=digest) for name,digest in c.WEEKLY_EXECUTION_ADDITIONS.items()]
        self.assertEqual(set(c._weekly_execution_additions({'files':files})),set(c.WEEKLY_EXECUTION_ADDITIONS))
        self.assertEqual(c._weekly_execution_additions({'files':[]}),{})
        for i in range(len(files)):
            bad=copy.deepcopy(files);bad.pop(i)
            with self.subTest(missing=i),self.assertRaisesRegex(RuntimeError,'Incomplete'):c._weekly_execution_additions({'files':bad})
        for field,value in [('sha256','0'*64),('mode','100755'),('bytes',True),('bytes',0),('bytes',(1<<20)+1)]:
            bad=copy.deepcopy(files);bad[0][field]=value
            with self.subTest(field=field,value=value),self.assertRaisesRegex(RuntimeError,'Unsupported'):c._weekly_execution_additions({'files':bad})
    def test_weekly_wrapper_uses_actual_root_head_and_fixed_clock_then_validates_graph(self):
        from urllib.request import OpenerDirector,Request
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'output/data').mkdir(parents=True)
            raw=b'{"fictional_wrapper_control":true}';(root/c.WEEKLY_POLICY).write_bytes(raw)
            board=b'{"fictional_board_control":true}';(root/'output/data/week.json').write_bytes(board)
            events=[];source='2'*40
            class Clock(c.datetime):
                @classmethod
                def now(cls,tz=None):return cls.fromisoformat('2026-11-09T05:02:15+00:00')
            clock=Clock;at=clock.now(c.timezone.utc).isoformat()
            pointer={'display_board_sha256':c.sha(board),'sha256':'3'*64};doc={'website_source_sha':source,'rows':[],'state':'DISABLED_USE_R0'}
            module=SimpleNamespace(validate_public_root=lambda path:events.append(('validate',path)),read_public=lambda path:(pointer,doc))
            ranking={'schema_version':'weekly-selected-rankings-v1','website_source_sha':source,'display_board_sha256':c.sha(board),
                'overlay_sha256':pointer['sha256'],'prepared_at':at,'picks':{'over':[],'under':[]},'frozen_proofs':[]}
            ranker=SimpleNamespace(datetime=c.datetime,read_public=lambda path:({'published_at':at,'sha256':'4'*64},ranking))
            def script(path,args,actual_clock):
                self.assertEqual(path,root/'tools/weekly_adaptive_overlay.py');self.assertIs(actual_clock,clock)
                self.assertIs(sys.modules['weekly_selected_rankings'],ranker);self.assertIs(ranker.datetime,clock)
                self.assertEqual(args[args.index('--website-source-sha')+1],source)
                self.assertEqual(args[args.index('--feed-policy')+1],c.WEEKLY_POLICY)
                with self.assertRaises(HTTPError):OpenerDirector().open(Request('https://example.invalid/fictional-control'))
                events.append(('writer',path));return module
            with patch.object(c,'git',side_effect=lambda path,*args:source if path==root and args==('rev-parse','HEAD') else self.fail('Wrong execution identity')),patch.object(c,'WEEKLY_POLICY_SHA256',c.sha(raw)),patch.object(c,'_weekly_ranker',return_value=ranker),patch.object(c,'_advisory_script',side_effect=script):
                value=c._weekly_display(root,{'capture':SimpleNamespace(datetime=clock)})
            self.assertEqual(value['website_source_sha'],source);self.assertEqual(value['mocked_missing_feed_requests'],1)
            self.assertEqual(value['accepted_selected_feed'],'NOT_EXERCISED_NO_MATCHING_FICTIONAL_LAB_PUBLICATION')
            self.assertEqual(value['rankings']['prepared_at'],at);self.assertEqual(value['rankings']['published_at'],at)
            self.assertEqual(events,[('writer',root/'tools/weekly_adaptive_overlay.py'),('validate',root/'output')])
            self.assertEqual((root/'output/data/week.json').read_bytes(),board)
    def test_actual_ranking_source_and_default_completion_clock_share_fixture_clock(self):
        path=HERE/'tools/weekly_selected_rankings.py';body=path.read_bytes()
        descriptor={'path':'tools/weekly_selected_rankings.py','mode':'100644','bytes':len(body),'sha256':c.sha(body)}
        with patch.object(c,'_source_marker',return_value={'files':{descriptor['path']:descriptor}}):ranker=c._weekly_ranker(HERE)
        class Clock(c.datetime):
            @classmethod
            def now(cls,tz=None):return cls.fromisoformat('2026-11-09T05:02:15+00:00')
        expected=Clock.now(c.timezone.utc).isoformat();seen={}
        def prepare(*args,**kwargs):seen.update(kwargs);return {}
        with patch.object(ranker,'datetime',Clock):
            self.assertEqual(ranker.write_public.__kwdefaults__['clock'](),expected)
            with patch.object(ranker,'prepare',side_effect=prepare),patch.object(ranker,'write_public',return_value={}),patch.object(ranker,'validate_document'):
                ranker.prepare_writer(HERE,{},'a'*64,{},website_source_sha='b'*40,atomic_json=lambda *a:None)
        self.assertEqual(seen['now'],expected);self.assertEqual(seen['website_source_sha'],'b'*40)
    def test_ranking_source_mutations_fail_before_execution(self):
        name='tools/weekly_selected_rankings.py';path=HERE/name;body=path.read_bytes()
        descriptor={'path':name,'mode':'100644','bytes':len(body),'sha256':c.sha(body)}
        for field,value in [('path','tools/other.py'),('mode','100755'),('bytes',len(body)+1),('sha256','0'*64)]:
            bad=dict(descriptor);bad[field]=value
            with self.subTest(field=field),patch.object(c,'_source_marker',return_value={'files':{name:bad}}),self.assertRaisesRegex(RuntimeError,'ranking source changed'):c._weekly_ranker(HERE)
        changed=bytes([body[0]^1])+body[1:]
        with patch.object(c,'_source_marker',return_value={'files':{name:descriptor}}),patch.object(c,'_bounded_file',return_value=changed),self.assertRaisesRegex(RuntimeError,'ranking source changed'):
            c._weekly_ranker(HERE)
    def test_actual_eight_public_registration_objects_are_rehashed_at_both_roots(self):
        """Eight exact public objects only; not a complete application Git copy."""
        name='tools/weekly_public_feed.py';body=(HERE/name).read_bytes()
        descriptor=dict(path=name,mode='100644',bytes=len(body),sha256=c.sha(body))
        module=c._weekly_source_module(HERE,name,descriptor);expected=module.registration_objects(HERE)
        self.assertEqual(len(expected),8)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            c._install_weekly_registrations(HERE,root,{'files':[descriptor]})
            self.assertEqual(module.registration_objects(root),expected)
            self.assertFalse((root/'config').exists());self.assertFalse((root/'data').exists())
    def test_actual_complete_ranking_bridge_and_frozen_dependency_failures(self):
        """Actual producers/reader subprocesses; Git lookup alone is an explicit unit stub."""
        script=r"""
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=process.argv[1],pages=process.argv[2],sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const testText=fs.readFileSync(root+'/tests/test-grading-browser.cjs','utf8'),fixtureBlock=testText.split('// BEGIN SELECTED RANKINGS FIXTURE\n')[1].split('// END SELECTED RANKINGS FIXTURE')[0];
const releaseText=fs.readFileSync(root+'/tools/release_browser.cjs','utf8'),readBlock=releaseText.split('// BEGIN WEEKLY DISPLAY GRAPH CONTRACT\n')[1].split('// END WEEKLY DISPLAY GRAPH CONTRACT')[0],rankBlock=releaseText.split('// BEGIN SELECTED RANKING GRAPH CONTRACT\n')[1].split('// END SELECTED RANKING GRAPH CONTRACT')[0];
const scope={fs,path,cp,assert,crypto,Buffer,Map,sha,repo:root,__dirname:path.join(root,'tools'),encode:v=>Buffer.from(JSON.stringify(v))};vm.createContext(scope);
vm.runInContext(fixtureBlock+'\nglobalThis.make=makeSelectedRankingsFixture;'+readBlock+rankBlock+'\nglobalThis.collect=rankingArtifactMembers;globalThis.verify=validateRankingArtifact;globalThis.sources=checkedRankingSources;globalThis.limit=rankingPublicLimit;',scope);
const board={season:2026,week:6,generated_at:'2026-10-15T10:00:00Z',games:[{id:'fictional-game',kickoff:'2026-10-15T00:15:00Z',state:'post'},{id:'fictional-pending',kickoff:'2026-10-20T17:00:00Z',state:'pre'}],players:[0,3].map(i=>({id:'fixture-'+i,game_id:i===3?'fictional-pending':'fictional-game',team:'AAA',opp:'BBB',pos:'WR',games_this_season:5,snap_share:.75,proj_ppr:12,injury:null,props:[{key:'rec',line:4.5,line_from:'dk',proj:4.8,adj:5,n:5,over:2}]})),picks:{over:[],under:[]}};
const good=scope.make(board),expired=scope.make(board,true);let checks=0;
assert.equal(good.doc.picks.under[0].adj,2.5);assert.equal(good.doc.frozen_proofs.length,1);assert.equal(expired.doc.picks.under.length,0);assert.equal(expired.overlay.rows.length,0);checks+=4;
for(const [name,bytes]of good.assets){const file=path.join(pages,name.slice(1));fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);}fs.writeFileSync(path.join(pages,'data/week.json'),JSON.stringify(board));
const gitStub=(command,args)=>{assert.equal(command,'git');assert.ok(args.includes('--no-lazy-fetch'));const name=args[args.length-1].split(':tools/')[1];assert.ok(['weekly_adaptive_overlay.py','weekly_selected_rankings.py'].includes(name));return fs.readFileSync(path.join(root,'tools',name));};
const sources=scope.sources(root,'7'.repeat(40),gitStub),boardHash=sha(Buffer.from(JSON.stringify(board))),overlayPointer=JSON.parse(good.assets.get('/data/weekly-adaptive-overlay.json'));
const verify=()=>scope.verify(pages,scope.collect(pages),'7'.repeat(40),sources,boardHash,overlayPointer.sha256);
let value=verify();assert.equal(value.frozen_proofs,1);assert.equal(value.required.length,5);checks++;
const receipt='data/weekly-selected-rankings/'+good.doc.frozen_proofs[0].receipt_sha256+'.receipt.json',receiptPath=path.join(pages,receipt),receiptBytes=fs.readFileSync(receiptPath);
fs.unlinkSync(receiptPath);assert.throws(verify);fs.writeFileSync(receiptPath,receiptBytes);checks++;
const originalPointer=JSON.parse(receiptBytes),originalPath=path.join(pages,'data',originalPointer.path),originalBytes=fs.readFileSync(originalPath),stamp=fs.statSync(originalPath);const damaged=Buffer.from(originalBytes);damaged[0]^=1;
fs.writeFileSync(originalPath,damaged);fs.utimesSync(originalPath,stamp.atime,stamp.mtime);assert.throws(verify);fs.writeFileSync(originalPath,originalBytes);checks++;
fs.writeFileSync(receiptPath,Buffer.alloc(4097));assert.throws(()=>scope.collect(pages));fs.writeFileSync(receiptPath,receiptBytes);checks++;
const currentPath=path.join(pages,'data',good.pointer.path),currentBytes=fs.readFileSync(currentPath);fs.writeFileSync(currentPath,Buffer.alloc(262145));assert.throws(()=>scope.collect(pages));fs.writeFileSync(currentPath,currentBytes);checks++;
assert.throws(()=>scope.limit('data/weekly-selected-rankings/private.json'));assert.throws(()=>scope.limit('data/weekly-selected-rankings/'+'a'.repeat(64)+'.json.gz'));checks+=2;
assert.throws(()=>scope.sources(root,'7'.repeat(40),()=>Buffer.from('wrong immutable source')));checks++;
const bad=structuredClone(sources);bad['weekly_selected_rankings.py'].sha256='0'.repeat(64);assert.throws(()=>scope.verify(pages,scope.collect(pages),'7'.repeat(40),bad,boardHash,overlayPointer.sha256));checks++;
value=verify();assert.equal(value.required.length,5);checks++;
console.log(JSON.stringify({checks,actual_producers:true,actual_python_graph_reader:true,git_source_lookup:'EXPLICIT_MATCHING_AND_MISMATCHING_UNIT_STUB',provider_requests:0,browser:false}));
"""
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run(['node','-e',script,str(HERE),temp],capture_output=True,text=True,timeout=60,check=True)
        self.assertEqual(json.loads(result.stdout),{'checks':14,'actual_producers':True,'actual_python_graph_reader':True,
            'git_source_lookup':'EXPLICIT_MATCHING_AND_MISMATCHING_UNIT_STUB','provider_requests':0,'browser':False})
    def test_actual_browser_graph_function_and_reviewed_decoder_controls(self):
        script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto'),vm=require('node:vm'),path=require('node:path');
const root=process.argv[1],sourceText=fs.readFileSync(path.join(root,'tools/release_browser.cjs'),'utf8');
const block=sourceText.split('// BEGIN WEEKLY DISPLAY GRAPH CONTRACT\n')[1].split('// END WEEKLY DISPLAY GRAPH CONTRACT')[0];
const sha=b=>crypto.createHash('sha256').update(b).digest('hex'),scope={assert,sha,Buffer};vm.createContext(scope);vm.runInContext(block+'\nglobalThis.graph=weeklyDisplayGraph;globalThis.read=readWeeklyAsset;',scope);
const helperBytes=fs.readFileSync(path.join(root,'output/weekly-adaptive-overlay.js')),helperModule={exports:{}};
assert.equal(sha(helperBytes),'d6657e82639aa001f64701672e25cc72bd6e55142127669a59396f9efe485a68');vm.runInNewContext(helperBytes.toString('utf8'),{module:helperModule},{timeout:2000});
const helper=helperModule.exports,hash='2'.repeat(64),source='1'.repeat(40);
const board={season:2026,week:6,games:[{id:'fictional-game',kickoff:'2026-10-15T00:15:00Z'}],players:[{id:'fictional-player',game_id:'fictional-game',team:'AAA',opp:'BBB',props:[{key:'rec'}]}]},boardHash=sha(Buffer.from(JSON.stringify(board)));
const row={player_id:'fictional-player',game_id:'fictional-game',category:'rec',method_id:'FICTIONAL_TEST_ONLY',model_version:hash,procedure_version:hash,product:'point_mean',prediction_functional:'expected_mean',forecast_value:5.25,horizon:'player_game',source_cutoff_utc:'2026-10-14T09:00:00Z',issued_at:'2026-10-14T08:00:00Z',persistence_completed_at:'2026-10-14T08:01:00Z',kickoff_utc:'2026-10-15T00:15:00Z',valid_until_utc:'2026-10-15T00:15:00Z',selection_sha256:hash,source_policy_sha256:hash,query_source_sha256:hash,first_prepared_at:'2026-10-14T10:00:00Z'};
const doc={schema_version:'weekly-adaptive-public-overlay-v1',registration_id:'weekly-adaptive-release-v1',state:'PROVISIONAL',season:2026,week:6,canonical_board_sha256:boardHash,display_board_sha256:boardHash,board_contract_sha256:hash,prepared_at:'2026-10-14T10:00:00Z',packaged_at:'2026-10-14T10:00:00Z',website_source_sha:source,publication_review_sha256:hash,rows:[row],frozen_rows:[],fallback_counts:{}};
const encode=d=>{const body=Buffer.from(JSON.stringify(d));return {body,pointer:{schema_version:'weekly-adaptive-overlay-pointer-v1',path:'data/weekly-adaptive/'+sha(body)+'.json',sha256:sha(body),bytes:body.length,display_board_sha256:boardHash}}};
let good=encode(doc);scope.graph(good.pointer,good.body,board,boardHash,source,helper);let count=1;
for(const change of [x=>{x.pointer.display_board_sha256='0'.repeat(64)},x=>{x.pointer.bytes++},x=>{x.body=Buffer.from(x.body);x.body[0]^=1},x=>{x.pointer.path='data/weekly-adaptive/other.json'},x=>{x.pointer.extra=true},x=>{x.pointer.schema_version='unknown'}]){const v=encode(doc);change(v);assert.throws(()=>scope.graph(v.pointer,v.body,board,boardHash,source,helper));count++;}
for(const change of [x=>{x.website_source_sha='0'.repeat(40)},x=>{x.rows[0].category='fpts'},x=>{x.rows[0].forecast_value=null},x=>{x.week=7}]){const d=structuredClone(doc);change(d);const v=encode(d);assert.throws(()=>scope.graph(v.pointer,v.body,board,boardHash,source,helper));count++;}
function readerControl(options={}){const data=Buffer.from(options.data||'abc');let cursor=0,stats=0,closed=false,opened=false,maxRead=0;
  const stat=(size,ino=1,symbolic=false,regular=true)=>({size,ino,dev:1,isFile:()=>regular,isSymbolicLink:()=>symbolic});
  const io={constants:options.unsupported?{}:fs.constants,openSync:(_name,flags)=>{opened=true;assert.ok(flags&fs.constants.O_NOFOLLOW);assert.ok(flags&fs.constants.O_NONBLOCK);return 7;},
    fstatSync:()=>++stats===1?stat(options.firstSize??3,1,false,options.regular!==false):stat(options.afterSize??data.length),
    lstatSync:()=>stat(options.currentSize??data.length,options.replaced?2:1,!!options.symbolic),
    readSync:(_fd,buffer,offset,size)=>{maxRead=Math.max(maxRead,size);if(options.ioError)throw Error('fictional read failure');const n=Math.min(size,data.length-cursor);data.copy(buffer,offset,cursor,cursor+n);cursor+=n;return n;},
    closeSync:fd=>{assert.equal(fd,7);closed=true;}};
  return {io,state:()=>({closed,opened,maxRead})};}
let io=readerControl();assert.equal(scope.read('fictional',4,io.io).toString(),'abc');assert.equal(io.state().closed,true);count++;
for(const options of [{firstSize:5,data:'abcde'},{firstSize:3,data:'abcde'},{regular:false},{replaced:true},{symbolic:true},{firstSize:3,data:'ab'},{ioError:true},{unsupported:true}]){
  io=readerControl(options);assert.throws(()=>scope.read('fictional',4,io.io));assert.ok(!io.state().opened||io.state().closed);assert.ok(io.state().maxRead<=5);count++;}
assert.throws(()=>scope.read('fictional',false,readerControl().io));count++;
console.log(JSON.stringify({checks:count,browser:false,provider_requests:0}));
"""
        result=subprocess.run(['node','-e',script,str(HERE)],capture_output=True,text=True,timeout=15,check=True)
        self.assertEqual(json.loads(result.stdout),{'checks':21,'browser':False,'provider_requests':0})

if __name__=='__main__':unittest.main(verbosity=2)
