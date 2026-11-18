"""Fast synthetic media assets generator for testing the IncuBrix Editing Engine.

Uses vectorized numpy and fast FFmpeg encoding.
Generates:
1. single_speaker_interview.mp4 (240s)
2. two_speaker_podcast.mp4 (30s)
3. phone_vfr_video.mp4 (15s)
4. no_audio_video.mp4 (10s)
5. ambient_music.wav (60s)
"""

from __future__ import annotations
import math
import os
import subprocess
import wave
import cv2
import numpy as np

from engine.ffmpeg_utils import get_ffmpeg_path


def generate_audio_tone_fast(path: str, duration_s: float, freq: int = 440, rate: int = 44100):
    n_samples = int(duration_s * rate)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    # Cadence modulation
    cadence = 0.5 * (1.0 + np.sin(2.0 * np.pi * 1.5 * t))
    sine_wave = 32767.0 * 0.25 * cadence * np.sin(2.0 * np.pi * freq * t)
    audio_data = sine_wave.astype(np.int16)

    # Stereo interleaving
    stereo = np.column_stack((audio_data, audio_data)).flatten()
    with wave.open(path, "wb") as w:
        w.setparams((2, 2, rate, n_samples, "NONE", "not compressed"))
        w.writeframes(stereo.tobytes())


def generate_video_file_fast(output_path: str, duration_s: float, label: str, fps: float = 30.0, with_audio: bool = True):
    ffmpeg = get_ffmpeg_path()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    temp_video = output_path + ".loop.mp4"
    width, height = 640, 360
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_video, fourcc, fps, (width, height))

    # Generate 60 frames (2 seconds) of base visual loop
    for i in range(int(fps * 2)):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :, 0] = int(25 + 20 * math.sin(i / 10))
        frame[:, :, 1] = int(35 + 20 * math.cos(i / 10))
        frame[:, :, 2] = 55

        # Silhouette
        cv2.circle(frame, (320, 140), 45, (190, 190, 190), -1)
        cv2.ellipse(frame, (320, 270), (85, 55), 0, 0, 180, (140, 140, 140), -1)

        t_cur = i / fps
        cv2.putText(frame, f"IncuBrix Asset: {label}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        out.write(frame)
    out.release()

    if with_audio:
        temp_audio = output_path + ".temp.wav"
        generate_audio_tone_fast(temp_audio, duration_s, freq=440)

        # Fast mux with stream_loop & ultrafast preset
        cmd = [
            ffmpeg, "-y",
            "-stream_loop", "-1", "-i", temp_video,
            "-i", temp_audio,
            "-t", str(duration_s),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac",
            "-shortest",
            output_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception:
                pass
    else:
        cmd = [
            ffmpeg, "-y",
            "-stream_loop", "-1", "-i", temp_video,
            "-t", str(duration_s),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-an",
            output_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if os.path.exists(temp_video):
        try:
            os.remove(temp_video)
        except Exception:
            pass


def main():
    media_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Generating synthetic test media in: {media_dir}...")

    # Clean any stale raw files
    for f in os.listdir(media_dir):
        if f.endswith(".raw.mp4") or f.endswith(".raw.wav"):
            try:
                os.remove(os.path.join(media_dir, f))
            except Exception:
                pass

    # 1. Single speaker interview (240s)
    single_spk = os.path.join(media_dir, "single_speaker_interview.mp4")
    print("Generating single_speaker_interview.mp4 (240s)...")
    generate_video_file_fast(single_spk, duration_s=240.0, label="Host Solo Interview", with_audio=True)

    # 2. Two-speaker podcast (30s)
    two_spk = os.path.join(media_dir, "two_speaker_podcast.mp4")
    print("Generating two_speaker_podcast.mp4 (30s)...")
    generate_video_file_fast(two_spk, duration_s=30.0, label="Podcast Host & Guest", with_audio=True)

    # 3. Variable Frame Rate video (15s)
    vfr_vid = os.path.join(media_dir, "phone_vfr_video.mp4")
    print("Generating phone_vfr_video.mp4 (15s)...")
    generate_video_file_fast(vfr_vid, duration_s=15.0, label="Mobile VFR Recording", fps=24.0, with_audio=True)

    # 4. Audio-free video (10s)
    no_audio = os.path.join(media_dir, "no_audio_video.mp4")
    print("Generating no_audio_video.mp4 (10s)...")
    generate_video_file_fast(no_audio, duration_s=10.0, label="B-Roll Silent Video", with_audio=False)

    # 5. Background music track (60s)
    music = os.path.join(media_dir, "ambient_music.wav")
    print("Generating ambient_music.wav (60s)...")
    generate_audio_tone_fast(music, duration_s=60.0, freq=220)

    print("All synthetic test media generated successfully.")


if __name__ == "__main__":
    main()
