"""Fix a rough cut's playback speed exactly once; keep a hashed speed record."""
import argparse,math,shutil
from pathlib import Path
from common import setup_path,need_tools,probe,sha,load,save,new_dir,run

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('video',type=Path);ap.add_argument('dest',type=Path)
    ap.add_argument('--input-speed',type=float,required=True)
    ap.add_argument('--target-speed',type=float,default=1.1)
    args=ap.parse_args();setup_path();need_tools('ffmpeg','ffprobe')
    if any(not math.isfinite(v) or v<=0 for v in [args.input_speed,args.target_speed]):
        ap.error('Speeds must be finite and positive')
    source=args.video.resolve();info=probe(source)
    if not any(s['codec_type']=='video' for s in info['streams']):ap.error('No video track')
    if not any(s['codec_type']=='audio' for s in info['streams']):ap.error('No original voice track')
    identity=sha(source)
    previous=source.parent/'speed.json'
    if previous.is_file():
        old=load(previous)
        if old.get('currentSha256')==identity and abs(old['targetSpeed']-args.input_speed)>1e-8:
            ap.error('Input speed conflicts with its saved speed record; refusing to apply speed twice')
    target=new_dir(args.dest);out=target/'talk.mp4';ratio=args.target_speed/args.input_speed
    if abs(ratio-1)<1e-8:
        shutil.copy2(source,out)
    else:
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        intended=float(video.get('duration') or info['format']['duration'])/ratio
        frames=max(1,math.floor(intended*30+.5));out_duration=frames/30
        # Chain atempo factors so all target ratios remain in the common 0.5–2 range.
        factors=[];r=ratio
        while r>2:factors.append(2);r/=2
        while r<.5:factors.append(.5);r/=.5
        factors.append(r)
        audio=','.join('atempo='+str(v) for v in factors)+',aresample=48000:first_pts=0,apad'
        run(['ffmpeg','-n','-v','error','-i',source,'-map','0:v:0','-map','0:a:0',
             '-vf',f'setpts=(PTS-STARTPTS)/{ratio}','-af',audio,'-r','30',
             '-c:v','libx264','-preset','fast','-crf','16','-threads','2',
             '-c:a','aac','-b:a','256k','-frames:v',frames,'-t',out_duration,
             '-map_metadata','-1','-movflags','+faststart',out])
    result=probe(out)
    record={'schema':'netfeel-speed/1','source':str(source),'sourceSha256':identity,
            'inputSpeed':args.input_speed,'targetSpeed':args.target_speed,'appliedMultiplier':ratio,
            'currentSha256':sha(out),'duration':float(result['format']['duration'])}
    save(target/'speed.json',record)
    print(str(target/'speed.json'))

if __name__=='__main__':main()
