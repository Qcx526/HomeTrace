"""Encode browser screenshots of a labelled frozen-task review, not a live run."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from create_delivery_video import probe


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode(frames, review, output, durations):
    frames, review, output = map(Path, (frames, review, output))
    audit_path = output.with_suffix('.metadata.json')
    if output.exists() or audit_path.exists():
        raise ValueError('Never overwrite a video or metadata')
    audit = json.loads(review.read_text(encoding='utf-8'))
    if (audit['kind'] != 'frozen_execution_review' or audit['new_model_calls'] != 0
            or audit['automatic_FOUND'] is not False):
        raise ValueError('Expected a labelled read-only execution review')
    if len(durations) != len(audit['chapters']) or any(not 1 <= d <= 60 for d in durations):
        raise ValueError('One bounded duration per chapter is required')
    inputs = [frames / f'{i + 1:02d}.png' for i in range(len(durations))]
    hashes = [sha(p) for p in inputs]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hometrace-review-') as tmp:
        tmp = Path(tmp)
        for i, (source, seconds) in enumerate(zip(inputs, durations)):
            subprocess.run(['ffmpeg', '-n', '-v', 'error', '-loop', '1', '-framerate', '25',
                            '-i', str(source.resolve()), '-t', str(seconds), '-vf',
                            'scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                            'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xf5f5ee,setsar=1',
                            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                            '-pix_fmt', 'yuv420p', str(tmp / f'{i}.mp4')], check=True)
        (tmp / 'list.txt').write_text(''.join(f"file '{i}.mp4'\n" for i in range(len(inputs))), encoding='ascii')
        subprocess.run(['ffmpeg', '-n', '-v', 'error', '-f', 'concat', '-safe', '1', '-i',
                        str(tmp / 'list.txt'), '-c', 'copy', '-movflags', '+faststart',
                        str(output.resolve())], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'], check=True)
    metadata = {'kind': 'edited_browser_screenshot_walkthrough', 'continuous_live_recording': False,
                'source': 'Frozen actual workflow snapshots and real owner photographs',
                'new_model_calls': 0, 'synthetic_scene_images': 0, 'automatic_FOUND': False,
                'navigation': 'simulated', 'identity_decision': 'owner_confirmation',
                'audio': 'none; Chinese on-screen explanation',
                'full_decode_passed': True, 'review_sha256': sha(review),
                'output_sha256': sha(output), **probe(output),
                'timeline': [{'chapter': i + 1, 'frame_sha256': h, 'seconds': d}
                             for i, (h, d) in enumerate(zip(hashes, durations))]}
    audit_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return metadata


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('frames', 'review', 'output'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--durations', nargs='+', type=int, required=True)
    a = p.parse_args()
    print(json.dumps(encode(a.frames, a.review, a.output, a.durations), ensure_ascii=False, indent=2))
