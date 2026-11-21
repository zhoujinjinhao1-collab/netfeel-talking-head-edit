"""Build an editable portrait project from a verified-speed rough cut and timed plan."""
import argparse,copy,math,re,shutil
from pathlib import Path
from common import SKILL,setup_path,need_tools,probe,sha,load,save,new_dir,run

TYPES={'question','impact','quote','underline','stages','keywords','identity','items','pivot','evidence'}

def timecode(s):
    h,m,sec=s.strip().replace(',','.').split(':');return int(h)*3600+int(m)*60+float(sec)

def read_captions(path):
    if path.suffix.lower()=='.srt':
        rows=[]
        for block in re.split(r'\n\s*\n',path.read_text(encoding='utf-8-sig').replace('\r','').strip()):
            lines=block.splitlines();i=next((i for i,line in enumerate(lines) if '-->' in line),None)
            if i is None:continue
            a,b=lines[i].split('-->')
            rows.append({'start':timecode(a),'end':timecode(b),'text':' '.join(lines[i+1:]),'highlights':[]})
        return rows
    data=load(path);return data['captions'] if isinstance(data,dict) else data

def finite(n):return isinstance(n,(float,int)) and not isinstance(n,bool) and math.isfinite(n)

def interval(row,duration):
    if not all(finite(row.get(k)) for k in ['start','end']) or not 0<=row['start']<row['end']<=duration+.06:
        raise ValueError('Invalid interval: '+str(row))

def shifted(row,start):
    if isinstance(row,list):return [shifted(x,start) for x in row]
    if isinstance(row,dict):return {k:(v-start if k in {'start','end','at','line2At','promptAt','time'} and finite(v) else shifted(v,start)) for k,v in row.items()}
    return row

def camera_value(keys,t):
    for (a,z0),(b,z1) in zip(keys,keys[1:]):
        if t<=b:
            q=max(0,min(1,(t-a)/(b-a)));q=1-(1-q)**4 if b-a<.6 else q*q*(3-2*q)
            return math.exp(math.log(z0)+(math.log(z1)-math.log(z0))*q)
    return keys[-1][1]

def validate(plan,captions,duration):
    if not captions:raise ValueError('Captions are empty; supply checked source speech timings')
    last=-1
    for row in captions:
        interval(row,duration)
        if row['start']<last-.001:raise ValueError('Overlapping captions')
        if not isinstance(row.get('text'),str) or not row['text'].strip():raise ValueError('Empty subtitle')
        last=row['end']
    previous=-1
    for row in plan.get('scenes',[]):
        interval(row,duration)
        if row.get('type') not in TYPES:raise ValueError('Unsupported scene type')
        if row['start']<previous-.001:raise ValueError('Main scenes overlap; choose one main reading target')
        previous=row['end']
        if row['type'] in {'items','keywords','stages'} and not 1<=len(row.get('items',[]))<=3:raise ValueError('Use 1–3 items per scene')
        for item in row.get('items',[]):
            if isinstance(item,dict) and (not finite(item.get('at')) or not row['start']<=item['at']<row['end']):raise ValueError('Item timing outside its scene')
    for note in plan.get('notes',[]):interval(note,duration)
    keys=plan.get('camera',{}).get('keys',[[0,1.02],[duration,1.02]])
    anchor=plan.get('camera',{}).get('anchor',[600,860])
    if len(anchor)!=2 or not all(finite(v) for v in anchor):raise ValueError('Camera anchor needs two pixel coordinates')
    if len(keys)<2 or keys[0][0]!=0:raise ValueError('Camera keys must begin at zero and have at least two keys')
    for i,(t,z) in enumerate(keys):
        if not finite(t) or not finite(z) or not 0<=t<=duration+.06 or z<1 or z>2:raise ValueError('Invalid camera key')
        if i and t<=keys[i-1][0]:raise ValueError('Camera key times must strictly increase')
    return keys

