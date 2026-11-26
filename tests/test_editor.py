"""The clip editor's server side: the state it hands the browser, and the look changes it may send back to the
renderer. Runs against the code directly, with its own empty data folder; nothing is rendered."""
import json
import os
import shutil
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-editor-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_AI_KEY"] = ""
sys.path.insert(0, ".")
from studio import auth, config, ctx, db, jobs, templates  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"   {extra}" if extra and not ok else ""))
    ok or fails.append(name)


u, _ = auth._create("editor@example.com", "Editor", password_hash="x")

WORDS = [{"w": w, "s": 5 + i * 0.4, "e": 5 + i * 0.4 + 0.35}
         for i, w in enumerate("this is a test of the editor and its captions".split())]

with ctx.as_user(u.id):
    job = jobs.create({"type": "file", "name": "a video.mp4"}, {"captions": True}, enqueue=False)
    d = config.user_dir(u.id) / "jobs" / job["id"]
    src = d / "source.mp4"
    src.write_bytes(b"\0" * 2048)
    (d / "words.json").write_text(json.dumps(WORDS), encoding="utf-8")
    clip = {"id": "c1", "start": 5.0, "end": 15.0, "hook": "WATCH THIS", "title": "A clip", "description": "",
            "hashtags": ["test"], "score": 91, "status": "done", "version": 1, "file": "c1.mp4", "cover": "c1.jpg",
            "captions": True, "style": "bounce", "layout": "blur", "template": "b-bounce",
            "fixed_words": WORDS, "fixed_for": [5.0, 15.0, "en2"]}
    job.update(status="done", width=1280, height=720, duration=60.0, source_path=str(src), clips=[clip])
    jobs.save(job)

    # ---- what the editor is handed
    state = jobs.editor_state(job["id"], "c1")
    check("the clip comes with the editor", state["clip"]["id"] == "c1" and state["clip"]["start"] == 5.0)
    check("the look is the tidied copy the clip keeps", state["look"]["cap"]["size"] == 132 and state["look"]["layout"] == "blur")
    check("the words are timed from the clip's start", state["words"][0]["s"] == 0.0 and state["words"][0]["w"] == "this")
    check("the video is the whole source, the clip starts inside it",
          state["video"]["start"] == 5.0 and state["video"]["url"].endswith("/c1/source"))
    check("trimming may go anywhere in the video", state["window"] == {"start": 5.0, "end": 15.0, "min": 0.0, "max": 60.0},
          str(state["window"]))

    # ---- a live clip: its own saved stretch, so the editor's times are moved back by where it sits
    piece = d / "clips"
    piece.mkdir()
    (piece / "c2.mp4").write_bytes(b"\0" * 1024)
    live = dict(clip, id="c2", src=str(piece / "c2.mp4"), src_offset=100.0, src_end=160.0, start=105.0, end=115.0)
    live.pop("fixed_for")
    job["clips"].append(live)
    jobs.save(job)
    state2 = jobs.editor_state(job["id"], "c2")
    check("a saved stretch starts where the clip does", state2["video"]["start"] == 5.0, str(state2["video"]))
    check("a saved stretch can only be trimmed inside itself",
          state2["window"] == {"start": 105.0, "end": 115.0, "min": 100.0, "max": 160.0}, str(state2["window"]))

    # ---- the look changes a re-make may carry
    before = jobs.clip_look(job["clips"][0])
    jobs.request_render(job["id"], "c1", {"look": {"cap": {"size": 500, "per": 2, "color": "12abEf", "not_a_thing": 1},
                                                      "hook": {"upper": True}, "layout": "crop"}})
    after = job["clips"][0]
    check("the caption size is kept in range", after["look"]["cap"]["size"] == 200, str(after["look"]["cap"]))
    check("the caption colours are tidied", after["look"]["cap"]["color"] == "12ABEF")
    check("unknown look fields are dropped", "not_a_thing" not in after["look"]["cap"])
    check("the heading and the layout follow", after["look"]["hook"]["upper"] is True and after["look"]["layout"] == "crop")
    check("everything not sent stays as it was", after["look"]["cap"]["outline"] == before["cap"]["outline"]
          and after["look"]["cap"]["font"] == before["cap"]["font"])
    check("the video is queued to be made again", after["status"] == "queued" and after["version"] == 1)

    # a look change and a different template cannot both win: the template is replaced by the look
    job["clips"][0].update(status="done")
    jobs.request_render(job["id"], "c1", {"template": "b-hype", "look": {"cap": {"size": 90}}})
    check("a template and look changes sent together: the look is used", job["clips"][0]["look"]["cap"]["size"] == 90)

    # ---- trimming, and the limits a clip keeps
    job["clips"][0].update(status="done")
    jobs.request_render(job["id"], "c1", {"start": 4.2, "end": 12.7})
    check("a trim is stored in seconds", (job["clips"][0]["start"], job["clips"][0]["end"]) == (4.2, 12.7))
    for bad, why in (({"start": 10, "end": 11}, "shorter than three seconds"), ({"start": 0, "end": 400}, "longer than three minutes")):
        try:
            jobs.request_render(job["id"], "c1", bad)
            ok = False
        except ValueError:
            ok = True
        check(f"a clip {why} is refused", ok)

    # ---- drafts: what is waiting, kept as it was typed
    job["clips"][0].update(status="done")
    jobs.update_text(job["id"], "c1", {"draft": {"hook": "NEW HOOK", "start": 6.5, "captions": False,
                                                 "look": {"cap": {"size": 110, "bogus": 1}, "hook": {"color": "ffffff"}},
                                                 "junk": "x"}})
    draft = job["clips"][0]["draft"]
    check("the draft keeps the hook, the trim and the captions switch",
          draft["hook"] == "NEW HOOK" and draft["start"] == 6.5 and draft["captions"] is False)
    check("the draft keeps only the look fields the editor may change",
          draft["look"] == {"cap": {"size": 110}, "hook": {"color": "ffffff"}}, str(draft.get("look")))
    check("unknown draft keys are not stored", "junk" not in draft)
    check("a waiting draft comes back to the editor", jobs.editor_state(job["id"], "c1")["clip"]["draft"]["hook"] == "NEW HOOK")
    jobs.update_text(job["id"], "c1", {"draft": {}})
    check("an empty draft clears it", "draft" not in job["clips"][0])

    # ---- a clip whose own saved stretch is gone says so, rather than handing the browser another video
    (piece / "c2.mp4").unlink()
    try:
        jobs.editor_state(job["id"], "c2")
        gone_piece = ""
    except ValueError as e:
        gone_piece = str(e)
    check("a clip whose saved stretch is gone cannot be edited", "no longer on this server" in gone_piece, gone_piece)

    # ---- a clip whose video is gone says so instead of handing the browser a dead address
    src.unlink()
    try:
        jobs.editor_state(job["id"], "c1")
        gone = ""
    except ValueError as e:
        gone = str(e)
    check("a clip with no video left says it cannot be edited", "no longer on this server" in gone, gone)

print("ALL PASSED" if not fails else f"{len(fails)} failed")
db.engine.dispose()
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
