"""Downloading a clip's captions: the .ass the renderer wrote becomes SubRip (.srt) with the words and moments
that are on the picture, without the heading, the campaign's line or the boxes."""
import json
import os
import shutil
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-srt-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from studio import auth, config, ctx, db, jobs, render  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"   {extra}" if extra and not ok else ""))
    ok or fails.append(name)


ASS = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins ExtraBold,132,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,0,0,0,0,100,100,0,0,1,7,0,5,0,0,0,1
Style: Hook,Poppins ExtraBold,96,&H000E1014,&H000E1014,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Note,Poppins ExtraBold,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 3,0:00:00.00,0:00:03.90,Hook,,0,0,0,,{\an7\pos(0,0)\fad(160,0)\c&HFFFFFF&\p1}m 10 10 l 300 10 300 200 10 200{\p0}
Dialogue: 4,0:00:00.00,0:00:03.90,Hook,,0,0,0,,{\an5\pos(540,466)\fs96}WATCH THIS
Dialogue: 4,0:00:00.00,0:00:03.90,Note,,0,0,0,,{\an5\pos(540,516)\fs46}follow for more
Dialogue: 1,0:00:00.50,0:00:00.90,Cap,,0,0,0,,{\an5\pos(540,1444)\fs100}{\c&H00FFF000&}THIS {\c&H00FFFFFF&}IS
Dialogue: 1,0:00:00.90,0:00:01.40,Cap,,0,0,0,,{\an5\pos(540,1444)\fs100}{\c&H00FFFFFF&}THIS {\c&H00FFF000&}IS
Dialogue: 0,0:00:00.50,0:00:00.90,Cap,,0,0,0,,{\an7\pos(0,0)\bord0\shad0\c&H000000&\p1}m 0 0 l 400 0 400 300 0 300{\p0}
Dialogue: 1,0:00:02.00,0:00:03.00,Cap,,0,0,0,,{\an5\pos(540,1444)\fs100}A\NTEST
"""

srt = render.ass_to_srt(ASS)
expected = ("1\n00:00:00,500 --> 00:00:01,400\nTHIS IS\n\n"
            "2\n00:00:02,000 --> 00:00:03,000\nA\nTEST\n")
check("the words and their moments become one cue per line", srt == expected, repr(srt))
check("the heading is not a caption", "WATCH THIS" not in srt)
check("a campaign's fixed line is not a caption", "follow for more" not in srt)
check("drawn boxes are skipped", "m 0 0" not in srt and "m 10 10" not in srt)
WORDS = r"""Dialogue: 1,0:00:00.00,0:00:00.60,Cap,,0,0,0,,{\an5\pos(100,1444)\fs100\c&HFFFFFF&}NO
Dialogue: 2,0:00:00.30,0:00:00.60,Cap,,0,0,0,,{\an5\pos(100,1444)\fs100\c&HFFF000&}NO
Dialogue: 1,0:00:00.00,0:00:01.00,Cap,,0,0,0,,{\an5\pos(240,1444)\fs100\c&HFFFFFF&}NO
Dialogue: 2,0:00:00.70,0:00:01.00,Cap,,0,0,0,,{\an5\pos(240,1444)\fs100\c&HFFF000&}NO
Dialogue: 1,0:00:00.00,0:00:01.40,Cap,,0,0,0,,{\an5\pos(380,1444)\fs100\c&HFFFFFF&}WAY
Dialogue: 1,0:00:01.40,0:00:02.20,Cap,,0,0,0,,{\an5\pos(160,1444)\fs100\c&HFFFFFF&}GO
"""
check("words waiting and being said become the line they are on, a repeated word kept",
      render.ass_to_srt(WORDS) == ("1\n00:00:00,000 --> 00:00:01,400\nNO NO WAY\n\n"
                                    "2\n00:00:01,400 --> 00:00:02,200\nGO\n"), repr(render.ass_to_srt(WORDS)))

check("an empty caption file gives no cues", render.ass_to_srt("[Events]\nFormat: Layer\n") == "")
check("a line that is only tags gives no cue",
      render.ass_to_srt("Dialogue: 1,0:00:01.00,0:00:02.00,Cap,,0,0,0,,{\\an5\\pos(1,2)}   ") == "")

u, _ = auth._create("srt@example.com", "Srt", password_hash="x")
with ctx.as_user(u.id):
    job = jobs.create({"type": "file", "name": "a video.mp4"}, {"captions": True}, enqueue=False)
    d = config.user_dir(u.id) / "jobs" / job["id"]
    (d / "clips").mkdir()
    clip = {"id": "c1", "start": 0.0, "end": 5.0, "title": "My clip", "hook": "WATCH", "status": "done",
            "version": 1, "file": "c1.mp4", "cover": "c1.jpg"}
    job.update(status="done", clips=[clip])
    jobs.save(job)
    (d / "clips" / "c1.ass").write_text(ASS, encoding="utf-8")
    got = jobs.clip_captions(job["id"], "c1")
    check("a made clip hands over its captions", got == expected, repr(got))
    (d / "clips" / "c1.ass").unlink()
    try:
        jobs.clip_captions(job["id"], "c1")
        why = ""
    except ValueError as e:
        why = str(e)
    check("a clip whose caption file is gone says so", "caption file is gone" in why, why)
    (d / "clips" / "c1.ass").write_text(ASS.split("[Events]")[0] + "[Events]\n", encoding="utf-8")
    try:
        jobs.clip_captions(job["id"], "c1")
        why = ""
    except ValueError as e:
        why = str(e)
    check("a clip with captions off says it has none", "captions turned off" in why, why)

print("ALL PASSED" if not fails else f"{len(fails)} failed")
db.engine.dispose()
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
