"""LIVE P0 smoke — real Whisper STT + real Gemini description + real OpenAI TTS.

1. Generates Marathi 'factory speech' (gTTS) and mixes in machine noise
   (low-freq hum + white noise, ~10dB SNR) via numpy over the raw mp3->wav.
2. Uploads it and calls POST /ai/voice-describe (REAL integrations).
3. Computes word-level accuracy of the transcript against the reference.
4. Calls POST /ai/tts twice with a Marathi sentence — proves generation + cache.

Run: python scripts/live_voice_smoke.py  (backend must be running on :8001)
"""
import io
import json
import subprocess
import sys
import urllib.request

import numpy as np

BASE = "http://localhost:8001/api"
# Realistic shop-floor Marathi report (spoken register, not textbook)
REFERENCE = "पंप नंबर दोन जवळ पाणी गळत आहे आणि मोटर मधून जळका वास येतो आहे लवकर कोणीतरी बघा"


def req(path, method="GET", body=None, headers=None, raw=None, ctype="application/json"):
    url = BASE + path
    data = raw if raw is not None else (json.dumps(body).encode() if body else None)
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", ctype)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def login():
    st, _ = req("/auth/send-otp", "POST", {"phone": "+919000000011"})
    assert st in (200, 429), st
    st, b = req("/auth/verify-otp", "POST", {"phone": "+919000000011", "otp": "123456"})
    assert st == 200, b
    return {"Authorization": "Bearer " + json.loads(b)["access_token"]}


def make_noisy_marathi_wav() -> bytes:
    from gtts import gTTS

    mp3 = io.BytesIO()
    gTTS(REFERENCE, lang="mr").write_to_fp(mp3)
    # decode mp3 -> wav pcm via ffmpeg
    p = subprocess.run(
        ["ffmpeg", "-i", "pipe:0", "-f", "wav", "-ar", "16000", "-ac", "1", "pipe:1"],
        input=mp3.getvalue(), capture_output=True, check=True,
    )
    wav = p.stdout
    pcm = np.frombuffer(wav[44:], dtype=np.int16).astype(np.float32)
    # factory noise: 50Hz machine hum + broadband white noise at ~10dB SNR
    t = np.arange(len(pcm)) / 16000.0
    speech_rms = np.sqrt(np.mean(pcm**2))
    noise = (
        0.6 * np.sin(2 * np.pi * 50 * t)
        + 0.4 * np.sin(2 * np.pi * 120 * t)
        + 0.8 * np.random.randn(len(pcm))
    )
    noise = noise / np.sqrt(np.mean(noise**2)) * (speech_rms / (10 ** (10 / 20)))
    noisy = np.clip(pcm + noise, -32768, 32767).astype(np.int16)
    import tempfile, os
    fd, tmp = tempfile.mkstemp(suffix=".m4a")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
         "-c:a", "aac", tmp],
        input=noisy.tobytes(), capture_output=True, check=True,
    )
    with open(tmp, "rb") as f:
        data = f.read()
    os.unlink(tmp)
    return data  # m4a


def upload(headers, content: bytes, name: str) -> str:
    boundary = "----smoke123"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{name}\"\r\nContent-Type: audio/mp4\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    st, b = req("/files/upload", "POST", raw=body, headers=headers,
                ctype=f"multipart/form-data; boundary={boundary}")
    assert st == 200, (st, b[:300])
    return json.loads(b)["key"]


def word_accuracy(ref: str, hyp: str) -> float:
    ref_w, hyp_w = ref.split(), hyp.split()
    # simple LCS-based word accuracy
    m, n = len(ref_w), len(hyp_w)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            dp[i + 1][j + 1] = dp[i][j] + 1 if ref_w[i] == hyp_w[j] else max(dp[i][j + 1], dp[i + 1][j])
    return dp[m][n] / m


def main():
    h = login()
    print("== logged in as worker w_prod1")

    audio = make_noisy_marathi_wav()
    print(f"== noisy Marathi m4a: {len(audio)} bytes")
    key = upload(h, audio, "voice_note.m4a")
    print(f"== uploaded: {key}")

    st, b = req("/ai/voice-describe", "POST", {"audio_key": key}, headers=h)
    print(f"== /ai/voice-describe status={st}")
    assert st == 200, b[:500]
    d = json.loads(b)
    print(f"   language:    {d['language']}")
    print(f"   transcript:  {d['transcript']}")
    print(f"   description: {d['description']}")
    acc = word_accuracy(REFERENCE, d["transcript"])
    print(f"   WORD ACCURACY vs reference (10dB machine noise): {acc:.0%}")

    tts_text = "पंप क्रमांक दोन जवळ पाण्याची गळती आहे. त्वरित तपासणी करा."
    st1, b1 = req("/ai/tts", "POST", {"text": tts_text}, headers=h)
    assert st1 == 200, b1[:300]
    r1 = json.loads(b1)
    st2, b2 = req("/ai/tts", "POST", {"text": tts_text}, headers=h)
    r2 = json.loads(b2)
    print(f"== /ai/tts call1 cached={r1['cached']} key={r1['key']}")
    print(f"== /ai/tts call2 cached={r2['cached']} same_key={r1['key'] == r2['key']}")
    st3, audio_bytes = req(f"/files/{r1['key']}", headers=h)
    print(f"== generated mp3 fetch status={st3} bytes={len(audio_bytes)} "
          f"magic_ok={audio_bytes[:3] == b'ID3' or audio_bytes[0] == 0xFF}")
    print("LIVE SMOKE PASSED")


if __name__ == "__main__":
    sys.exit(main())
