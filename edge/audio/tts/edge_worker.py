"""Isolated edge-tts dependency process: text stdin -> decoded PCM stdout."""
import asyncio
import json
import subprocess
import sys
import edge_tts

async def run():
    request = json.load(sys.stdin)
    decoder = subprocess.Popen([
        "gst-launch-1.0", "-q", "fdsrc", "fd=0", "!", "mpegaudioparse", "!",
        "mpg123audiodec", "!", "audioconvert", "!", "audioresample", "!",
        "audio/x-raw,format=S16LE,rate=24000,channels=1", "!", "fdsink", "fd=1"],
        stdin=subprocess.PIPE, stdout=sys.stdout.buffer, stderr=subprocess.DEVNULL)
    try:
        async for event in edge_tts.Communicate(request["text"], request["voice"]).stream():
            if event["type"] == "audio":
                decoder.stdin.write(event["data"])
                decoder.stdin.flush()
        decoder.stdin.close()
        if decoder.wait(timeout=10): raise RuntimeError("Decoder failed")
    finally:
        if decoder.poll() is None:
            decoder.kill(); decoder.wait()

if __name__ == "__main__":
    try: asyncio.run(run())
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
