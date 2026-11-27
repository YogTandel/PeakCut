"""Speech in the cloud: ElevenLabs' Scribe writing the transcript instead of the local model. The network is
replaced, so nothing leaves this machine and no key is needed."""
import json
import os
import shutil
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-cloud-asr-")
os.environ["DATABASE_URL"] = ""
os.environ["PEAKCUT_ELEVENLABS_KEY"] = "test-key-12345678"
os.environ.pop("PEAKCUT_ELEVENLABS_KEY_FILE", None)
sys.path.insert(0, ".")
import numpy as np  # noqa: E402

from studio import fetch_model, transcribe  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"   {extra}" if extra and not ok else ""))
    ok or fails.append(name)


class Reply:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


seen = []


def fake_post(url, data=None, files=None, headers=None, timeout=None, **_k):
    seen.append({"url": url, "data": data, "files": files, "headers": headers})
    if fake_post.status != 200:
        return Reply(fake_post.status, {"detail": {"message": "bad key"}})
    return Reply(200, {"words": [
        {"text": "hello", "type": "word", "start": 0.1, "end": 0.4},
        {"text": " ", "type": "spacing", "start": 0.4, "end": 0.45},
        {"text": "(laughter)", "type": "audio_event", "start": 0.45, "end": 0.5},
        {"text": "world", "type": "word", "start": 0.5, "end": 0.9},
        {"text": "", "type": "word", "start": 0.9, "end": 1.0},
    ]})


fake_post.status = 200
transcribe.httpx.post = fake_post
seg = np.full(16000, 0.1, dtype=np.float32)

check("a key turns the cloud model on", transcribe.CLOUD and transcribe.model_ready("en"))
transcribe.fetch_model.ready = lambda lang=None: False          # no local model in this empty folder
check("with no local model, a language still counts as ready", transcribe.model_ready("ar"))

words = transcribe._cloud_piece(seg, "en", 16000)
check("words keep their moments, moved to the whole video",
      words == [{"w": "hello", "s": 1.1, "e": 1.4}, {"w": "world", "s": 1.5, "e": 1.9}], str(words))
check("the request is ElevenLabs' speech-to-text", seen[0]["url"] == "https://api.elevenlabs.io/v1/speech-to-text")
check("the key goes in the xi-api-key header", seen[0]["headers"].get("xi-api-key") == "test-key-12345678")
check("word timestamps and raw 16 kHz sound are asked for",
      (seen[0]["data"]["timestamps_granularity"], seen[0]["data"]["file_format"], seen[0]["data"]["model_id"],
       seen[0]["data"]["language_code"]) == ("word", "pcm_s16le_16", "scribe_v2", "en"), str(seen[0]["data"]))
check("the sound is sent as 16-bit little-endian mono, not encoded",
      seen[0]["files"]["file"][1] == np.clip(seg * 32768.0, -32768, 32767).astype("<i2").tobytes())

progress = []
both = transcribe._cloud_all([(0, 16000, seg), (32000, 48000, seg)], progress.append, "en")
check("several stretches come back in order", [w["w"] for w in both] == ["hello", "world", "hello", "world"], str(both))
check("the later stretch is timed from its own place", both[2]["s"] == 2.1 and both[3]["s"] == 2.5, str(both[2:]))
check("progress counts every stretch", progress[-1] == 1 and len(progress) == 2, str(progress))

settled = transcribe._settle([{"w": "a", "s": 0.0, "e": 0.2}, {"w": "a", "s": 0.0, "e": 0.2},
                              {"w": "b", "s": 0.5, "e": 0.6}, {"w": "c", "s": 0.7, "e": 0.8}])
check("the same word at the same moment is said once", [w["w"] for w in settled] == ["a", "b", "c"])
check("a word lasts until the next one starts", settled[1]["e"] == 0.7, str(settled))

fake_post.status = 401
seen.clear()
try:
    transcribe._cloud_piece(seg, "en", 0)
    why = ""
except RuntimeError as e:
    why = str(e)
check("a refused key says what ElevenLabs answered", "HTTP 401" in why and "bad key" in why, why)

# A video: the cloud fails, and there is no local model to fall back on: the error names the service and the way out.
noise = (np.random.default_rng(3).integers(-6000, 6000, 32000)).astype("<i2")
transcribe.CLOUD = True
try:
    transcribe.transcribe(noise, None, "en")
    why = ""
except RuntimeError as e:
    why = str(e)
check("a failed cloud with no local model explains itself",
      "ElevenLabs couldn't write down this video" in why and "HTTP 401" in why and "Speech models" in why, why)

fake_post.status = 200
transcribe.CLOUD = False
check("with the key off, the local models are the only ones used", not transcribe.CLOUD and not transcribe.model_ready("en"))
transcribe.CLOUD = True

print("ALL PASSED" if not fails else f"{len(fails)} failed")
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
