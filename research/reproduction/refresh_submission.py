"""Refresh verified deadline-cutoff tables, compile PDFs and render all pages.

No scientific/native experiment commands are launched. Visual acceptance is a
separate explicit step after inspecting the new rendered PDFs.
"""
from pathlib import Path
from datetime import datetime, timezone
import concurrent.futures, hashlib, json, os, shutil, subprocess, time

ROOT = Path('/Users/tusharteotia/Documents/Codex/2026-11-07/get-a/work/oasis37-ssd-20261108/phase3')
ARCHIVE = Path('/Volumes/ HD/tushar/Oasis-37-direct-exfat-20261108/ssd-run/phase3')
BASE = ROOT.parents[2]
OUTPUT = BASE / 'outputs/oasis-submission-20261109'
PY = '/Users/tusharteotia/Library/Application Support/PersonalAgent/workspace/projects/oasis-local-gui/.venv/bin/python'
PDFPY = '/Users/tusharteotia/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
TECTONIC = BASE / 'work/paper-revision/tectonic'


def run(command, log):
    with log.open('wb') as f: subprocess.run(list(map(str,command)), cwd=OUTPUT, stdout=f, stderr=subprocess.STDOUT, check=True)


def main():
    assert ARCHIVE.stat().st_dev == 16777239
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    logs=ARCHIVE/'reports/submission/build-logs'/stamp;logs.mkdir(parents=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,[PY,ARCHIVE/'recipes/analyze_completed_catalog3.py',ROOT],logs/'analysis.log'),
                 pool.submit(run,[PY,ARCHIVE/'recipes/audit_catalog3_archives.py',ROOT,'--reuse'],logs/'integrity.log')]
        for f in futures:f.result()
    run([PY,ARCHIVE/'recipes/build_submission_results.py'],logs/'tables.log')
    for source in ['manuscript.tex','1352_revised_version.tex']:
        run([TECTONIC,'--keep-logs','--keep-intermediates',source],logs/(source+'.log'))
    qa=BASE/'work/submission-qa'/stamp;qa.mkdir(parents=True)
    rendered={}
    for name in ['manuscript','1352_revised_version']:
        pdf=OUTPUT/(name+'.pdf');prefix=qa/name
        run(['pdftoppm','-scale-to','1300','-png',pdf,prefix],logs/(name+'-render.log'))
        rendered[name]={'pdf':str(pdf),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
                        'pages':[str(f) for f in sorted(qa.glob(name+'-*.png'))]}
    report={'epoch':time.time(),'status':'rendered_requires_visual_review','render_directory':str(qa),'rendered':rendered,
            'build_logs':str(logs),'dataset_status':json.loads((OUTPUT/'catalog3-study/summary.json').read_text())['status']}
    (ARCHIVE/'reports/submission/latest-render.json').write_text(json.dumps(report,indent=2)+'\n')
    (OUTPUT/'render-status.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
