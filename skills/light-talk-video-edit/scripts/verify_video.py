"""Decode an export, check duration, and optionally compare copied audio."""
import argparse
import json
from pathlib import Path
import subprocess
from render_light import probe

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('video',type=Path);ap.add_argument('--ffmpeg',default='ffmpeg')
    ap.add_argument('--expected-duration',type=float);ap.add_argument('--audio-reference',type=Path)
    a=ap.parse_args();meta=probe(a.ffmpeg,a.video)
    subprocess.run([a.ffmpeg,'-v','error','-i',str(a.video),'-f','null','-'],check=True)
    if a.expected_duration is not None and abs(meta['duration']-a.expected_duration)>.08:raise SystemExit('Unexpected duration.')
    if a.audio_reference:
        def digest(path):return subprocess.check_output([a.ffmpeg,'-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-'],text=True).strip()
        if digest(a.video)!=digest(a.audio_reference):raise SystemExit('Copied audio differs from reference.')
        meta['audio_identical']=True
    print(json.dumps({'decode_ok':True,**meta},ensure_ascii=False))

if __name__=='__main__':main()
