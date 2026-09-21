"""Build all seven editable classic Mathcad worksheets; no Mathcad required."""
from __future__ import annotations
import argparse
import importlib
import json
from pathlib import Path
from collections import Counter
from book import ROOT
MODULES=('intro','metric_synthesis','engine','shaper','press','pneumatic','cams')
SLUGS=('00_cam_context','01_metric_synthesis','02_engine','03_shaper','04_press','05_pneumatic','06_cams')

def build_all(output: Path, modules=MODULES):
    reports=[]
    for module in modules:
        b=importlib.import_module(module).build()
        path=b.write(output)
        record=json.loads(path.with_suffix('.validation.json').read_text(encoding='utf-8'))
        categories=Counter(s.split(':',1)[0] for s in record['warnings'])
        reports.append(dict(module=module,worksheet=path.name,pages=record['pages'],regions=record['region_count'],
                            errors=len(record['errors']),warnings=len(record['warnings']),warning_categories=dict(categories)))
        print(f'{path.name}: {record["region_count"]} regions, {len(record["errors"])} errors, {len(record["warnings"])} warnings')
    reports=[]
    for module,slug in zip(MODULES,SLUGS):
        path=output/(slug+'.validation.json')
        if not path.exists(): continue
        record=json.loads(path.read_text(encoding='utf-8'))
        reports.append(dict(module=module,worksheet=slug+'.xmcd',pages=record['pages'],regions=record['region_count'],errors=len(record['errors']),warnings=len(record['warnings']),warning_categories=dict(Counter(x.split(':',1)[0] for x in record['warnings']))))
    summary=dict(native_mathcad_recalculated=False,full_ptc_xsd_validation=False,worksheets=reports,
                 total_regions=sum(x['regions'] for x in reports),total_errors=sum(x['errors'] for x in reports),
                 total_warnings=sum(x['warnings'] for x in reports))
    (output/'build_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'output');p.add_argument('--only',nargs='+',choices=MODULES,default=MODULES);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);build_all(args.out,args.only)
if __name__=='__main__': main()
