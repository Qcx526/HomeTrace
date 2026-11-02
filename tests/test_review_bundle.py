"""Only TEST_ONLY synthetic materials enter these review-bundle tests."""
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

from hometrace import official_submission as form
from hometrace import submission as sub
from test_official_submission import template, data
from test_submission import bundle

spec=importlib.util.spec_from_file_location('build_review_bundle',Path(__file__).resolve().parents[1]/'tools/build_review_bundle.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


def draft_bundle(bundle):
    root,inputs,cfg,path,save=bundle
    cfg.update(document_source='official_template',official_source='TEST_ONLY original',
               official_fields=data(),official_template_sha256=template(inputs/'original.docx'))
    cfg['official_fields']['team_name']=''
    cfg['official_fields']['identity_confirmed']=False
    cfg['materials'].update(official_template='original.docx',application='DRAFT.docx')
    form.fill_draft(inputs/'original.docx',inputs/'DRAFT.docx',cfg['official_template_sha256'],cfg['official_fields'])
    save()
    return root,inputs,cfg,path,save


def test_review_never_unblocks_official_builder_and_checks_hashes(bundle):
    root,_,_,path,_=draft_bundle(bundle)
    result=review.build(path,root)
    assert result['status']=='REVIEW_ONLY_NOT_FOR_UPLOAD'
    assert not result['ready_to_submit'] and not result['uploaded']
    target=root/'dist_submission/TEST_ONLY-REVIEW_ONLY_HomeTrace.zip'
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert '01_DRAFT_官方主表_个人信息未填写.docx' in z.namelist()
        assert all('original.docx' not in n and 'config.json' not in n for n in z.namelist())
        for line in z.read('manifest.sha256').decode().splitlines():
            digest,name=line.split('  ',1)
            assert review.hashlib.sha256(z.read(name)).hexdigest()==digest
    assert sub.build(path,root)['status']=='BLOCKED'
    with pytest.raises(sub.SubmissionError): review.build(path,root)


@pytest.mark.parametrize('bad',['tampered_draft','missing_video','secret','team_authored'])
def test_review_blocks_invalid_material_or_source(bundle,bad):
    root,inputs,cfg,path,save=draft_bundle(bundle)
    if bad=='missing_video': (inputs/'video.mp4').unlink()
    elif bad=='secret': (root/'README.md').write_text('-----BEGIN RSA '+'PRIVATE KEY-----',encoding='utf-8')
    elif bad=='team_authored': cfg['document_source']='team_authored';save()
    else:
        with zipfile.ZipFile(inputs/'DRAFT.docx') as z: parts={n:z.read(n) for n in z.namelist()}
        parts['word/document.xml']=parts['word/document.xml'].replace(b'TEST_ONLY HomeTrace',b'MODIFIED HomeTrace')
        with zipfile.ZipFile(inputs/'DRAFT.docx','w') as z:
            for n,v in parts.items():z.writestr(n,v)
    with pytest.raises(sub.SubmissionError): review.build(path,root)
    assert not list((root/'dist_submission').glob('*.zip'))


def test_existing_review_audit_is_preserved_without_archive(bundle):
    root,_,_,path,_=draft_bundle(bundle)
    output=root/'dist_submission';output.mkdir()
    audit=output/'TEST_ONLY-REVIEW_ONLY_HomeTrace.audit.json'
    audit.write_bytes(b'Existing TEST_ONLY audit')
    with pytest.raises(sub.SubmissionError): review.build(path,root)
    assert audit.read_bytes()==b'Existing TEST_ONLY audit'
    assert not list(output.glob('*.zip'))


def test_review_rejects_non_object_config(bundle):
    root,_,_,path,_=bundle
    path.write_text('[]',encoding='utf-8')
    with pytest.raises(sub.SubmissionError):review.build(path,root)


def test_review_preserves_configured_secret_block(bundle,monkeypatch):
    root,_,_,path,_=draft_bundle(bundle)
    fake='TEST_ONLY_CONFIGURED_PRIVATE_KEY_8899'
    monkeypatch.setenv('HOMETRACE_LLM_API_KEY',fake)
    (root/'README.md').write_text(fake,encoding='utf-8')
    with pytest.raises(sub.SubmissionError):review.build(path,root)
    assert not list((root/'dist_submission').glob('*.zip'))
