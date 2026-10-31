"""Private workspace places and immutable-by-copy per-run place snapshots.

Place names are operator configuration, never observations or proof of arrival.
Old runs without a snapshot retain the original three-place contract.
"""
import json
from pathlib import Path
import re
import unicodedata


DEFAULT_LOCATIONS = ({'location_id': 'entry-tray', 'location_name': '玄关托盘'},
                     {'location_id': 'study-desk', 'location_name': '书房桌面'},
                     {'location_id': 'living-table', 'location_name': '客厅茶几'})
MAX_LOCATIONS = 10
MAX_CONFIG_BYTES = 16 * 1024


def _validate_locations(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LOCATIONS:
        raise ValueError('地点配置必须包含 1..10 个地点')
    result, ids, names = [], set(), set()
    for row in rows:
        if type(row) is not dict or set(row) != {'location_id', 'location_name'}:
            raise ValueError('每个地点只能包含 location_id 和 location_name')
        key, name = row['location_id'], row['location_name']
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', key):
            raise ValueError('地点 ID 须以小写字母开头，仅含小写字母、数字、下划线或连字符，最长 64 字符')
        if (not isinstance(name, str) or not name.strip() or len(name) > 120
                or any(unicodedata.category(char).startswith('C') for char in name)):
            raise ValueError('地点名称须为 1..120 个字符，不得包含控制字符')
        name = name.strip()
        normalized = ' '.join(unicodedata.normalize('NFKC', name).casefold().split())
        if key in ids or normalized in names:
            raise ValueError('地点 ID 和规范化后的名称不得重复')
        ids.add(key)
        names.add(normalized)
        result.append({'location_id': key, 'location_name': name})
    return result


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('地点配置不得包含重复 JSON 字段')
        result[key] = value
    return result


def load_workspace_locations(workspace):
    """Load once at service startup; missing file preserves the legacy defaults."""
    path = Path(workspace) / 'locations.json'
    if path.is_symlink():
        raise ValueError('地点配置不得是符号链接')
    if not path.exists():
        return [dict(row) for row in DEFAULT_LOCATIONS]
    if not path.is_file():
        raise ValueError('地点配置必须是普通 JSON 文件')
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValueError('地点配置文件不得超过 16 KiB')
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_fields)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('地点配置无法读取为有效 UTF-8 JSON，未回退默认地点') from exc
    if (type(payload) is not dict or set(payload) != {'version', 'locations'}
            or type(payload['version']) is not int or payload['version'] != 1):
        raise ValueError('地点配置仅支持 version=1 和 locations 字段')
    return _validate_locations(payload['locations'])


def run_locations(run):
    """Use the frozen run contract, never the current workspace configuration."""
    if 'location_snapshot' not in run:
        return [dict(row) for row in DEFAULT_LOCATIONS]
    return _validate_locations(run['location_snapshot'])
