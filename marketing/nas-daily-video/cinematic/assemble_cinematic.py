"""Assembles the JobSpike photoreal cinematic ad from Kling/Veo clips.

WORKFLOW
  1. Generate the 5 clips using marketing/nas-daily-video/PROMPTS.md
     (Google AI Studio / Kling), download them, and name them clip1.mp4
     .. clip5.mp4 (story order) inside cinematic/clips_in/.
  2. Drop one royalty-free music track (mp3/wav) into cinematic/music/
     and point MUSIC_PATH at it below. Free sources: YouTube Audio
     Library, Pixabay Music, Free Music Archive (CC0 / no-attribution
     tracks). This script does not fetch one for you.
  3. Run:  python assemble_cinematic.py
     Output lands in cinematic/out/jobspike_cinematic_final.mp4
     (1080x1920, ready for Reels / Shorts / TikTok).

DESIGN NOTES
  - Real Kling/Veo generations vary in resolution, fps and exact
    duration run to run, so every clip is first normalized (scaled +
    center-cropped to 1080x1920 "cover", 30fps, silent) before concat --
    concatenating mismatched streams directly corrupts the output.
  - A CTA end card is generated in-process (same headless-Chrome +
    ffmpeg technique used for the earlier illustrated scenes) and
    appended after the 5 clips, so you don't need to shoot a 6th clip
    for it.
  - Caption/narration timing is anchored to each SEGMENT's *actual*
    start time in the concatenated timeline (measured via ffprobe),
    not hardcoded seconds -- so it self-corrects if your generated
    clips run shorter or longer than requested.
  - Segment 4 ("reacting to score") carries four narration lines
    (beats 05-08) back to back, because that's where the original
    10-beat script compresses four narrative beats into one cinematic
    shot. The narration is allowed to run past that single clip's
    visual duration into clip 5's footage -- this is normal
    documentary/ad practice (voiceover commonly bridges a cut) rather
    than a bug. If it sounds rushed once you hear it against picture,
    either regenerate clip 4 longer or edit SEGMENTS below to move a
    line onto its own beat.
"""
import glob
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # marketing/nas-daily-video
FFMPEG = r"C:\Users\venut\AppData\Roaming\Python\Python314\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CLIPS_IN = os.path.join(HERE, "clips_in")
WORK = os.path.join(HERE, "work")
OUT_DIR = os.path.join(HERE, "out")
NARRATION_DIR = os.path.join(ROOT, "narration")

VOICE = "andrew"          # "andrew" or "aria" -- must match generate_narration.py output
MUSIC_PATH = os.path.join(HERE, "music", "background.mp3")  # <-- put your track here
MUSIC_VOLUME = 0.14        # relative to narration; bg music should sit well under VO

W, H, FPS = 1080, 1920, 30

os.makedirs(WORK, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + " ".join(cmd) + "\n\nSTDERR:\n" + r.stderr[-4000:])
    return r


def probe_duration(path):
    r = subprocess.run(
        [FFMPEG, "-i", path], capture_output=True, text=True
    )
    for line in r.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            hms = line.split()[1].rstrip(",")
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f"could not read duration for {path}")


def narration(beat):
    return os.path.join(NARRATION_DIR, VOICE, f"beat{beat}.mp3")


# ---------------------------------------------------------------------------
# 1. Build the CTA end card (rendered once, cached)
# ---------------------------------------------------------------------------

