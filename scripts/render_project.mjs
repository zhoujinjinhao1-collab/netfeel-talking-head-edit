// Original local renderer for this skill. No external video-skill runtime.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawn,spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(path.join(root,'package.json'));
const {chromium}=require('playwright');
const argv=process.argv.slice(2),command=argv.shift(),project=path.resolve(argv.shift()||''),output=path.resolve(argv.shift()||'');
const options={segments:'2',times:''};
for(let i=0;i<argv.length;i+=2){const k=argv[i];if(!['--segments','--times'].includes(k)||argv[i+1]===undefined)throw Error('Invalid option: '+k);options[k.slice(2)]=argv[i+1];}
if(!['video','stills'].includes(command))throw Error('Usage: node render_project.mjs video|stills PROJECT NEW_OUTPUT [--segments 2 | --times 1,3]');
if(fs.existsSync(output))throw Error('Output already exists: '+output);
if(command==='video'&&fs.existsSync(output+'.manifest.json'))throw Error('Output manifest already exists');
if(!fs.existsSync(path.dirname(output)))throw Error('Output parent directory is missing');
const entry=path.join(project,'index.html'),fps=60,width=1080,height=1920;
const config=JSON.parse(fs.readFileSync(path.join(project,'film.json'),'utf8'));
const count=Math.round(Number(config.end)*fps),duration=count/fps;
if(!Number.isFinite(duration)||count<1)throw Error('Invalid project duration');
if(config.width!==width||config.height!==height)throw Error('Adapt the layout before exporting a different aspect ratio');
const segments=Math.min(count,Number(options.segments));
if(!Number.isInteger(segments)||segments<1||segments>8)throw Error('segments must be an integer from 1 to 8');

