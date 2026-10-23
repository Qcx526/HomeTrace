"""Caption a verified public browser recording, preserving actual execution frames.

Requires ffmpeg/ffprobe (material-authoring tools, not Demo dependencies).
Never point this script at private recordings. Source video is selected from the
browser validator's manifest, not an arbitrary wildcard.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def timestamp(value):
    return f"{int(value // 3600)}:{int(value // 60) % 60:02d}:{value % 60:05.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = json.loads((args.recording_dir / "browser-checks.json").read_text(encoding="utf-8"))
    if checks.get("passed") is not True or checks.get("errors"):
        raise ValueError("Browser verification must have passed")
    for name in ("moved", "missing", "replay"):
        session = json.loads((args.recording_dir / f"{name}-session.json").read_text(encoding="utf-8"))
        if session.get("case", {}).get("case_id") != "public":
            raise ValueError("Public video must not contain a private case")
    source = args.recording_dir / Path(checks["video"]).name
    duration = float(json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source),
    ]))["format"]["duration"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subtitles = args.recording_dir / "narration.ass"
    end = 6 + duration
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1440", "PlayResY: 1080", "WrapStyle: 0", "",
        "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Body,Microsoft YaHei,30,&H00F1F6F7,&H00FFFFFF,&H001E3039,&H001E3039,0,0,0,0,100,100,0,0,1,0,0,2,70,70,25,1",
        "Style: Title,Microsoft YaHei,52,&H00F1F6F7,&H00FFFFFF,&H001E3039,&H001E3039,1,0,0,0,100,100,0,0,1,0,0,5,80,80,0,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    def caption(start, stop, text, style="Body"):
        lines.append(f"Dialogue: 0,{timestamp(start)},{timestamp(stop)},{style},,0,0,0,,{text}")
    caption(0, 6, r"HomeTrace\N作品设计与实际软件演示", "Title")
    caption(0, 6, r"历史记忆 → 主动搜索 → 图像证据验证\N公开实拍样例 · 全程模拟导航 · 无真实机器人运行")
    caption(6, end, r"{\an8\pos(720,22)}HomeTrace  |  实际浏览器录屏  |  OpenCV 公开实拍照片  |  模拟导航")
    caption(6, 14, r"历史记忆只用于决定先去哪里；当前图像必须重新验证。\N公开样例历史 A 为参考图自匹配，不能计作独立识别成绩。")
    caption(14, 23, r"A 未确认后继续到 B；ORB 特征匹配与几何验证支持 FOUND。\N绿色检测框来自实际图像坐标，决策与证据写入 SQLite。")
    caption(23, 40, r"无可靠匹配时保留 SUSPECTED / UNKNOWN。\N未确认不等于证明目标不存在，也不能编造物品位置。")
    caption(40, end, r"重放旧证据不会成为新发现；只有新的合格观察才能确认。\N报告记录每步决策、图片来源、实际计数和最终状态。")
    caption(end, end + 8, r"家庭实拍适用性检查", "Title")
    caption(end, end + 8, r"25 个图对 × 3 种成熟方法，共 75 次评价，0 次 FOUND。\N纸巾等目标仍未可靠确认；保留原阈值，私有照片不进入公开视频。")
    caption(end + 8, end + 15, r"记住过去  验证现在", "Title")
    caption(end + 8, end + 15, r"三个公开场景的策略步数打平，未证明效率提升。\N成果为照片驱动的软件闭环；候选材料须经 PM 与提交前人工核验。")
    subtitles.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Run in the subtitle directory to avoid Windows drive-colon filter escaping.
    filters = (
        "color=c=0x142c35:s=1440x1080:r=25:d=6[intro];"
        "[0:v]fps=25,scale=1200:900,pad=1440:1080:120:80:color=0x142c35,setsar=1[screen];"
        "color=c=0x142c35:s=1440x1080:r=25:d=15[outro];"
        "[intro][screen][outro]concat=n=3:v=1:a=0,ass=narration.ass[out]"
    )
    subprocess.run(["ffmpeg", "-y", "-v", "warning", "-i", str(source.resolve()), "-filter_complex", filters,
                    "-map", "[out]", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(args.output.resolve())], cwd=args.recording_dir, check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(args.output), "-f", "null", "-"], check=True)
    metadata = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_name,width,height", "-of", "json", str(args.output)]))
    metadata.update({"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                     "source": "Actual public browser validation recording; captions and title cards added; no synthetic detection events", "audio": "No audio; Chinese explanatory captions", "full_decode_passed": True})
    args.output.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