def srt_stamp(t):
    n=round(t*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'

def mix(project,talk,start,duration,plan,base):
    import numpy as np
    import wave
    audio=project/'assets/audio';audio.mkdir();sr=48000;n=round(duration*sr)
    run(['ffmpeg','-n','-v','error','-ss',str(start),'-i',talk,'-t',str(duration),'-vn','-af','highpass=f=70,loudnorm=I=-16:TP=-2:LRA=9','-ar',sr,'-ac','2',audio/'voice.wav'])
    def read(file,offset=0):
        data=run(['ffmpeg','-v','error','-ss',offset,'-i',file,'-t',duration,'-f','f32le','-ac','2','-ar',sr,'-'],raw=True)
        x=np.frombuffer(data,np.float32).reshape(-1,2).astype(float)
        return np.pad(x[:n],((0,max(0,n-len(x))),(0,0)))
    def write(file,x):
        with wave.open(str(file),'wb') as w:
            w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes((np.clip(x,-1,1)*32767).astype('<i2').tobytes())
    voice=read(audio/'voice.wav');music=np.zeros((n,2));v_rms=float(np.sqrt(np.mean(voice**2)))
    if v_rms<1e-6:raise ValueError('Original speech is silent')
    selection=copy.deepcopy(plan.get('audio',{}).get('music',{}));mode=selection.get('mode')
    if mode=='track':
        file=Path(selection['path']);file=file if file.is_absolute() else base/file
        offset=float(selection.get('offset',0))
        if offset<0 or not selection.get('source'):raise ValueError('Music needs a nonnegative offset and a rights/source record')
        length=float(probe(file)['format']['duration'])
        if length+.04<offset+start+duration:raise ValueError('Music does not cover this range; choose a longer track, do not loop silently')
        dest=audio/('music-source'+file.suffix.lower());shutil.copy2(file,dest)
        music=read(dest,offset+start);rms=float(np.sqrt(np.mean(music**2)))
        if rms<1e-8:raise ValueError('Selected music is silent')
        below=float(selection.get('belowVoiceDb',-20))
        if not -40<=below<=-8:raise ValueError('Music gain is outside the speech-first range')
        music*=v_rms/rms*10**(below/20);t=np.arange(n)/sr
        envelope=np.minimum(np.clip((t+start)/.5,0,1),np.clip((duration-t)/.5,0,1))
        for cue in plan.get('audio',{}).get('sfx',[]):
            if cue['name']=='impact':envelope*=1-.65*np.exp(-((t-(cue['time']-start))/.28)**2)
        music*=envelope[:,None];selection['path']=str(dest.relative_to(project));selection['sha256']=sha(dest)
    elif mode!='none':raise ValueError('Bind a real music track or explicitly choose mode:none with a reason')
    elif not selection.get('reason'):raise ValueError('Record why this project has no music')
    effects=np.zeros((n,2));rng=np.random.default_rng(11)
    for cue in plan.get('audio',{}).get('sfx',[]):
        name=cue['name'];gain=float(cue.get('gain',.055));stamp=float(cue['time'])-start
        if name not in {'tick','click','pop','swish','impact'} or not 0<=gain<=.15:raise ValueError('Unsupported or over-loud SFX cue')
        seconds={'tick':.05,'click':.07,'pop':.13,'swish':.23,'impact':.65}[name];t=np.arange(round(sr*seconds))/sr
        noise=rng.standard_normal(len(t))
        if name in {'tick','click'}:x=(noise+.5*np.sin(2*np.pi*3000*t))*np.exp(-t*200)
        elif name=='pop':x=np.sin(2*np.pi*(800*t+5*(1-np.exp(-t*50))))*np.exp(-t*38)
        elif name=='swish':x=(noise-np.convolve(noise,np.ones(12)/12,'same'))*np.sin(np.pi*t/seconds)**2
        else:x=np.sin(2*np.pi*(65*t+3*(1-np.exp(-t*10))))*np.exp(-t*12)+.25*noise*np.exp(-t*70)
        x=x/(np.max(np.abs(x))+1e-12)*gain;k=round(stamp*sr);a=max(0,k);b=min(n,k+len(x))
        if b>a:effects[a:b]+=x[a-k:b-k,None]
    write(audio/'music-stem.wav',music);write(audio/'sfx-stem.wav',effects)
    bus=voice+music+effects;peak=float(np.max(np.abs(bus)));scale=min(1,.92/max(peak,1e-9));write(audio/'premix.wav',bus*scale)
    run(['ffmpeg','-n','-v','error','-i',audio/'premix.wav','-af','alimiter=limit=0.92:level=false:latency=true,loudnorm=I=-15.5:TP=-1.2:LRA=9','-ar',sr,'-ac','2','-t',duration,project/'mix.wav'])
    save(project/'mix-recipe.json',{'voiceRMS':v_rms,'musicBelowVoiceRMSdB':selection.get('belowVoiceDb',-20),'premixScale':scale,'music':selection,'sfx':plan.get('audio',{}).get('sfx',[]),'sourceStart':start})
    (project/'发布用音乐署名.txt').write_text(selection.get('attribution','本期无须单独音乐署名；详见mix-recipe.json的来源记录。'),encoding='utf-8')

def make_preview(project):
    html=(project/'index.html').read_text(encoding='utf-8')
    ui='''<style>html,body{width:100%;height:auto;overflow:auto;background:#14201c}body{padding:20px;display:flex;align-items:center;flex-direction:column}#player{width:324px;height:576px;overflow:hidden}#stage{transform:scale(.3);transform-origin:top left}#controls{font:16px system-ui;color:#fff;display:flex;gap:15px;margin:15px}button{background:#ffe344;border:0;border-radius:6px;padding:8px 20px}input{width:250px;accent-color:#ffe344}</style>'''
    html=html.replace('</head>',ui+'</head>').replace('<body><div id="stage">','<body><div id="player"><div id="stage">').replace('</div><script src="config.js">','</div></div><script src="config.js">')
    controls='''<div id="controls"><button id="play">播放</button><input id="seek" type="range" min="0" step="0.016667" value="0"></div><audio id="sound" src="mix.wav"></audio><script>const audio=document.getElementById('sound'),seek=document.getElementById('seek'),button=document.getElementById('play');seek.max=FILM.end;let busy=false;async function draw(t){if(busy)return;busy=true;try{await renderAt(Math.min(FILM.end-1/60,t));seek.value=t}finally{busy=false}}async function loop(){if(!audio.paused){await draw(audio.currentTime);requestAnimationFrame(loop)}}button.onclick=async()=>{await READY;if(audio.paused){if(audio.currentTime>=FILM.end)audio.currentTime=0;await audio.play();button.textContent='暂停';loop()}else{audio.pause();button.textContent='播放'}};seek.oninput=()=>{audio.currentTime=+seek.value;draw(+seek.value)};audio.onended=()=>button.textContent='播放';</script>'''
    (project/'preview.html').write_text(html.replace('</body>',controls+'</body>'),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ['prepared','captions','plan','dest']:ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--start',type=float,default=0);ap.add_argument('--end',type=float)
    args=ap.parse_args();setup_path();need_tools('ffmpeg','ffprobe')
    # Fail dependency validation before creating any output directory.
    import numpy
    source=args.prepared.resolve()/'talk.mp4';speed=load(args.prepared/'speed.json');plan=load(args.plan);captions=read_captions(args.captions)
    if speed.get('schema')!='netfeel-speed/1' or sha(source)!=speed.get('currentSha256'):raise ValueError('Prepared talk does not match its speed record')
    if abs(speed['targetSpeed']-float(plan.get('targetSpeed',1.1)))>1e-8:raise ValueError('Plan targetSpeed conflicts with actual prepared speech')
    info=probe(source);duration=float(info['format']['duration']);keys=validate(plan,captions,duration)
    start=args.start;end=duration if args.end is None else args.end
    if not all(finite(v) for v in [start,end]) or not 0<=start<end<=duration+.01:raise ValueError('Invalid source range')
    for c in captions:
        if c['start']+.04<start<c['end']-.04 or c['start']+.04<end<c['end']-.04:raise ValueError('Sample boundary cuts through a subtitle; choose complete sentences')
    length=end-start;project=new_dir(args.dest);(project/'assets/frames').mkdir(parents=True);(project/'assets/fonts').mkdir();(project/'来源').mkdir()
    for file in (SKILL/'assets/template').iterdir():shutil.copy2(file,project/file.name)
    shutil.copy2(source,project/'assets/talk.mp4');save(project/'speed.json',speed);save(project/'plan-original.json',plan)
    framing=plan.get('framing',{});fx=float(framing.get('focusX',.5));fy=float(framing.get('focusY',.5))
    if not 0<=fx<=1 or not 0<=fy<=1:raise ValueError('Framing focus must be between 0 and 1')
    vf=f'scale=1080:1920:force_original_aspect_ratio=increase:force_divisible_by=2,setsar=1,crop=1080:1920:(iw-1080)*{fx}:(ih-1920)*{fy},fps=30'
    run(['ffmpeg','-n','-v','error','-ss',start,'-i',source,'-t',length,'-an','-vf',vf,'-q:v','3','-threads','2',project/'assets/frames/%05d.jpg'])
    selected=shifted([c for c in captions if c['end']>start and c['start']<end],start)
    for c in selected:c['start']=max(0,c['start']);c['end']=min(length,c['end'])
    scenes=copy.deepcopy([s for s in plan.get('scenes',[]) if s['end']>start and s['start']<end]);register=[]
    for s in scenes:
        if s['type']=='evidence':
            image=Path(s['image']);image=image if image.is_absolute() else args.plan.resolve().parent/image
            src=s.get('source',{})
            if not src.get('title') or not (src.get('url') or src.get('locator')):raise ValueError('Evidence needs a real source title and URL/locator')
            if image.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('Evidence must be a local raster image')
            identity=sha(image);dest=project/'assets'/('evidence-'+identity[:16]+image.suffix.lower());shutil.copy2(image,dest);s['image']=str(dest.relative_to(project)).replace('\\','/');register.append({**src,'image':s['image'],'sha256':identity})
    scenes=shifted(scenes,start)
    for s in scenes:s['start']=max(0,s['start']);s['end']=min(length,s['end'])
    notes=shifted([n for n in plan.get('notes',[]) if n['end']>start and n['start']<end],start)
    for n in notes:n['start']=max(0,n['start']);n['end']=min(length,n['end'])
    camera={'anchor':plan.get('camera',{}).get('anchor',[600,860]),'keys':[[0,camera_value(keys,start)]]+[[t-start,z] for t,z in keys if start<t<end]+[[length,camera_value(keys,end)]]}
    config={'end':length,'speed':speed['targetSpeed'],'alreadyRetimed':True,'sourceStart':start,'sourceEnd':end,'sourceFps':30,'fps':60,'width':1080,'height':1920,'frameCount':len(list((project/'assets/frames').glob('*.jpg'))),'captions':selected,'camera':camera,'scenes':scenes,'notes':notes}
    if config['frameCount']<1:raise ValueError('No source frames')
    save(project/'film.json',config);(project/'config.js').write_text('window.FILM = '+__import__('json').dumps(config,ensure_ascii=False,indent=2)+';\n',encoding='utf-8')
    save(project/'来源/source-register.json',register)
    save(project/'output-signature.json',{'schema':'adu-output-signature/1','enabled':False})
    text=__import__('json').dumps(config,ensure_ascii=False)+'资料来源个阶段“”→?×0123456789'
    fonts=SKILL/'assets/fonts'
    try:
        from fontTools import subset
        options=subset.Options();font=subset.load_font(str(fonts/'IBMPlexSansSC-SemiBold.otf'),options);sub=subset.Subsetter(options=options);sub.populate(text=text);sub.subset(font)
        # The OFL font reserves the name Plex; modified subsets use our own family.
        names={1:'Netfeel Sans SC',2:'SemiBold',3:'NetfeelSansSC-SemiBold-1',4:'Netfeel Sans SC SemiBold',6:'NetfeelSansSC-SemiBold',16:'Netfeel Sans SC',17:'SemiBold'}
        for record in font['name'].names:
            if record.nameID in names:record.string=names[record.nameID].encode(record.getEncoding(),errors='replace')
        subset.save_font(font,str(project/'assets/fonts/Plex.otf'),options)
    except ImportError:shutil.copy2(fonts/'IBMPlexSansSC-SemiBold.otf',project/'assets/fonts/Plex.otf')
    for name in ['Inter-SemiBold.ttf','OFL-IBM-Plex.txt','OFL-Inter.txt']:shutil.copy2(fonts/name,project/'assets/fonts'/name)
    (project/'字幕.srt').write_text('\n\n'.join(f'{i+1}\n{srt_stamp(c["start"])} --> {srt_stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(selected))+'\n',encoding='utf-8-sig')
    mix(project,source,start,length,plan,args.plan.resolve().parent);make_preview(project)
    (project/'工程说明.txt').write_text('网感口播剪辑可编辑工程\n入口index.html；可拖动预览preview.html。\n编辑config.js中的字幕、场景与镜头；style.css控制版式；scene.js控制动作。film.json为同版数据快照。\n字幕/镜头/字效修改后另存导出；声音变化时按plan-original.json重新构建新工程以同步混音。\nassets/talk.mp4为完整的已倍速粗剪，speed.json记录速度，film.json的sourceStart/End记录本次引用区间；不要重复加速。\n来源与音乐许可分别见来源/source-register.json及mix-recipe.json；有音乐署名时发布需附发布用音乐署名.txt。\n此工程是HTML/JS工程，不是剪映或PR工程。\n',encoding='utf-8')
    save(project/'build.json',{'schema':'netfeel-build/1','sourceRange':[start,end],'targetSpeed':speed['targetSpeed'],'frameCount':config['frameCount'],'sourceSha256':sha(source),'captionsInput':str(args.captions.resolve()),'planInput':str(args.plan.resolve())})
    print(str(project))

if __name__=='__main__':main()
