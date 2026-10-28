"""Prepare a NEW private workspace from the explicitly synthetic five-image pack.

Creates fictional demonstration memory only; does not run a search or consume
evidence. Refuses existing workspaces. Never copies private household photos.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from hometrace.household_service import HouseholdService
from hometrace.photo_flow_service import PhotoFlowService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=Path('local_data/ai_html_test_20261027'))
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    if args.workspace.exists():
        parser.error('Workspace already exists. Use a new path; existing memories/evidence are never deleted.')
    root = args.images.resolve()
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    expected = {
        '01_reference_keys.png':'3cc149287c013dd6b9ff8f4ff9f54a4d32d9dfeb5b4200612ec2ea0d40e94fe8',
        '03_keys_study_desk.png':'ac06b717b7171daa0b4b26c6adcbb1556938717929b7a68d53ba785494239502',
        '04_rival_red_keys.png':'5646c45ed7f793136e85ce9183a96d6ef9055af428d47a35ce4215fa447d3b50',
        '05_empty_entry_tray.png':'0b66fbf63b2255ecd3d2535974e0a730403e88c35c9038a67663006a879ae307',
    }
    if manifest.get('not_real_household_data') is not True:
        parser.error('Only the reviewed synthetic demo pack is supported')
    contents = {name:(root/name).read_bytes() for name in expected}
    if any(hashlib.sha256(contents[name]).hexdigest() != digest for name, digest in expected.items()):
        parser.error('Synthetic pack differs from the reviewed fixed ROI inputs; upload and review through the UI instead')
    home = HouseholdService(args.workspace)
    service = PhotoFlowService(home)
    home.enroll('blue-keys', '蓝色钥匙', ['钥匙'])
    assets = {name:service.upload(base64.b64encode(data).decode('ascii'), 'synthetic') for name,data in contents.items()}
    service.reference('blue-keys', assets['01_reference_keys.png']['asset_id'], [110,120,1390,950], True)
    for place, name in [('entry-tray','05_empty_entry_tray.png'), ('study-desk','03_keys_study_desk.png'),
                         ('living-table','04_rival_red_keys.png')]:
        service.scene(place, assets[name]['asset_id'])
    # Both statements are explicitly fictional setup, never robot observations.
    for place in ('study-desk','entry-tray'):
        pending = service.start('记住蓝色钥匙放在这里', place)
        service.act(pending['run_id'], pending['version'], 'confirm_memory')
    (home.workspace/'SYNTHETIC_DEMO.json').write_text(json.dumps({
        'source':'AI generated fictional demonstration', 'real_household_evidence':False,
        'reference_review':'assistant reviewed synthetic ROI [110,120,1390,950]',
        'memory_events':'two fictional owner statements created by explicit demo setup',
        'search_executed':False, 'files':expected}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('已准备合成图演示；尚未搜索。请在页面发送：帮我找蓝色钥匙。')
    print('历史是两条虚构的演示陈述；导航为模拟；外观候选不等于实例 FOUND。')


if __name__ == '__main__':
    main()
