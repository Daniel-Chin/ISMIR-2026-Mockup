'''
Burn each paper's captions into its video.
uv run python -m scripts.bake_captions            # all
uv run python -m scripts.bake_captions --uids 105 # some
Reads tmp/videos/<uid>.* and tmp/captions/<uid>.{srt,sbv}
(fetch with scripts.download_and_rename_videos_and_captions);
writes tmp/videos_w_caption/<uid>.mp4. Videos without captions are copied as-is.
'''
import argparse
import os
import re
import shutil
import subprocess
import tempfile

from tqdm import tqdm

VIDEOS_DIR = './tmp/videos/'
CAPTIONS_DIR = './tmp/captions/'
OUT_DIR = './tmp/videos_w_caption/'

# libass units are relative to a 288-px-tall canvas, so this scales with resolution.
# White sans on a mostly opaque black box: high contrast over any slide,
# and it hides captions some authors already burned in.
STYLE = ','.join([
    'FontName=DejaVu Sans', 'FontSize=16', 'Bold=0',
    'PrimaryColour=&H00FFFFFF',
    'BorderStyle=3', 'Outline=1', 'Shadow=0', 'OutlineColour=&H33000000',
    'MarginV=10', 'Alignment=2',
])

def find(directory: str, uid: str) -> str | None:
    for name in os.listdir(directory):
        stem, _ = os.path.splitext(name)
        if stem == uid:
            return os.path.join(directory, name)
    return None

def sbv_to_srt(text: str) -> str:
    def ts(t: str) -> str:
        h, m, s = t.strip().split(':')
        sec, ms = s.split('.')
        return f'{int(h):02d}:{int(m):02d}:{int(sec):02d},{ms.ljust(3, "0")[:3]}'
    cues = [c for c in re.split(r'\n\s*\n', text.strip()) if c.strip()]
    out = []
    for i, cue in enumerate(cues, 1):
        times, *lines = cue.splitlines()
        start, end = times.split(',')
        out.append(f'{i}\n{ts(start)} --> {ts(end)}\n' + '\n'.join(lines))
    return '\n\n'.join(out) + '\n'

MP4_AUDIO = {'aac', 'mp3', 'ac3', 'eac3', 'opus', 'alac', 'flac'}

def audio_args(src: str) -> list[str]:
    # Some uploads are e.g. WMV/WMA Pro despite a .mp4 name; MP4 can't hold that audio.
    codecs = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_name',
         '-of', 'csv=p=0', src], capture_output=True, text=True, check=True).stdout.split()
    if all(c in MP4_AUDIO for c in codecs):
        return ['-c:a', 'copy']
    return ['-c:a', 'aac', '-b:a', '192k']

def bake(uid: str) -> None:
    src = find(VIDEOS_DIR, uid)
    if src is None:
        tqdm.write(f'no video {uid}')
        return
    dst = os.path.join(OUT_DIR, f'{uid}.mp4')
    if os.path.exists(dst):
        tqdm.write(f'skip (exists) {dst}')
        return
    captions = find(CAPTIONS_DIR, uid)
    if captions is None:
        tqdm.write(f'no captions, copying {uid}')
        shutil.copyfile(src, os.path.join(OUT_DIR, uid + os.path.splitext(src)[1]))
        return
    with tempfile.TemporaryDirectory() as temp:
        srt = os.path.join(temp, 'c.srt')
        with open(captions, encoding='utf-8-sig') as f:
            text = f.read()
        with open(srt, 'w', encoding='utf-8') as f:
            f.write(sbv_to_srt(text) if captions.endswith('.sbv') else text)
        partial = os.path.join(temp, 'out.mp4')
        tqdm.write(f'{src} + {captions} -> {dst}')
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', src,
            '-vf', f"subtitles={srt}:charenc=UTF-8:force_style='{STYLE}'",
            '-c:v', 'libx264', '-crf', '20', '-preset', 'medium', '-pix_fmt', 'yuv420p',
            *audio_args(src), '-movflags', '+faststart', partial,
        ], check=True)
        shutil.move(partial, dst)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uids', help='comma-separated (default: all videos)')
    args = parser.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    uids = args.uids.split(',') if args.uids else sorted(
        os.path.splitext(n)[0] for n in os.listdir(VIDEOS_DIR)
        if os.path.isfile(os.path.join(VIDEOS_DIR, n)))
    for uid in tqdm(uids, unit='video'):
        bake(uid.strip())

if __name__ == '__main__':
    main()
