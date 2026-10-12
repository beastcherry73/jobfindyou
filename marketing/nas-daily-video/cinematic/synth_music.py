"""Synthesizes a simple instrumental background pad with ffmpeg (no external
files, no downloads). Not a substitute for a real royalty-free track, but
free and available now.

Structure: a sustained minor-chord pad (A2-C3-E3, "Am") for the discouraged
first ~60% of the video, crossfading into a warm major-chord pad (C3-E3-G3,
"C") for the hopeful/resolved remainder -- matching the story's emotional
arc. Low-passed for warmth, slow attack/release, kept quiet so it sits under
narration.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = r"C:\Users\venut\AppData\Roaming\Python\Python314\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
OUT = os.path.join(HERE, "music", "background.mp3")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

TOTAL = float(sys.argv[1]) if len(sys.argv) > 1 else 29.73
SPLIT = TOTAL * 0.6           # when Am -> C crossfade begins
XFADE = 3.0                   # crossfade length
CHORD_A = [110.00, 130.81, 164.81]   # A2 C3 E3 -- Am
CHORD_B = [130.81, 164.81, 196.00]   # C3 E3 G3 -- C major

a_len = SPLIT + XFADE / 2
b_len = TOTAL - SPLIT + XFADE / 2


def chord_inputs(freqs, length):
    return [f"sine=frequency={f}:duration={length}" for f in freqs]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])


# Build chord A and chord B as separate mixed-down, filtered clips, then
# acrossfade them together.
a_mp3 = os.path.join(HERE, "music", "_chordA.wav")
b_mp3 = os.path.join(HERE, "music", "_chordB.wav")

for freqs, length, out in [(CHORD_A, a_len, a_mp3), (CHORD_B, b_len, b_mp3)]:
    inputs = []
    for f in freqs:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={f}:duration={length}"]
    filt = (
        "".join(f"[{i}:a]volume=0.33[a{i}];" for i in range(len(freqs)))
        + "".join(f"[a{i}]" for i in range(len(freqs)))
        + f"amix=inputs={len(freqs)}:duration=longest:normalize=0,"
        + f"afade=t=in:st=0:d=1.2,afade=t=out:st={length-1.2}:d=1.2,"
        + "lowpass=f=1200,volume=0.11[out]"
    )
    run([FFMPEG, "-y"] + inputs + ["-filter_complex", filt, "-map", "[out]", out])

run([
    FFMPEG, "-y", "-i", a_mp3, "-i", b_mp3,
    "-filter_complex", f"[0:a][1:a]acrossfade=d={XFADE}:c1=tri:c2=tri[out]",
    "-map", "[out]", "-t", str(TOTAL), OUT,
])

for tmp in (a_mp3, b_mp3):
    os.remove(tmp)

print(f"wrote {OUT} ({TOTAL}s)")
