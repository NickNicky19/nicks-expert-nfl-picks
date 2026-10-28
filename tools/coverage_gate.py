"""Semantic prerequisite only; never substitutes for full workload admission."""
import json
from pathlib import Path

def evaluate(h,admission):
    m=admission['metrics'];d=h.admission_decisions(m)
    # Small construction cannot establish 24-generation archive/physical floors.
    # Every such requirement remains mandatory in later FULL admission.
    categorical={k:v for k,v in d['categorical'].items() if k!='archives'}
    dimensions={k:m['group_dimensions'].get(k,0)>=minimum for k,minimum in h.GROUP_DIMENSION_FLOORS.items()}
    counts={k:type(m.get(k)) is int and m[k]>=h.ENVELOPE[k] for k in ('groups','contexts')}
    checks=dict(categorical=categorical,dimensions=dimensions,counts=counts,population=d['population_pass'],
        fresh_reconstruction=m.get('cold_restart')=='PASS_NEW_PROCESS_NO_SHARED_TRUST',
        original_bytes=admission.get('immutable_bytes_unchanged') is True)
    passed=all(categorical.values()) and all(dimensions.values()) and all(counts.values()) and all(checks[k] for k in ('population','fresh_reconstruction','original_bytes'))
    return dict(status='PRELIMINARY_COVERAGE_PASS' if passed else 'PRELIMINARY_COVERAGE_FAIL',checks=checks,
        group_dimensions=m['group_dimensions'],groups=m['groups'],contexts=m['contexts'],
        full_admitted=False,full_requirements_unchanged=h.ENVELOPE,
        full_archive_requirement_deferred_not_waived=h.ENVELOPE['complete_generations']-2)

def main():
    import operating_diagnostic as h
    import argparse
    p=argparse.ArgumentParser();p.add_argument('admission',type=Path);p.add_argument('result',type=Path);a=p.parse_args()
    result=evaluate(h,json.loads(a.admission.read_bytes()));a.result.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))
    if result['status']!='PRELIMINARY_COVERAGE_PASS':raise SystemExit(3)

if __name__=='__main__':main()