def build_cta_card():
    png = os.path.join(WORK, "cta.png")
    mp4 = os.path.join(WORK, "cta_norm.mp4")
    if os.path.exists(mp4):
        return mp4
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{W}px;height:{H}px;background:#1E3A5F;
    display:flex;align-items:center;justify-content:center;
    font-family:'Segoe UI',Arial,sans-serif;}}
  .card{{text-align:center;color:#F7F5F0;}}
  .brand{{font-size:64px;font-weight:800;letter-spacing:-1px;}}
  .spike{{color:#818CF8;}}
  .url{{margin-top:18px;font-size:34px;color:#B9C4D8;}}
  .tag{{margin-top:34px;display:inline-block;padding:14px 34px;
    border-radius:999px;background:#4F46E5;font-size:28px;font-weight:600;}}
</style></head>
<body>
  <div class="card">
    <div class="brand">Job<span class="spike">Spike</span></div>
    <div class="url">jobspike.in</div>
    <div class="tag">Free &middot; No card</div>
  </div>
</body></html>"""
    html_path = os.path.join(WORK, "cta.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    user_data = os.path.join(WORK, "chrome_cta_profile")
    shutil.rmtree(user_data, ignore_errors=True)
    run([
        CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", f"--window-size={W},{H}",
        "--virtual-time-budget=1500", f"--user-data-dir={user_data}",
        f"--screenshot={png}", f"file:///{html_path.replace(os.sep, '/')}",
    ])
    # beat10 narration ("JobSpike. jobspike dot in. Free. No card.") measures
    # 4.10s -- the card must hold at least that long or the line gets cut off.
    cta_duration = 4.6
    run([
        FFMPEG, "-y", "-loop", "1", "-i", png,
        "-vf", f"fade=t=in:st=0:d=0.3,fade=t=out:st={cta_duration-0.4}:d=0.4,fps={FPS}",
        "-t", str(cta_duration), "-pix_fmt", "yuv420p", mp4,
    ])
    return mp4


# ---------------------------------------------------------------------------
# 2. Normalize every input clip to 1080x1920 / 30fps / silent h264
# ---------------------------------------------------------------------------

def normalize(src, tag):
    out = os.path.join(WORK, f"norm_{tag}.mp4")
    run([
        FFMPEG, "-y", "-i", src,
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", out,
    ])
    return out


def find_input_clips():
    files = sorted(glob.glob(os.path.join(CLIPS_IN, "clip*.mp4")))
    if not files:
        raise SystemExit(
            f"No clip*.mp4 files found in {CLIPS_IN}\n"
            "Generate the 5 clips from PROMPTS.md, download them, and name them "
            "clip1.mp4 .. clip5.mp4 in story order before running this script."
        )
    return files


# ---------------------------------------------------------------------------
# 3. Segment schedule: caption(s) + narration beat(s) per clip, in order.
#    Edit this list freely -- timestamps are computed from real durations,
#    not hardcoded.
# ---------------------------------------------------------------------------

def build_segments(clip_files):
    cta = build_cta_card()
    segs = []
    # Caption windows below are the MEASURED narration durations (see the
    # module docstring), so a caption is on screen for exactly as long as
    # its line is being spoken -- no more guessed round numbers.
    # seg index 0 -> clip1 .. matches PROMPTS.md order
    segs.append(dict(file=clip_files[0], captions=[(0.0, 3.5, "Applied to 47 jobs. Zero replies.")],
                      narration=[narration("01")]))
    if len(clip_files) > 1:
        segs.append(dict(file=clip_files[1], captions=[
            (0.0, 2.2, "bro try JobSpike.in first"),
            (2.2, 4.4, "i think your resume's the problem"),
        ], narration=[]))
    if len(clip_files) > 2:
        segs.append(dict(file=clip_files[2], captions=[(0.0, 2.38, "Uploaded it. 20 seconds.")],
                          narration=[narration("04")]))
    if len(clip_files) > 3:
        segs.append(dict(file=clip_files[3], captions=[
            (0.0, 0.74, "Oh."),
            (0.74, 4.24, "My resume was unreadable to the scanner the whole time."),
            (4.24, 6.28, "It rewrote the weak parts."),
            (6.28, 8.34, "Then matched me to real roles."),
        ], narration=[narration("05"), narration("06"), narration("07"), narration("08")]))
    if len(clip_files) > 4:
        segs.append(dict(file=clip_files[4], captions=[(0.0, 3.02, "Same me. A resume they can actually read.")],
                          narration=[narration("09")]))
    # any extra clips beyond 5 are appended with no captions/narration
    for extra in clip_files[5:]:
        segs.append(dict(file=extra, captions=[], narration=[]))
    # no caption here: the CTA card image already has the brand text baked in
    segs.append(dict(file=cta, captions=[], narration=[narration("10")]))
    return segs


# ---------------------------------------------------------------------------
# 4. SRT generation
# ---------------------------------------------------------------------------

def srt_ts(t):
    if t < 0:
        t = 0
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    s = int(t)
    ms = int(round((t - s) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(entries, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(entries, 1):
            f.write(f"{i}\n{srt_ts(start)} --> {srt_ts(end)}\n{text}\n\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    clip_files = find_input_clips()
    print(f"found {len(clip_files)} input clip(s): {[os.path.basename(c) for c in clip_files]}")

    segments = build_segments(clip_files)

    # normalize each segment's video (cta already normalized in build_cta_card)
    for i, seg in enumerate(segments):
        if seg["file"].endswith("cta_norm.mp4"):
            seg["norm"] = seg["file"]
        else:
            seg["norm"] = normalize(seg["file"], f"seg{i}")
        seg["dur"] = probe_duration(seg["norm"])

    # concat demuxer list
    list_path = os.path.join(WORK, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"file '{seg['norm'].replace(chr(92), '/')}'\n")
    concat_video = os.path.join(WORK, "concat_video.mp4")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", concat_video])
    total_duration = probe_duration(concat_video)
    print(f"concatenated video duration: {total_duration:.2f}s")

    # compute absolute offsets + build SRT + narration delay list.
    # narration lines within a segment queue back to back starting at that
    # segment's start; captions are anchored the same way.
    srt_entries = []
    narration_inputs = []  # (path, delay_seconds)
    offset = 0.0
    for seg in segments:
        for start, end, text in seg["captions"]:
            srt_entries.append((offset + start, offset + end, text))
        line_offset = offset
        for npath in seg["narration"]:
            narration_inputs.append((npath, line_offset))
            line_offset += probe_duration(npath)
        offset += seg["dur"]

    srt_path = os.path.join(WORK, "captions.srt")
    write_srt(srt_entries, srt_path)
    print(f"wrote {len(srt_entries)} caption lines to {srt_path}")

    last_narr_end = max((d + probe_duration(p) for p, d in narration_inputs), default=0)
    if last_narr_end > total_duration + 0.5:
        print(f"WARNING: narration runs to {last_narr_end:.1f}s but video is only "
              f"{total_duration:.1f}s -- audio will be cut off. Consider a longer clip 4 "
              f"or trimming a narration line.")

    # ---- audio filter graph ----
    audio_inputs = [p for p, _ in narration_inputs]
    have_music = os.path.exists(MUSIC_PATH)
    cmd = [FFMPEG, "-y", "-i", concat_video]
    for p in audio_inputs:
        cmd += ["-i", p]
    music_idx = None
    if have_music:
        music_idx = len(audio_inputs) + 1
        cmd += ["-stream_loop", "-1", "-i", MUSIC_PATH]
    else:
        print("NOTE: no music file found at", MUSIC_PATH, "-- output will have narration only.")

    filter_parts = []
    # video: crop already done; burn subtitles
    srt_for_filter = srt_path.replace("\\", "/").replace(":", "\\:")
    filter_parts.append(
        f"[0:v]subtitles='{srt_for_filter}':force_style="
        f"'FontName=Segoe UI,FontSize=15,PrimaryColour=&H00F5F5F7,"
        f"OutlineColour=&H00201E1B,BorderStyle=1,Outline=2,Shadow=0,"
        f"Alignment=2,MarginV=140'[vout]"
    )

    narr_labels = []
    for i, (p, delay) in enumerate(narration_inputs, start=1):
        ms = int(delay * 1000)
        lbl = f"n{i}"
        filter_parts.append(
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"adelay={ms}|{ms}[{lbl}]"
        )
        narr_labels.append(f"[{lbl}]")
    if narr_labels:
        filter_parts.append(
            "".join(narr_labels) + f"amix=inputs={len(narr_labels)}:duration=longest:normalize=0[narr]"
        )
        narr_out = "[narr]"
    else:
        # silent placeholder matching video length
        filter_parts.append(f"anullsrc=r=44100:cl=stereo:d={total_duration}[narr]")
        narr_out = "[narr]"

    if have_music:
        filter_parts.append(
            f"[{music_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={MUSIC_VOLUME},atrim=0:{total_duration}[mus]"
        )
        filter_parts.append(f"{narr_out}[mus]amix=inputs=2:duration=first:normalize=0[aout]")
        a_out = "[aout]"
    else:
        a_out = narr_out

    filter_complex = ";".join(filter_parts)
    out_path = os.path.join(OUT_DIR, "jobspike_cinematic_final.mp4")
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", a_out,
        "-t", str(total_duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    run(cmd)
    print(f"\nDONE: {out_path}  ({total_duration:.1f}s, {W}x{H})")


if __name__ == "__main__":
    main()
