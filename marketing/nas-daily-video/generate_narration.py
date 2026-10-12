"""Generate edge-tts narration takes for the JobSpike illustrated-narrative video.

Two voice options are rendered per line so the user can A/B compare against
their own recorded voice. Filenames are prefixed with the beat number from
the beat sheet in marketing/nas-daily-video/SCRIPT.md.
"""
import asyncio
import edge_tts

LINES = [
    ("01", "Applied to 47 jobs. Zero replies."),
    ("04", "Uploaded it. 20 seconds."),
    ("05", "Oh."),
    ("06", "My resume was unreadable to the scanner the whole time."),
    ("07", "It rewrote the weak parts."),
    ("08", "Then matched me to real roles."),
    ("09", "Same me. A resume they can actually read."),
    ("10", "JobSpike. jobspike dot in. Free. No card."),
]

VOICES = {
    "andrew": "en-US-AndrewNeural",   # warm, confident, conversational
    "aria": "en-US-AriaNeural",       # crisp, confident, news/novel register
}


async def main():
    for voice_dir, voice_id in VOICES.items():
        for num, text in LINES:
            out_path = f"marketing/nas-daily-video/narration/{voice_dir}/beat{num}.mp3"
            communicate = edge_tts.Communicate(text, voice_id, rate="-4%")
            await communicate.save(out_path)
            print(f"wrote {out_path}  ({voice_id}): {text}")


if __name__ == "__main__":
    asyncio.run(main())
