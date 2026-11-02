"""Assemble a clearly labelled working copy while official identity is unfilled.

This never produces a submission candidate. The official builder remains blocked.
Only an exact draft generated from the supplied original and current project text
is permitted; every other preflight error remains fatal. Private config is omitted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from hometrace import submission as sub
from hometrace.official_submission import fill_draft


def build(config_path, repo_root):
    config_path, repo_root = Path(config_path).resolve(), Path(repo_root).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'), object_pairs_hook=sub._object)
    if not isinstance(config, dict) or config.get('document_source') != 'official_template':
        raise sub.SubmissionError('Review bundle requires the supplied official template')
    report, entries, _ = sub.prepare(config_path, repo_root)
    if any(issue['field'] != 'official_application' for issue in report['issues']):
        raise sub.SubmissionError('A non-identity preflight error blocks the review bundle')
    template = sub.local_file(config_path.parent, config['materials']['official_template'])
    draft = sub.local_file(config_path.parent, config['materials']['application'])
    with tempfile.TemporaryDirectory(prefix='hometrace-draft-check-') as tmp:
        expected = Path(tmp) / 'DRAFT-expected.docx'
        fill_draft(template, expected, config['official_template_sha256'], config['official_fields'])
        with zipfile.ZipFile(expected) as a, zipfile.ZipFile(draft) as b:
            if set(a.namelist()) != set(b.namelist()) or any(a.read(n) != b.read(n) for n in a.namelist()):
                raise sub.SubmissionError('Application is not the exact unfilled project draft')
    output = repo_root / 'dist_submission'
    sub._no_links(output, repo_root)
    output.mkdir(exist_ok=True)
    name = ('TEST_ONLY-' if report['test_only'] else '') + 'REVIEW_ONLY_HomeTrace.zip'
    target = output / name
    audit = target.with_suffix('.audit.json')
    sub._no_links(target, repo_root)
    sub._no_links(audit, repo_root)
    if target.exists() or audit.exists():
        raise sub.SubmissionError('Review bundle exists; never overwrite evidence')
    for entry in entries:
        if entry.path == draft:
            entries[entries.index(entry)] = sub.Entry('01_DRAFT_官方主表_个人信息未填写.docx', entry.path, entry.sha256, entry.size)
            break
    status = {'status':'REVIEW_ONLY_NOT_FOR_UPLOAD', 'ready_to_submit':False,
              'officially_verified':False, 'uploaded':False, 'test_only':report['test_only'],
              'official_application':'DRAFT_IDENTITY_MISSING',
              'source':report['checks']['source'], 'materials_checked':report['checks'],
              'required_before_upload':['Complete and validate official identity',
                  'Review current code and materials', 'Verify submission-page requirements',
                  'Build official candidate and extract/open files']}
    generated = {
        'NOT_FOR_UPLOAD_请先阅读.txt': ('这是待填写和审阅的工作副本，不是比赛提交包。\n'
            '官方主表个人信息按负责人要求留空，必须填写并核对；不要上传本 ZIP。\n'
            '正式工具仍会拒绝缺身份主表。请按源码 docs/DELIVERY_CLOSEOUT_20261101.md 完成填表、正式打包与人工核验。\n'
            '导航模拟，软件素材演示不代表独立家庭识别通过。\n').encode('utf-8'),
        'REVIEW_STATUS.json':sub.json_bytes(status),
        'SOURCE_INFO.json':sub.json_bytes(report['checks']['source']),
    }
    hashes = {e.name:e.sha256 for e in entries}
    hashes.update({n:hashlib.sha256(v).hexdigest() for n,v in generated.items()})
    if len(hashes) != len(entries)+len(generated):
        raise sub.SubmissionError('Duplicate review entry')
    generated['manifest.sha256']=''.join(f'{h}  {n}\n' for n,h in sorted(hashes.items())).encode('utf-8')
    hashes['manifest.sha256']=hashlib.sha256(generated['manifest.sha256']).hexdigest()
    # A partial archive is never published under the review filename.
    with tempfile.TemporaryDirectory(prefix='review-build-', dir=output) as tmp:
        partial=Path(tmp)/'review.zip'
        with zipfile.ZipFile(partial,'x',compression=zipfile.ZIP_DEFLATED) as z:
            for e in entries:
                sub._no_links(e.path, Path(e.path.anchor))
                data=e.path.read_bytes()
                if hashlib.sha256(data).hexdigest()!=e.sha256:
                    raise sub.SubmissionError('Input changed during review packaging')
                z.writestr(e.name,data)
            for n,data in generated.items(): z.writestr(n,data)
        with zipfile.ZipFile(partial) as z:
            if z.testzip() or len(z.namelist())!=len(hashes) or set(z.namelist())!=set(hashes):
                raise sub.SubmissionError('Review ZIP integrity failed')
            for n,h in hashes.items():
                if hashlib.sha256(z.read(n)).hexdigest()!=h:
                    raise sub.SubmissionError('Review entry SHA256 differs')
        partial.rename(target)
    status.update(archive_bytes=target.stat().st_size, archive_sha256=sub.sha256(target),
                  verified_entries=len(hashes), crc_and_sha256_verified=True)
    with audit.open('xb') as stream:
        stream.write(sub.json_bytes(status))
    return status


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--repo-root',type=Path,default=Path.cwd())
    args=parser.parse_args()
    try:
        result=build(args.config,args.repo_root)
        print(result['status'])
        print('Official candidate remains blocked. Do not upload this review ZIP.')
    except (ValueError,OSError,KeyError,zipfile.BadZipFile):
        print('BLOCKED: review inputs, official draft or ZIP validation failed.')
        raise SystemExit(2)
