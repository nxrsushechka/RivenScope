"""Opt-in real desktop and audio pipeline test, clearly labelled, no market data."""
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rivenscope.config import validate_settings
from rivenscope.notifications import Channels


def main():
    app=QApplication([]); channel=Channels()
    result={"desktop":False,"in_app":False,"audio_started":False,"audio_finished":False,"warnings":[]}
    with tempfile.TemporaryDirectory(prefix="rivenscope-audio-") as root:
        wav=Path(root)/"test.wav"
        with wave.open(str(wav),"wb") as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(22050)
            stream.writeframes(b"".join(struct.pack("<h",int(2500*math.sin(2*math.pi*660*i/22050))) for i in range(4410)))
        def desktop(ok,detail): result.update(desktop=ok,desktop_reply=detail)
        def playing():
            if channel.sound.isPlaying(): result["audio_started"]=True
            elif result["audio_started"]: result["audio_finished"]=True
        channel.desktop_result.connect(desktop); channel.in_app.connect(lambda *_:result.update(in_app=True))
        channel.warning.connect(result["warnings"].append); channel.sound.playingChanged.connect(playing)
        channel.deliver({"title":"RivenScope · installation test","body":"Test notification — not a market event or trading opportunity.",
                         "settings":validate_settings({"desktop":True,"sound":True,"sound_path":str(wav)}),"listing_id":""})
        QTimer.singleShot(2500,app.quit); app.exec(); channel.close()
        result["sound_status"]=str(channel.sound.status())
    output=Path(__file__).resolve().parents[1]/"test-artifacts/channels.json"; output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,indent=2))
    return 0 if all(result[k] for k in ("desktop","in_app","audio_started","audio_finished")) and not result["warnings"] else 1


if __name__=="__main__": raise SystemExit(main())
