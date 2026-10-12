"""Applies Ken Burns pan/zoom to the 5 Gemini-generated photoreal stills and
writes them straight into clips_in/ as clip1.mp4 .. clip5.mp4, matching what
assemble_cinematic.py expects.

Durations are driven by the ACTUAL measured length of each scene's narration
(voice length + a 0.8s buffer), not the other way around -- this is the fix
for the sync issue in the first cut, where clip4 was a fixed 6s guess but had
to carry 8.34s of narration (beats 05-08 back to back), so the audio ran past
the picture. Measured via ffprobe on marketing/nas-daily-video/narration/andrew/:
  beat01 3.50s | beat04 2.38s | beat05 0.74s beat06 3.50s beat07 2.04s
  beat08 2.06s (seg4 total 8.34s) | beat09 3.02s
These same numbers are used in assemble_cinematic.py's caption timing, so
picture, captions and voice all agree -- keep the two files in sync if you
regenerate narration.
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = r"C:\Users\venut\AppData\Roaming\Python\Python314\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
STILLS = os.path.join(HERE, "gemini_stills")
CLIPS_IN = os.path.join(HERE, "clips_in")
os.makedirs(CLIPS_IN, exist_ok=True)

W, H, FPS = 1080, 1920, 30

# (still filename, output clip name, duration seconds, zoom direction)
# duration = that segment's narration length + 0.8s buffer (clip2 has no
# narration -- its two DM-bubble captions drive it instead, ~4.4s + buffer)
SPECS = [
    ("scene1_rejections.png", "clip1.mp4", 4.3, "in"),   # beat01 3.50s + buffer
    ("scene2_text.png", "clip2.mp4", 4.8, "in"),          # caption-driven, no VO
    ("scene3_laptop.png", "clip3.mp4", 3.2, "out"),       # beat04 2.38s + buffer
    ("scene4_reaction.png", "clip4.mp4", 9.2, "in"),      # beats 05-08 8.34s + buffer
    ("scene5_calm.png", "clip5.mp4", 3.8, "out"),         # beat09 3.02s + buffer
]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])


for still, out_name, seconds, direction in SPECS:
    src = os.path.join(STILLS, still)
    out = os.path.join(CLIPS_IN, out_name)
    n = int(seconds * FPS)
    if direction == "in":
        z_expr = f"'min(zoom+{0.10/n:.6f},1.10)'"
    else:
        z_expr = f"'if(eq(on,0),1.10,max(zoom-{0.10/n:.6f},1.0))'"
    # cover-crop to 1080x1920 first, then zoompan for the Ken Burns motion
    filt = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"scale=8000:-1,"
        f"zoompan=z={z_expr}:d={n}:s={W}x{H}:fps={FPS}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    )
    cmd = [FFMPEG, "-y", "-loop", "1", "-i", src, "-vf", filt,
           "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "18", out]
    run(cmd)
    print(f"wrote {out} ({seconds}s, zoom {direction})")
