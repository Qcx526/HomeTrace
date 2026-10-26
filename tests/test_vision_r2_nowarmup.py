"""Controlled-training protections; no GPU or real photos used."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from train_vision_r2 import build_train_args, TRIALS
from train_vision_r2_nowarmup import claim_attempt, controlled_arguments, verify_gate
from vision_r2_data import Blocked, sha256


def test_only_warmup_changes_ignoring_storage_paths(tmp_path):
    baseline=build_train_args(tmp_path/'old-data',tmp_path/'old-run','low-lr-finetune')
    snapshot=copy.deepcopy(baseline)
    new=controlled_arguments(baseline,tmp_path/'new-data',tmp_path/'new-run')
    assert baseline==snapshot
    assert {k for k in baseline if new[k]!=baseline[k]}=={'warmup_epochs','data','project'}
    assert new['warmup_epochs']==0 and new['warmup_bias_lr']==.001 and new['nbs']==2


@pytest.mark.parametrize('key,value',[('epochs',51),('patience',11),('seed',20),('lr0',.01),('batch',4),('nbs',64),('warmup_epochs',2),('mosaic',1),('freeze',10),('optimizer','SGD')])
def test_config_drift_is_blocked(tmp_path,key,value):
    baseline=build_train_args(tmp_path/'data',tmp_path/'run','low-lr-finetune')
    baseline[key]=value
    with pytest.raises(Blocked): controlled_arguments(baseline,tmp_path/'newdata',tmp_path/'newrun')


def test_extra_parameter_cannot_silently_enter_controlled_run(tmp_path):
    baseline=build_train_args(tmp_path/'data',tmp_path/'run','low-lr-finetune')
    baseline['new_option']=True
    with pytest.raises(Blocked): controlled_arguments(baseline,tmp_path/'newdata',tmp_path/'newrun')


def test_one_attempt_cannot_be_reclaimed_by_changing_output(tmp_path):
    ledger=tmp_path/'fixed-ledger.json'
    claim_attempt(ledger,{'destination':'first','status':'RESERVED_ONCE'})
    before=ledger.read_bytes()
    with pytest.raises(Blocked): claim_attempt(ledger,{'destination':'second'})
    assert ledger.read_bytes()==before
    assert json.loads(before)['destination']=='first'


def test_original_two_trial_limit_unchanged():
    assert set(TRIALS)=={'freeze-backbone','low-lr-finetune'}
    assert TRIALS['low-lr-finetune']['warmup_epochs']==1.0


@pytest.mark.parametrize('contents',[{}, {'status':'COMPLETED'}, {'schema_version':1,'total_executed_rows':539}])
def test_incomplete_diagnostics_cannot_authorize_training(tmp_path,contents):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    (tmp_path/'.gitignore').write_text('private/\n')
    directory=tmp_path/'private';directory.mkdir()
    gate=directory/'gate.json';gate.write_text(json.dumps(contents))
    with pytest.raises(Blocked,match='Incomplete'):
        verify_gate(gate,sha256(gate),tmp_path,'synthetic-annotation-binding')
