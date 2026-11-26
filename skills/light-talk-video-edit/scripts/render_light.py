"""Configuration-driven 720x1280 light editorial talking-head renderer."""
from __future__ import annotations
import argparse
import bisect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

W,H=720,1280
COLORS=dict(ink='#283F3C',green='#376F62',sage='#AAC4B4',peach='#D49C7F',paper='#F7F7F1',muted='#7D8B83')
ICONS={'city','globe','edu','shield','check','chat'}
KINDS={'talking','photo','gateway','identity','stability','end'}

def resolve(root,value):
    p=Path(os.path.expandvars(os.path.expanduser(str(value))))
    return p if p.is_absolute() else (root/p).resolve()

def probe(ff,path):
    p=subprocess.run([ff,'-hide_banner','-i',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    m=re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)',p.stderr)
    if not m:raise ValueError(f'Cannot read media duration: {path}\n{p.stderr[-1500:]}')
    return {'duration':int(m[1])*3600+int(m[2])*60+float(m[3]),'audio':bool(re.search(r'Stream .*Audio:',p.stderr))}

def remap_captions(captions,keep):
    result=[];offset=0
    for a,b in keep:
        for s,e,text in captions:
            lo,hi=max(s,a),min(e,b)
            if hi>lo:result.append([offset+lo-a,offset+hi-a,text])
        offset+=b-a
    return sorted(result)

class Project:
    def __init__(self,path):
        self.path=Path(path).resolve();self.root=self.path.parent
        self.data=json.loads(self.path.read_text(encoding='utf-8-sig'))
        c=self.data
        executable=c.get('ffmpeg') or os.environ.get('FFMPEG_EXE') or shutil.which('ffmpeg')
        if not executable:raise ValueError('Set ffmpeg in config, FFMPEG_EXE, or PATH.')
        self.ff=str(resolve(self.root,executable)) if Path(executable).is_absolute() or '/' in executable or '\\' in executable else executable
        self.source=resolve(self.root,c['source']);self.output=resolve(self.root,c['output'])
        if not self.source.is_file():raise ValueError(f'Source not found: {self.source}')
        if self.source==self.output:raise ValueError('Output must differ from source.')
        if self.output.suffix.lower()!='.mp4':raise ValueError('Output must be .mp4.')
        self.meta=probe(self.ff,self.source);self.fps=float(c.get('fps',25))
        if not 1<=self.fps<=60:raise ValueError('fps must be between 1 and 60.')
        self.keep=c.get('keep') or [[0,self.meta['duration']]]
        for a,b in self.keep:
            if not 0<=a<b<=self.meta['duration']+.02:raise ValueError(f'Invalid keep range: {[a,b]}')
        self.duration=sum(b-a for a,b in self.keep)
        if 'captions' in c and 'source_captions' in c:raise ValueError('Choose captions OR source_captions, not both.')
        self.captions=sorted(c.get('captions',remap_captions(c.get('source_captions',[]),self.keep)))
        for i,(a,b,line) in enumerate(self.captions):
            if not 0<=a<b<=self.duration+.05 or not isinstance(line,str) or not line.strip():raise ValueError(f'Invalid caption: {[a,b,line]}')
            if i and a<self.captions[i-1][1]-.001:raise ValueError('Caption intervals overlap.')
        self.starts=[x[0] for x in self.captions]
        self.theme={**COLORS,**c.get('theme',{})}
        for value in self.theme.values():ImageColor.getrgb(value)
        self.brand={**dict(title='口播观察',english='PERSPECTIVE',footer='口播观察'),**c.get('brand',{})}
        self.pip=c.get('pip_crop')
        if self.pip:
            x,y,w,h=self.pip
            if not (0<=x<1 and 0<=y<1 and w>0 and h>0 and x+w<=1.001 and y+h<=1.001):raise ValueError('pip_crop must fit normalized source.')
        self.scenes=sorted(c.get('scenes',[]),key=lambda s:s['start'])
        for i,s in enumerate(self.scenes):
            if s['kind'] not in KINDS or not 0<=s['start']<s['end']<=self.duration+.05:raise ValueError(f'Invalid scene: {s}')
            if i and s['start']<self.scenes[i-1]['end']:raise ValueError('Scene intervals overlap.')
            if s.get('photo'):
                s['photo']=str(resolve(self.root,s['photo']))
                if not Path(s['photo']).is_file():raise ValueError('Photo not found: '+s['photo'])
            items=s.get('items',[])
            if s['kind']=='gateway' and len(items)!=3:raise ValueError('gateway needs exactly three items.')
            if s['kind'] in {'identity','stability'} and not 1<=len(items)<=3:raise ValueError('identity/stability need 1-3 items.')
            for item in items:
                if item.get('icon','check') not in ICONS:raise ValueError('Unknown icon: '+item['icon'])
            appear=s.get('appear',[s['start']+.3+j*.45 for j in range(len(items))])
            if len(appear)!=len(items) or any(not s['start']<=v<s['end'] for v in appear):raise ValueError('appear must match items and fit scene.')
            s['appear']=appear
        self.audio=resolve(self.root,c['audio_source']) if c.get('audio_source') else None
        if self.audio:
            am=probe(self.ff,self.audio)
            if not am['audio'] or abs(am['duration']-self.duration)>1/self.fps+.02:raise ValueError('audio_source must have audio and match edited duration to one frame.')
        self.work=self.output.parent/('.'+self.output.stem+'_work')

class Painter:
    def __init__(self,p):
        self.p=p;self.c=p.theme;self.fonts={};self.caps={};self.scene_cache={}
        supplied=p.data.get('fonts',{})
        win=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        candidates={
            'regular':[win/'msyh.ttc',Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')],
            'bold':[win/'msyhbd.ttc',Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')],
            'latin':[win/'arial.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')],
            'serif':[win/'georgia.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf')]}
        self.font_paths={}
        for key,paths in candidates.items():
            if key in supplied:paths=[resolve(p.root,supplied[key])]
            choice=next((x for x in paths if x.is_file()),None)
            if not choice and key in {'latin','serif'}:choice=self.font_paths.get('regular')
            if not choice:raise ValueError(f'Set fonts.{key} to a font covering the project language.')
            self.font_paths[key]=choice
        yy=np.arange(H)[:,None];xx=np.arange(W)[None,:];glow=np.exp(-((xx-650)**2/460**2+(yy-180)**2/440**2))
        ar=np.empty((H,W,3),np.uint8);rgb=ImageColor.getrgb(self.c['paper'])
        for ch in range(3):ar[:,:,ch]=np.clip(rgb[ch]-glow*[5,1,4][ch],0,255).astype(np.uint8)
        self.paper=Image.fromarray(ar).convert('RGBA');d=ImageDraw.Draw(self.paper)
        d.arc((415,-150,940,375),125,315,fill='#E1EADF',width=2);d.line((44,94,676,94),fill='#E1E8DE')
        self.text(self.paper,(44,39),p.brand['english'],16,'green',role='regular')
        self.text(self.paper,(676,36),p.brand['title'],20,'muted',anchor='rt')
        self.text(self.paper,(44,1223),p.brand['footer'],16,'muted')
        self.text(self.paper,(676,1224),p.brand['english'],13,'muted',anchor='rt')
        self.shade=Image.new('RGBA',(W,H));ar=np.zeros((H,W,4),np.uint8)
        for y in range(H):ar[y,:,3]=int(max(0,1-y/320)*38+max(0,(y-1030)/250)*45)
        self.shade=Image.fromarray(ar)
        for _,_,line in p.captions:self.caption(line)

    def f(self,n,role='regular'):
        key=(n,role)
        if key not in self.fonts:self.fonts[key]=ImageFont.truetype(str(self.font_paths[role]),n)
        return self.fonts[key]
    def text(self,im,xy,s,n=32,color='ink',role='regular',anchor=None):
        ImageDraw.Draw(im).text(xy,str(s),font=self.f(n,role),fill=self.c.get(color,color),anchor=anchor)
    def fit(self,im,xy,s,size,width,color='ink',role='bold',minimum=16):
        while size>minimum and self.f(size,role).getlength(str(s))>width:size-=1
        if self.f(size,role).getlength(str(s))>width:raise ValueError(f'Text does not fit: {s}')
        self.text(im,xy,s,size,color,role)
    @staticmethod
    def mask(size,r=28):
        m=Image.new('L',size);ImageDraw.Draw(m).rounded_rectangle((0,0,size[0]-1,size[1]-1),r,fill=255);return m
    def card(self,im,box,fill='#FFFFFF',radius=28,shade=True):
        if shade:
            sh=Image.new('RGBA',im.size);b=(box[0],box[1]+8,box[2],box[3]+8)
            ImageDraw.Draw(sh).rounded_rectangle(b,radius,fill=(35,65,51,19));im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
        ImageDraw.Draw(im).rounded_rectangle(box,radius,fill=self.c.get(fill,fill))
    def photo(self,im,path,box):
        x,y,w,h=box
        tile=ImageOps.fit(Image.open(path).convert('RGB'),(w,h),Image.Resampling.LANCZOS,centering=(.5,.55))
        im.paste(tile,(x,y),self.mask((w,h)))
    def icon(self,im,kind,xy,size=70,color='green'):
        tile=Image.new('RGBA',(100,100));d=ImageDraw.Draw(tile);c=self.c.get(color,color);w=3
        if kind=='city':
            for box in [(14,38,36,82),(40,15,65,82),(69,46,88,82)]:d.rounded_rectangle(box,3,outline=c,width=w)
            d.line((9,84,92,84),fill=c,width=w)
        elif kind=='globe':
            d.ellipse((15,14,85,84),outline=c,width=w);d.ellipse((34,14,66,84),outline=c,width=2);d.line((16,49,84,49),fill=c,width=2)
        elif kind=='edu':
            d.line([(10,35),(49,15),(88,35),(49,55),(10,35)],fill=c,width=w)
            d.line([(26,46),(26,66),(49,76),(72,66),(72,46)],fill=c,width=w);d.line((87,36,87,65),fill=c,width=w)
        elif kind=='shield':
            d.line([(49,10),(81,23),(77,59),(49,83),(21,59),(17,23),(49,10)],fill=c,width=w);d.line([(33,44),(46,57),(67,33)],fill=c,width=4)
        elif kind=='check':d.line([(21,49),(42,69),(79,29)],fill=c,width=4)
        elif kind=='chat':
            d.rounded_rectangle((15,16,84,70),14,outline=c,width=w);d.line([(32,70),(30,85),(49,70)],fill=c,width=w)
        else:raise ValueError('Unknown icon: '+kind)
        im.alpha_composite(tile.resize((size,size),Image.Resampling.LANCZOS),tuple(map(int,xy)))
    def pip(self,im,source,xy=(489,123),size=(186,217)):
        if not self.p.pip:return
        x,y,w,h=self.p.pip;crop=source.crop((round(x*W),round(y*H),round((x+w)*W),round((y+h)*H)))
        face=ImageOps.fit(crop,size,Image.Resampling.LANCZOS)
        self.card(im,(xy[0]-4,xy[1]-4,xy[0]+size[0]+4,xy[1]+size[1]+4),radius=30,shade=False)
        im.paste(face,xy,self.mask(size,26))
    def caption(self,line):
        if line in self.caps:return self.caps[line]
        n=34;f=self.f(n,'bold');lines=[];current=''
        for ch in line:
            if ch=='\n' or f.getlength(current+ch)>570:
                if current:lines.append(current)
                current='' if ch=='\n' else ch
            else:current+=ch
        if current:lines.append(current)
        if len(lines)>2:raise ValueError('Split long caption into timed events: '+line)
        width=math.ceil(max(f.getlength(s) for s in lines))+50;left=(W-width)//2
        im=Image.new('RGBA',(W,130));self.card(im,(left,5,left+width,70 if len(lines)==1 else 115),radius=20)
        for k,s in enumerate(lines):
            x=(W-f.getlength(s))/2;flags=[False]*len(s)
            for keyword in self.p.data.get('emphasis',[]):
                start=s.find(keyword)
                if start>=0:
                    for j in range(start,start+len(keyword)):flags[j]=True
            for i,ch in enumerate(s):
                self.text(im,(x,16+k*45),ch,n,'green' if flags[i] else 'ink','bold');x+=f.getlength(ch)
        self.caps[line]=im;return im
    @staticmethod
    def put(im,tile,xy,p=1):
        p=1-(1-max(0,min(1,p)))**3
        if p<=0:return
        if p<.999:
            tile=tile.copy();tile.putalpha(tile.getchannel('A').point(lambda a:int(a*p)))
        im.alpha_composite(tile,(round(xy[0]),round(xy[1]+16*(1-p))))

    def header(self,s):
        im=self.paper.copy()
        self.fit(im,(44,129),str(s.get('number',''))+'  /  '+s.get('kicker',''),18,420,'green','regular')
        self.fit(im,(43,174),s.get('title',''),65,420 if self.p.pip else 630)
        ImageDraw.Draw(im).rounded_rectangle((46,265,77,269),2,fill=self.c['peach'])
        self.fit(im,(46,285),s.get('subtitle',''),24,620,'muted','regular')
        if self.p.pip:self.card(im,(485,119,679,344),radius=31)
        return im
    def blueprint(self,s):
        key=id(s)
        if key in self.scene_cache:return self.scene_cache[key]
        kind=s['kind'];im=self.header(s);tiles=[]
        if kind=='photo':
            im=self.paper.copy();self.text(im,(44,132),s.get('kicker','PERSPECTIVE'),16,'green')
            self.fit(im,(42,178),s.get('title',''),62,632);self.fit(im,(46,270),s.get('subtitle',''),27,626,'muted','regular')
            self.card(im,(40,341,680,1021),radius=33)
            if s.get('photo'):self.photo(im,s['photo'],(46,347,628,668))
            else:self.card(im,(46,347,674,1015),'#EAF1E9',shade=False)
            self.fit(im,(48,1042),s.get('credit',''),14,625,'muted','regular')
        elif kind=='gateway':
            self.card(im,(40,370,680,677),radius=31)
            if s.get('photo'):self.photo(im,s['photo'],(46,376,628,295))
            else:
                self.card(im,(46,376,674,671),'#E8F0E6',shade=False)
                self.icon(im,'globe',(281,397),155);self.fit(im,(78,581),s.get('panel_title',s.get('subtitle','')),33,565)
            if s.get('credit'):self.fit(im,(48,686),s['credit'],13,620,'muted','regular')
            self.card(im,(40,719,680,993))
            for i,item in enumerate(s['items']):
                tile=Image.new('RGBA',(180,235));d=ImageDraw.Draw(tile)
                d.ellipse((39,10,141,112),fill=self.c['green'] if i==1 else '#EDF3ED')
                self.icon(tile,item.get('icon','check'),(55,25),72,'#FFFFFF' if i==1 else 'green')
                self.fit(tile,(21,140),item['label'],29,145)
                self.fit(tile,(21,192),item.get('secondary',''),12,145,'muted','regular')
                tiles.append((tile,(54+i*216,741)))
        elif kind=='identity':
            d=ImageDraw.Draw(im);d.ellipse((365,364,675,674),fill='#E7EFE4');d.ellipse((90,444,390,744),fill='#F2E7DC')
            back=Image.new('RGBA',(580,252));self.card(back,(12,12,568,240),'#E4ECE1',shade=False)
            im.alpha_composite(back.rotate(-5,resample=Image.Resampling.BICUBIC,expand=True),(50,389))
            self.card(im,(65,384,655,637));self.text(im,(96,414),self.p.brand['english'],15,'green')
            self.fit(im,(95,470),s.get('card_title',s.get('title','')),49,515)
            self.fit(im,(98,567),s.get('card_subtitle',s.get('subtitle','')),21,515,'muted','regular')
            for i,item in enumerate(s['items']):
                tile=Image.new('RGBA',(220,287));self.card(tile,(10,7,210,261),radius=26)
                self.text(tile,(184,26),f'0{i+1}',17,'muted',anchor='rt')
                ImageDraw.Draw(tile).ellipse((64,62,156,154),fill='#F5E9DF' if i==1 else '#EAF1E9')
                self.icon(tile,item.get('icon','check'),(72,70),76)
                self.fit(tile,(28,193),item['label'],25,167)
                tiles.append((tile,(34+i*216,733)))
        elif kind=='stability':
            self.card(im,(40,370,680,757),radius=30)
            d=ImageDraw.Draw(im);d.ellipse((198,404,522,728),fill='#EDF3EA')
            d.polygon([(190,497),(360,423),(530,497),(360,510)],fill='#B5CDBE')
            d.rectangle((190,497,530,515),fill='#75A08B');d.rectangle((227,525,499,674),fill='#E2EADB')
            for x in [239,303,367,431]:self.card(im,(x,530,x+39,666),radius=7,shade=False)
            for box,col in [((190,674,534,690),'#C1D3C1'),((181,692,543,704),'#9ABAA4'),((166,708,558,719),'#D6E2D1')]:self.card(im,box,col,4,False)
            self.icon(im,'shield',(522,622),95)
            for i,item in enumerate(s['items']):
                tile=Image.new('RGBA',(648,86));self.card(tile,(5,3,643,75),radius=20)
                self.card(tile,(24,20,65,59),'#EBF1E7',12,False)
                self.text(tile,(44,28),f'0{i+1}',14,'green',anchor='mt')
                self.fit(tile,(86,20),item['label'],28,470);self.icon(tile,item.get('icon','check'),(576,16),45)
                tiles.append((tile,(36,805+i*90)))
        self.scene_cache[key]=(im,tiles);return im,tiles

    def portrait(self,frame,s=None):
        im=frame.convert('RGBA');im.alpha_composite(self.shade)
        self.card(im,(40,34,258,84),radius=18);self.fit(im,(60,46),self.p.brand['title'],21,178)
        if s and s.get('title'):
            end=s['kind']=='end';box=(39,854,681,1020) if end else (41,115,679,295)
            self.card(im,box,radius=25)
            self.fit(im,(box[0]+28,box[1]+28),s['title'],42 if end else 55,580)
            self.fit(im,(box[0]+30,box[1]+109),s.get('subtitle',''),25,574,'muted','regular')
        return im
    def frame(self,source,t):
        s=next((s for s in self.p.scenes if s['start']<=t<s['end']),None)
        if s is None or s['kind'] in {'talking','end'}:im=self.portrait(source,s)
        else:
            base,tiles=self.blueprint(s);im=base.copy()
            for (tile,xy),at in zip(tiles,s['appear']):self.put(im,tile,xy,(t-at)/.45)
            if s['kind']=='gateway':
                for i,(a,b) in enumerate([(232,270),(450,488)]):
                    if t>=max(s['appear'][i:i+2]):
                        d=ImageDraw.Draw(im);d.line((a,800,b,800),fill=self.c['sage'],width=3)
                        d.line([(b-8,795),(b,800),(b-8,805)],fill=self.c['sage'],width=3)
            self.pip(im,source,(491,759),(168,196)) if s['kind']=='photo' else self.pip(im,source)
            if t-s['start']<.18:im=Image.blend(self.portrait(source),im,min(1,(t-s['start'])/.18))
        idx=bisect.bisect_right(self.p.starts,t)-1
        if idx>=0 and t<self.p.captions[idx][1]:im.alpha_composite(self.caption(self.p.captions[idx][2]),(0,1101))
        d=ImageDraw.Draw(im);d.rounded_rectangle((44,1254,676,1257),2,fill='#DCE6DC')
        d.rounded_rectangle((44,1254,44+int(632*min(1,t/self.p.duration)),1257),2,fill=self.c['green'])
        if t>self.p.duration-.25:im=Image.blend(im,Image.new('RGBA',(W,H),self.c['paper']),min(1,(t-self.p.duration+.25)/.25))
        return im.convert('RGB')

def run_logged(command,path):
    with path.open('w',encoding='utf-8') as log:
        result=subprocess.run(command,stdout=log,stderr=log)
    if result.returncode:raise RuntimeError(f'Command failed; see {path}')

def prepare(p):
    p.output.parent.mkdir(parents=True,exist_ok=True);p.work.mkdir(exist_ok=True)
    graphs=[];audio=p.meta['audio'] and not p.audio
    for i,(a,b) in enumerate(p.keep):
        graphs.append(f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]')
        if audio:graphs.append(f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]')
    labels=''.join(f'[v{i}]'+(f'[a{i}]' if audio else '') for i in range(len(p.keep)))
    graphs.append(labels+f'concat=n={len(p.keep)}:v=1:a={int(audio)}[v]'+('[a]' if audio else ''))
    graphs.append(f'[v]fps={p.fps},scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[vout]')
    if audio:graphs.append('[a]'+('highpass=f=75,loudnorm=I=-16:TP=-1.5:LRA=8' if p.data.get('normalize_voice') else 'anull')+'[aout]')
    clean=p.work/'clean.mp4'
    cmd=[p.ff,'-hide_banner','-y','-i',str(p.source),'-filter_complex',';'.join(graphs),'-map','[vout]']
    if audio:cmd+=['-map','[aout]','-c:a','aac','-b:a','160k']
    else:cmd+=['-an']
    cmd+=['-c:v','libx264','-preset','fast','-crf','17','-threads','4','-pix_fmt','yuv420p',str(clean)]
    run_logged(cmd,p.work/'prepare.log');return clean,audio

def stamp(t):
    ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',required=True);ap.add_argument('--check',action='store_true');ap.add_argument('--preview',action='store_true');ap.add_argument('--overwrite',action='store_true');a=ap.parse_args()
    p=Project(a.config);paint=Painter(p)
    for s in p.scenes:
        if s['kind'] not in {'talking','end'}:paint.blueprint(s)
    if a.check:print(json.dumps({'duration':p.duration,'scenes':len(p.scenes),'captions':len(p.captions),'fps':p.fps},ensure_ascii=False));return
    if not a.preview and p.output.exists() and not a.overwrite:raise ValueError(f'Output exists; choose a new version or --overwrite: {p.output}')
    clean,has_audio=prepare(p)
    previews=p.work/'preview';previews.mkdir(exist_ok=True)
    times=p.data.get('preview_times') or sorted({min(p.duration/2,.5),min(p.duration-.05,1.5),*[min(s['end']-.05,s['start']+.7) for s in p.scenes],*[min(s['end']-.05,max(s.get('appear') or [s['start']])+.6) for s in p.scenes]})
    if any(not 0<=t<p.duration for t in times):raise ValueError('Preview times must fit output duration.')
    if a.preview:
        for t in times:
            raw=subprocess.check_output([p.ff,'-v','error','-ss',str(t),'-i',str(clean),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
            if len(raw)!=W*H*3:raise RuntimeError('Preview frame missing.')
            paint.frame(Image.frombytes('RGB',(W,H),raw),t).save(previews/f'{t:07.2f}.jpg',quality=94)
        print(f'Previews: {previews}');return
    visual=p.work/'visual.mp4';size=W*H*3;i=0
    with (p.work/'decode.log').open('w') as dl,(p.work/'encode.log').open('w') as el:
        dec=subprocess.Popen([p.ff,'-v','error','-i',str(clean),'-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE,stderr=dl)
        enc=subprocess.Popen([p.ff,'-hide_banner','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','720x1280','-framerate',str(p.fps),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18','-threads','4','-pix_fmt','yuv420p',str(visual)],stdin=subprocess.PIPE,stderr=el)
        try:
            while True:
                raw=dec.stdout.read(size)
                if not raw:break
                if len(raw)!=size:raise RuntimeError('Incomplete raw frame.')
                t=i/p.fps;frame=paint.frame(Image.frombytes('RGB',(W,H),raw),t);enc.stdin.write(frame.tobytes())
                if any(abs(t-v)<.5/p.fps for v in times):frame.save(previews/f'{t:07.2f}.jpg',quality=94)
                i+=1
                if i%round(p.fps*10)==0:print(f'{t:.1f}/{p.duration:.1f}s',flush=True)
        except BaseException:
            dec.terminate();enc.terminate();raise
        finally:
            dec.stdout.close();enc.stdin.close();dc=dec.wait();ec=enc.wait()
        if dc or ec:raise RuntimeError('Render failed; inspect decode/encode logs.')
    cmd=[p.ff,'-hide_banner','-y','-i',str(visual)]
    audio=p.audio or (clean if has_audio else None)
    if audio:
        cmd+=['-i',str(audio),'-map','0:v','-map','1:a:0','-c:v','copy','-c:a','copy' if p.data.get('copy_audio') else 'aac']
    else:cmd+=['-map','0:v','-an','-c:v','copy']
    cmd+=['-movflags','+faststart','-shortest',str(p.output)];run_logged(cmd,p.work/'mux.log')
    p.output.with_suffix('.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{s}' for i,(a,b,s) in enumerate(p.captions))+'\n',encoding='utf-8-sig')
    saved={**p.data,'source':str(p.source),'output':str(p.output),'ffmpeg':p.ff}
    if p.audio:saved['audio_source']=str(p.audio)
    if p.data.get('fonts'):saved['fonts']={k:str(resolve(p.root,v)) for k,v in p.data['fonts'].items()}
    p.output.with_suffix('.project.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
    credits=[s.get('credit','')+' '+s.get('photo','') for s in p.scenes if s.get('photo')]
    if credits:p.output.with_suffix('.credits.txt').write_text('\n'.join(credits)+'\n',encoding='utf-8')
    print(f'FINAL {p.output} / {i} frames',flush=True)

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,KeyError,OSError) as e:print(f'ERROR: {e}',file=sys.stderr);sys.exit(1)
