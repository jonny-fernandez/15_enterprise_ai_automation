"""Offline repository audit: inspect candidate or Git index; writes report only."""
import argparse
from pathlib import Path
from enterprise_automation.release_audit import audit_repository, save_report

p=argparse.ArgumentParser()
p.add_argument('--root',type=Path,default=Path.cwd())
p.add_argument('--output',type=Path,default=Path('artifacts/cp4_repository_audit.json'))
a=p.parse_args()
result=audit_repository(a.root)
save_report(result,a.root/a.output)
print(f"CP4 audit: mode={result['inspection_mode']} scanned={result['text_files_scanned']} findings={result['finding_count']}")
print(f"Report: {a.output}")
if result['findings']:
    for item in result['findings']:
        print(f"BLOCKED {item['path']}: {item['code']}")
    raise SystemExit(1)
print('CP4 local code audit passed. Git staging, actual CI, screenshots and cloud scope are separate gates.')
