"""Render with the bundled standalone engine; inspect the actual encoded MP4."""
import argparse,json,subprocess,sys
from pathlib import Path
from common import SKILL,setup_path,need_tools,probe,run

def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    video=sub.add_parser('video');video.add_argument('project',type=Path);video.add_argument('output',type=Path);video.add_argument('--segments',type=int,default=2)
    still=sub.add_parser('stills');still.add_argument('project',type=Path);still.add_argument('output',type=Path);still.add_argument('--times',required=True)
    check=sub.add_parser('check');check.add_argument('video',type=Path)
    args=ap.parse_args();setup_path();need_tools('ffmpeg','ffprobe')
    if args.command=='check':
        data=probe(args.video);v=next(s for s in data['streams'] if s['codec_type']=='video');a=next(s for s in data['streams'] if s['codec_type']=='audio')
        run(['ffmpeg','-v','error','-i',args.video,'-f','null','-'])
        p=subprocess.run(['ffmpeg','-hide_banner','-i',str(args.video),'-vn','-af','loudnorm=I=-15.5:TP=-1.2:LRA=9:print_format=json','-f','null','-'],capture_output=True)
        if p.returncode:raise RuntimeError(p.stderr.decode('utf-8','replace')[-4000:])
        s=p.stderr.decode('utf-8','replace');loud=json.loads(s[s.rfind('{'):s.rfind('}')+1])
        result={'video':{k:v.get(k) for k in ['width','height','duration','nb_frames','avg_frame_rate','codec_name']},'audio':{k:a.get(k) for k in ['duration','sample_rate','codec_name']},'loudness':{'LUFS':loud['input_i'],'truePeak_dBTP':loud['input_tp']},'completeDecode':True}
        print(json.dumps(result,ensure_ascii=False));return
    need_tools('node');engine=SKILL/'scripts/render_project.mjs'
    if args.command=='video':
        if args.segments<1:ap.error('segments must be positive')
        cmd=['node',str(engine),'video',str(args.project),str(args.output),'--segments',str(args.segments)]
    else:cmd=['node',str(engine),'stills',str(args.project),str(args.output),'--times',args.times]
    subprocess.run(cmd,check=True)

if __name__=='__main__':main()
