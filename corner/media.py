"""Media processing, independent of the development dashboard."""
import json
from pathlib import Path
from urllib.parse import urlparse
import re
import shutil
import subprocess
import sys


def short_id(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        return None
    match = re.fullmatch(r'/shorts/([A-Za-z0-9_-]{11})/?', parsed.path)
    return match.group(1) if match else None


def choose_frames(candidates, duration, count=5):
    """One scene-change peak per temporal bin; centre bias prevents edge clustering."""
    selected = []
    for i in range(count):
        start, end = duration * i / count, duration * (i + 1) / count
        bucket = [c for c in candidates if start <= c[0] < end]
        if not bucket:
            continue
        centre = (start + end) / 2
        peak = max(c[1] for c in bucket) or 1
        selected.append(max(bucket, key=lambda c: c[1] / peak * .7 + (1 - abs(c[0] - centre) / (end - start)) * .3))
    return selected


def extract_frames(video, folder):
    import cv2
    import numpy as np
    import imageio_ffmpeg
    cap = cv2.VideoCapture(str(video))
    try:
        fps, total = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        cap.release()
    if not fps or not total:
        raise RuntimeError('Video could not be decoded.')
    duration = total / fps
    # Decode once at thumbnail resolution instead of repeatedly seeking AV1/GOPs.
    samples = min(900, max(25, int(duration * 4)))
    rate = samples / duration
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    def ffmpeg_run(args):
        result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', *args],
                                capture_output=True, timeout=180, creationflags=flags)
        if result.returncode:
            raise RuntimeError('Frame extraction failed: ' + result.stderr.decode(errors='replace')[-800:])
        return result.stdout
    raw = ffmpeg_run(['-i', str(video), '-vf', f'fps={rate},scale=96:96', '-frames:v', str(samples),
                      '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1'])
    thumbnails = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 96, 96)
    candidates = []
    for i, small in enumerate(thumbnails):
        score = float(np.abs(small.astype(np.int16) - thumbnails[i - 1]).mean()) if i else 0
        candidates.append((min(i / rate, duration - .001), score))
    frames = []
    for index, (t, score) in enumerate(choose_frames(candidates, duration)):
        name = f'frame-{index + 1}.jpg'
        ffmpeg_run(['-y', '-ss', str(t), '-i', str(video), '-frames:v', '1', '-q:v', '2', str(folder / name)])
        if not (folder / name).exists():
            raise RuntimeError(f'Cannot save selected frame at {t:.2f}s.')
        frames.append({'file': name, 'time': round(t, 2), 'change_score': round(score, 2)})
    if len(frames) != 5:
        raise RuntimeError('Could not extract five frames from this video.')
    return frames, duration


def process(url, folder, model='base', cookies=None):
    import yt_dlp
    import imageio_ffmpeg
    from faster_whisper import WhisperModel
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    options = {
        'format': 'bv*[height<=720]+ba/b[height<=720]/best',
        'outtmpl': str(folder / 'video.%(ext)s'), 'noplaylist': True,
        'merge_output_format': 'mp4', 'ffmpeg_location': ffmpeg,
        'socket_timeout': 20, 'retries': 2, 'fragment_retries': 2,
        'max_filesize': 250 * 1024 * 1024,
        'match_filter': lambda info, **kw: 'Video exceeds 10 minutes.' if (info.get('duration') or 0) > 600 else None,
    }
    runtimes = {name: {'path': path} for name in ('deno', 'node') if (path := shutil.which(name))}
    if runtimes:
        options['js_runtimes'] = runtimes
    if cookies:
        options['cookiefile'] = str(cookies)
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
    if not info:
        raise RuntimeError('No downloadable video returned.')
    files = [p for p in folder.glob('video.*') if p.suffix in ('.mp4', '.webm', '.mkv', '.mov')]
    if not files:
        raise RuntimeError('Download did not produce a playable video.')
    video = max(files, key=lambda p: p.stat().st_size)
    print('Extracting representative frames...', flush=True)
    frames, duration = extract_frames(video, folder)
    result = {'id': short_id(url), 'url': url, 'title': info.get('title', 'Untitled Short'),
              'author': info.get('uploader', ''), 'duration': duration, 'video': video.name,
              'frames': frames, 'segments': [], 'transcript': '', 'demo': False}
    # Save images even if speech processing fails, with the error explicitly visible.
    try:
        print(f'Transcribing locally with Whisper {model} (first use downloads the model)...', flush=True)
        # Decode with our bundled FFmpeg: this also avoids PyAV API/version drift.
        import numpy as np
        audio = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                                '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', 'pipe:1'],
                               capture_output=True, timeout=180,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        if audio.returncode:
            raise RuntimeError('Audio decoding failed: ' + audio.stderr.decode(errors='replace')[-600:])
        waveform = np.frombuffer(audio.stdout, dtype=np.float32).copy()
        whisper = WhisperModel(model, device='cpu', compute_type='int8')
        segments, metadata = whisper.transcribe(waveform, beam_size=5, vad_filter=True)
        result['segments'] = [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip()} for s in segments]
        result['language'] = metadata.language
        result['transcript'] = ' '.join(s['text'] for s in result['segments'])
    except Exception as exc:
        result['transcription_error'] = str(exc)
    save_result(folder, result)
    return result


def save_result(folder, result):
    (folder / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    (folder / 'transcript.txt').write_text(result['transcript'], encoding='utf-8')


def demo(folder, index):
    """Generate real local test clips; transcript is explicitly a fixture."""
    import cv2
    import numpy as np
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'video.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 12, (360, 640))
    if not writer.isOpened():
        raise RuntimeError('Demo video encoder unavailable.')
    try:
        for n in range(120):
            section = n // 24
            canvas = np.full((640, 360, 3), (40 + section * 25, 35 + index * 20, 65 + section * 20), dtype=np.uint8)
            cv2.circle(canvas, (80 + n % 200, 280), 50 + section * 8, (120, 210, 245), -1)
            cv2.putText(canvas, f'DEMO {index}', (55, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 2)
            cv2.putText(canvas, f'Scene {section + 1}', (70, 480), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
            writer.write(canvas)
    finally:
        writer.release()
    frames, duration = extract_frames(path, folder)
    text = 'Demo transcript fixture. This generated clip demonstrates five changing scenes. No YouTube video was downloaded and no speech recognition was run.'
    result = {'id': f'demo-{index}', 'title': ['A little change of perspective', 'Five moments, one story', 'Room for something curious'][(index - 1) % 3],
              'url': '', 'author': 'Local demo fixture', 'duration': duration, 'video': path.name,
              'frames': frames, 'transcript': text, 'segments': [{'start': 0, 'end': 10, 'text': text}], 'demo': True}
    save_result(folder, result)
    return result