function run(args){const r=spawnSync(String(args[0]),args.slice(1).map(String),{encoding:'utf8',maxBuffer:64*1024*1024,windowsHide:true});if(r.error)throw r.error;if(r.status!==0)throw Error(r.stderr.slice(-6000));return r.stdout;}
function probe(file,frames=false){return JSON.parse(run(['ffprobe','-v','error',...(frames?['-count_frames']:[]),'-show_streams','-show_format','-of','json',file]));}
function fileHash(file){return createHash('sha256').update(fs.readFileSync(file)).digest('hex');}
function sources(){const result={};function scan(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const f=path.join(dir,e.name);if(e.isDirectory()){if(!['node_modules','__pycache__','.git'].includes(e.name))scan(f);}else result[path.relative(project,f).replaceAll('\\','/')]=fileHash(f);}}scan(project);return result;}
function browserPath(){
 const paths=[process.env.CHROME,process.env.BROWSER_PATH,chromium.executablePath()];
 if(process.platform==='win32')for(const base of [process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA])if(base)paths.push(path.join(base,'Google/Chrome/Application/chrome.exe'),path.join(base,'Microsoft/Edge/Application/msedge.exe'));
 if(process.platform==='darwin')paths.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge');
 if(process.platform==='linux')paths.push('/usr/bin/google-chrome','/usr/bin/chromium','/usr/bin/chromium-browser','/usr/bin/microsoft-edge');
 const found=paths.find(p=>p&&fs.existsSync(p));if(!found)throw Error('No Chromium browser: run npx playwright install chromium, or set CHROME to an installed browser');return found;
}
const before=sources(),temp=fs.mkdtempSync(path.join(os.tmpdir(),'netfeel-render-')),live=new Set();
let browser,cancelled=false,report;
async function pageForJob(){
 const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,colorScheme:'light'});const page=await context.newPage();const errors=[];
 await context.route('**/*',async route=>{const u=route.request().url();if(/^(file:|data:|blob:|about:)/.test(u))await route.continue();else{errors.push('Remote asset blocked: '+u);await route.abort();}});
 if(context.routeWebSocket)await context.routeWebSocket('**/*',socket=>{errors.push('Remote WebSocket blocked');socket.close();});
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('requestfailed',r=>errors.push(r.url()+': '+r.failure()?.errorText));
 await page.goto(pathToFileURL(entry).href,{waitUntil:'load',timeout:60000});
 await page.waitForFunction(()=>typeof window.renderAt==='function'&&!!window.READY,null,{timeout:60000});
 await page.evaluate(async()=>{await window.READY;await document.fonts.ready;});
 if(Math.abs(await page.evaluate(()=>window.END)-config.end)>.0001)throw Error('film.json and runtime END differ; synchronize the project before export');
 async function frame(t){
  if(cancelled)throw Error('Render cancelled after another segment failed');
  if(errors.length)throw Error(errors.join('\n'));
  await page.evaluate(async t=>{
   await window.renderAt(t);await document.fonts.ready;
   if(document.querySelector('video,audio'))throw Error('Use deterministic image frames in index.html; native playback is only for preview.html');
   for(const im of document.images){let visible=true;for(let e=im;e;e=e.parentElement){const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0){visible=false;break;}}
    if(visible&&im.getAttribute('src')){if(im.dataset.decoded!==im.src){await im.decode();im.dataset.decoded=im.src;}if(!im.naturalWidth)throw Error('Broken image: '+im.src);}
   }
  },t);
  if(errors.length)throw Error(errors.join('\n'));
  return await page.screenshot({type:'png',animations:'disabled'});
 }
 return {context,frame};
}
async function encode(first,last,index){
 const {context,frame}=await pageForJob();let encoder,done,diagnostic='',pipeError;
 const target=path.join(temp,`part-${index}.mp4`);
 try{
  const args=['-n','-v','error','-f','image2pipe','-framerate',String(fps),'-c:v','png','-i','pipe:0','-an',
   '-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p','-c:v','libx264','-preset','fast','-crf','16','-threads','2',
   '-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-frames:v',String(last-first),'-video_track_timescale',String(fps),target];
  encoder=spawn('ffmpeg',args,{stdio:['pipe','ignore','pipe'],windowsHide:true});live.add(encoder);
  encoder.stderr.on('data',b=>{diagnostic=(diagnostic+b).slice(-6000);});encoder.stdin.on('error',e=>{pipeError=e;});
  done=new Promise(resolve=>{encoder.once('error',e=>resolve({error:e.message}));encoder.once('close',code=>resolve({code}));});
  for(let i=first;i<last;i++){
   if(pipeError||encoder.exitCode!==null)throw Error(diagnostic||String(pipeError));
   const png=await frame(i/fps);
   await new Promise((resolve,reject)=>encoder.stdin.write(png,e=>e?reject(e):resolve()));
  }
  encoder.stdin.end();const result=await done;if(result.error||result.code!==0)throw Error(result.error||diagnostic||'FFmpeg encoding failed');
  const v=probe(target,true).streams.find(s=>s.codec_type==='video');if(Number(v.nb_read_frames)!==last-first)throw Error('Segment frame count mismatch');
  process.stderr.write(`Segment ${index+1}/${segments}: ${last-first} frames verified\n`);return target;
 }catch(e){cancelled=true;throw e;}finally{if(encoder){if(encoder.exitCode===null){encoder.kill();await done;}live.delete(encoder);}await context.close();}
}
function verify(file){
 const data=probe(file,true),v=data.streams.find(s=>s.codec_type==='video'),a=data.streams.find(s=>s.codec_type==='audio');
 if(!v||!a||Number(v.nb_read_frames)!==count||v.width!==width||v.height!==height||v.avg_frame_rate!=='60/1'||Math.abs(Number(v.duration)-duration)>1/fps||Math.abs(Number(a.duration)-duration)>.05)throw Error('Final MP4 metadata mismatch');
 const frames=JSON.parse(run(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',file])).frames;
 if(frames.length!==count||frames.some((f,i)=>Math.abs(Number(f.best_effort_timestamp_time)-i/fps)>.000002))throw Error('Final display-frame clock mismatch');
 run(['ffmpeg','-v','error','-i',file,'-f','null','-']);return {frames:count,fps,width,height,duration,audio:true,completeDecode:true,frameClock:true};
}
try{
 const executablePath=browserPath();browser=await chromium.launch({executablePath,headless:true,args:['--allow-file-access-from-files','--force-color-profile=srgb','--disable-gpu']});
 if(command==='stills'){
  const times=options.times.split(',').map(Number);if(!options.times||times.some(t=>!Number.isFinite(t)||t<0||t>=config.end))throw Error('Provide still times within the project');
  const {context,frame}=await pageForJob();
  try{for(let i=0;i<times.length;i++)fs.writeFileSync(path.join(temp,`frame-${String(i).padStart(3,'0')}-${times[i].toFixed(3)}s.png`),await frame(times[i]));}finally{await context.close();}
  if(JSON.stringify(sources())!==JSON.stringify(before))throw Error('Project changed during rendering');
  fs.mkdirSync(output);for(const f of fs.readdirSync(temp))fs.copyFileSync(path.join(temp,f),path.join(output,f),fs.constants.COPYFILE_EXCL);
  report={output,times};
 }else{
  const audio=path.join(project,'mix.wav'),a=probe(audio).streams.find(s=>s.codec_type==='audio');
  if(!a||Number(a.duration)+.05<duration)throw Error('Mix does not cover the whole output');
  const jobs=Array.from({length:segments},(_,i)=>encode(Math.round(count*i/segments),Math.round(count*(i+1)/segments),i));
  const results=await Promise.allSettled(jobs);const failed=results.find(r=>r.status==='rejected');if(failed)throw failed.reason;
  const list=path.join(temp,'concat.txt');fs.writeFileSync(list,results.map(r=>"file '"+r.value.replaceAll('\\','/').replaceAll("'","'\\''")+"'").join('\n')+'\n');
  const silent=path.join(temp,'joined.mp4'),final=path.join(temp,'final.mp4');
  run(['ffmpeg','-n','-v','error','-f','concat','-safe','0','-i',list,'-map','0:v:0','-c:v','copy','-video_track_timescale',fps,silent]);
  run(['ffmpeg','-n','-v','error','-i',silent,'-i',audio,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-af','apad','-t',duration,'-video_track_timescale',fps,'-movflags','+faststart',final]);
  const checked=verify(final);if(JSON.stringify(sources())!==JSON.stringify(before))throw Error('Project changed during rendering');
  fs.copyFileSync(final,output,fs.constants.COPYFILE_EXCL);
  const manifest={schema:'netfeel-export/1',renderer:'standalone-1.1.0',...checked,sources:before,outputSha256:fileHash(output)};
  fs.writeFileSync(output+'.manifest.json',JSON.stringify(manifest,null,2),'utf8');report={output,...checked};
 }
}finally{
 for(const e of live)e.kill();
 if(browser){let timer;await Promise.race([browser.close(),new Promise(resolve=>{timer=setTimeout(resolve,10000);})]);clearTimeout(timer);}
 const relative=path.relative(path.resolve(os.tmpdir()),path.resolve(temp));
 if(relative.startsWith('..')||path.isAbsolute(relative)||!path.basename(temp).startsWith('netfeel-render-'))throw Error('Unexpected temporary path; refusing cleanup');
 fs.rmSync(temp,{recursive:true,force:true});
}
await new Promise(resolve=>process.stdout.write(JSON.stringify(report)+'\n',resolve));
// Chromium helpers on Windows can retain inherited pipes after browser.close().
// This is a CLI, and all verification and cleanup above have been awaited.
process.exit(0);
