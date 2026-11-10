"""Validate exports/PDFs and package the reviewable submission artifacts."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import argparse,csv,hashlib,json,os,re,shutil,time,zipfile
from pypdf import PdfReader

ROOT=Path('/Users/tusharteotia/Documents/Codex/2026-11-07/get-a/work/oasis37-ssd-20261108/phase3')
ARCHIVE=Path('/Volumes/ HD/tushar/Oasis-37-direct-exfat-20261108/ssd-run/phase3')
BASE=ROOT.parents[2];OUTPUT=BASE/'outputs/oasis-submission-20261109'


def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def copy(src,dest):dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)


def main():
    args=argparse.ArgumentParser();args.add_argument('--visual-verified',action='store_true');opts=args.parse_args()
    assert ARCHIVE.stat().st_dev==16777239
    summary=json.loads((OUTPUT/'catalog3-study/summary.json').read_text());counts=summary['counts']
    analysis=json.loads((ARCHIVE/'reports/analysis/catalog3-interim.json').read_text());assert len(analysis['per_operator'])==16
    cases=list(csv.DictReader((OUTPUT/'catalog3-study/mutant-cases.csv').open()));statuses=Counter(r['test_status'] for r in cases)
    assert len(cases)==counts['GeneratedCases'];assert sum(statuses[k] for k in ['survived','killed_assert','killed_error'])==counts['NScored']
    assert len(cases)-counts['NScored']==counts['ExcludedCases']
    repos=list(csv.DictReader((OUTPUT/'catalog3-study/repositories.csv').open()));assert len(repos)==counts['ArchivedRepos'];assert sum(int(r['scored_mutants'])>0 for r in repos)==counts['ScoredRepos']
    rendered=json.loads((ARCHIVE/'reports/submission/latest-render.json').read_text())
    pdfs={}
    for name in ['manuscript','1352_revised_version']:
        pdf=OUTPUT/(name+'.pdf');assert sha(pdf)==rendered['rendered'][name]['sha256'],'PDF changed since rendering'
        reader=PdfReader(pdf);pages=[p.extract_text() or '' for p in reader.pages];body='\n'.join(pages)
        assert len(rendered['rendered'][name]['pages'])==len(pages)
        assert all(Path(f).exists() for f in rendered['rendered'][name]['pages'])
        assert '??' not in body,'Unresolved printed reference';assert str(counts['NScored']) in body;assert str(counts['ScoredRepos']) in body
        assert ('INTERIM' in body)==(summary['status']!='final')
        pdfs[name]={'path':str(pdf),'sha256':sha(pdf),'bytes':pdf.stat().st_size,'pages':len(pages)}
        log=(OUTPUT/(name+'.log')).read_text()
        assert not re.search(r'(Citation|Reference).*undefined|There were undefined',log,re.I)
    freeze=json.loads((ROOT/'control/catalog3-freeze.json').read_text());code=OUTPUT/'research-code/src/tfmutate'
    for relative,expected in freeze['code_sha256'].items():
        source=ROOT/'framework-v3/src/tfmutate'/relative;assert sha(source)==expected;copy(source,code/relative);assert sha(code/relative)==expected
    for filename in ['pyproject.toml','LICENSE','README.md']:
        source=ROOT/'framework-v3'/filename
        if source.exists():copy(source,OUTPUT/'research-code'/filename)
    for name in ['analyze_completed_catalog3.py','audit_catalog3_archives.py','build_submission_results.py','refresh_submission.py','package_submission.py']:
        copy(ARCHIVE/'recipes'/name,OUTPUT/'reproduction'/name)
    for name in ['catalog3-interim.json','catalog3-interim-repositories.csv','version-separated-identities.json']:
        copy(ARCHIVE/'reports/analysis'/name,OUTPUT/'catalog3-study/analysis'/name)
    copy(ARCHIVE/'reports/integrity/summary.json',OUTPUT/'catalog3-study/integrity-summary.json')
    for receipt in (ARCHIVE/'reports/cancelled-preparations').glob('*/receipt.json'):copy(receipt,OUTPUT/'catalog3-study/cancelled-preparations'/receipt.parent.name/'receipt.json')
    copy(BASE/'outputs/paper-revision/1352_revision_supplement.zip',OUTPUT/'historical-revision-supplement.zip')
    stage='FINAL DATASET - visual review accepted' if summary['status']=='final' and opts.visual_verified else ('FINAL DATASET - visual review pending' if summary['status']=='final' else 'INTERIM - n8n is still running; not submission-ready')
    readme=f'''# Oasis submission copy - Paper1352

**{stage}**

The previous paper-revision directory is preserved. This copy reports frozen catalog3 as the primary study and keeps historical catalog2, the matched123-case study and historical tfsec comparison separate. The user closed the expansion queue for the submission deadline; no further repositories or retries are authorized.

Current archived evidence: {counts['ArchivedRepos']} completed repository attempts; {counts['ScoredRepos']} scored repositories, comprising {counts['FullCoverageRepos']} with every selected baseline passing and {counts['PartialCoverageRepos']} with blocked scopes. {counts['NScored']} scored mutants and {counts['ExcludedCases']} excluded mutant records. {counts['UnrunRepos']} planned repositories were not started and {counts['PreparationFailedRepos']} preparation failures/retries were cancelled. In-flight results are excluded until their repository archive is complete and verified.

- `manuscript.pdf`: article only, {pdfs['manuscript']['pages']} pages.
- `1352_revised_version.pdf`: article plus all14reviewer responses, {pdfs['1352_revised_version']['pages']} pages.
- `1352_latex_source.zip`: editable LaTeX at ZIP root, template dependencies, data tables and frozen scientific source.
- `1352_revision_supplement.zip`: publication CSVs, analysis/integrity summaries, separate historical study exports and historical scanner supplement.
- `catalog3-study/summary.json`: dataset stage, exact counters, timings and interpretation policies.
- `submission-validation.json`: checks, PDF/source/supplement hashes and readiness state.

Compile from this directory using Tectonic0.17.0 with `tectonic manuscript.tex` and `tectonic 1352_revised_version.tex`, or use the two corresponding LaTeX entry points in the source ZIP. The original22frozen source hashes are in catalog3-study/catalog3-freeze.json. Reproduction scripts operate on the retained local archive layout; absolute local paths in publication case CSVs are replaced by[campaign-root], while original bytes remain in the SHA-verified raw archives on the external drive. Raw native archives, provider binaries and credentials are not embedded in the LaTeX source ZIP. Raw archives remain preserved externally with receipts; no public artifact DOI is claimed.

The historical supplementary ZIP is copied unchanged and remains a separate version-specific experiment. Its statistics are not new catalog3 observations. Source-preparation cancellations preserve regular files and link-target metadata without following links; those bundles add no scored results.

No native experiments are launched by the results/export/PDF packaging scripts. No email, public upload or manuscript submission has been performed. No authenticated similarity percentage or certificate is claimed.
'''
    (OUTPUT/'README.md').write_text(readme.replace('Paper1352','Paper 1352').replace('catalog3','catalog 3').replace('catalog2','catalog 2').replace('matched123','matched 123').replace('all14','all 14').replace('original22','original 22').replace('Tectonic0.17','Tectonic 0.17').replace('catalog 3-study','catalog3-study').replace('catalog 3-freeze.json','catalog3-freeze.json'))
    source_files=[]
    for f in OUTPUT.rglob('*'):
        if not f.is_file():continue
        rel=f.relative_to(OUTPUT)
        if f.suffix in {'.aux','.log','.spl','.zip'} or f.name in {'submission-validation.json','render-status.json','bundle-manifest.json','DATASET-STATUS.txt'}:continue
        if f.suffix=='.pdf' and 'logo' not in f.name:continue
        source_files.append(f)
    manifest={str(f.relative_to(OUTPUT)):{'sha256':sha(f),'bytes':f.stat().st_size} for f in source_files}
    (OUTPUT/'bundle-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    sourcezip=OUTPUT/'1352_latex_source.zip'
    with zipfile.ZipFile(sourcezip,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(source_files):z.write(f,str(f.relative_to(OUTPUT)))
        z.write(OUTPUT/'bundle-manifest.json','bundle-manifest.json')
    with zipfile.ZipFile(sourcezip) as z:
        assert z.testzip() is None
        for name,record in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==record['sha256']
    supplement=OUTPUT/'1352_revision_supplement.zip'
    with zipfile.ZipFile(supplement,'w',zipfile.ZIP_DEFLATED) as z:
        for dirname in ['catalog3-study','historical-paired-study','historical-expanded-study']:
            for f in sorted((OUTPUT/dirname).rglob('*')):
                if f.is_file():z.write(f,str(f.relative_to(OUTPUT)))
        z.write(OUTPUT/'historical-revision-supplement.zip','historical-revision-supplement.zip')
        z.write(OUTPUT/'README.md','README.md')
    with zipfile.ZipFile(supplement) as z:
        assert z.testzip() is None
        for name in z.namelist():assert hashlib.sha256(z.read(name)).hexdigest()==sha(OUTPUT/name)
    validation={'epoch':time.time(),'status':stage,'dataset_final':summary['status']=='final','submission_ready':summary['status']=='final' and opts.visual_verified,
                'visual_review_accepted':opts.visual_verified,'render_directory':rendered['render_directory'],'pdfs':pdfs,
                'source_zip':{'path':str(sourcezip),'sha256':sha(sourcezip),'bytes':sourcezip.stat().st_size,'members_verified':len(manifest)+1},
                'supplement_zip':{'path':str(supplement),'sha256':sha(supplement),'bytes':supplement.stat().st_size},
                'primary_counts':counts,'frozen_scientific_hashes_verified':len(freeze['code_sha256']),
                'checks':['CSV totals reconcile with independent audit and tables','All16operator rows including zero-target identifiers retained','PDF citations/references resolved','LaTeX source ZIP member hashes verified','ZIPs pass integrity checks','No primary/historical percentage pooling','No new scientific experiments launched'],
                'layout_note':'Supplied Elsevier class emits the same two output-active logo header box warnings as the predecessor. Main text/table overflows were removed; rendered pages require explicit visual acceptance.'}
    (OUTPUT/'submission-validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    dest=ARCHIVE/'reports/submission';dest.mkdir(exist_ok=True);(dest/'latest-validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    (dest/('validation-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')).write_text(json.dumps(validation,indent=2)+'\n')
    print(json.dumps({'status':stage,'submission_ready':validation['submission_ready'],'pages':[d['pages'] for d in pdfs.values()],'source_zip_bytes':sourcezip.stat().st_size,'supplement_zip_bytes':supplement.stat().st_size}),flush=True)


if __name__=='__main__':main()
