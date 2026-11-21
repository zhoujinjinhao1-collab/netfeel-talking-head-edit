"""Public distribution checks using synthetic fixtures, never private recordings."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
def run(*args,success=True):
    r=subprocess.run([str(x) for x in args],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if success and r.returncode:raise AssertionError(r.stderr[-5000:])
    return r
def script(name,*args,**kwargs):return run(sys.executable,'-X','utf8',ROOT/'scripts'/name,*args,**kwargs)

class Workflow(unittest.TestCase):
    def test_clock_and_guards(self):
        with tempfile.TemporaryDirectory(prefix='netfeel-test-') as directory:
            p=Path(directory);source=p/'fixture.mp4'
            run('ffmpeg','-n','-v','error','-f','lavfi','-i','color=c=teal:s=108x192:r=30:d=2.2','-f','lavfi','-i','sine=frequency=997:sample_rate=48000:duration=2.2','-c:v','libx264','-threads','2','-c:a','aac',source)
            script('prepare_talk.py',source,p/'prepared','--input-speed','1')
            record=json.loads((p/'prepared/speed.json').read_text(encoding='utf-8'))
            self.assertEqual(record['targetSpeed'],1.1);self.assertAlmostEqual(record['duration'],2,places=2)
            wrong=script('prepare_talk.py',p/'prepared/talk.mp4',p/'wrong','--input-speed','1',success=False)
            self.assertNotEqual(wrong.returncode,0);self.assertFalse((p/'wrong').exists())
            script('prepare_talk.py',p/'prepared/talk.mp4',p/'reused','--input-speed','1.1')
            reused=json.loads((p/'reused/speed.json').read_text(encoding='utf-8'))
            self.assertEqual(reused['appliedMultiplier'],1)
            self.assertEqual(reused['currentSha256'],record['currentSha256'])
            captions=[{'start':0,'end':.8,'text':'测试字幕','highlights':['字幕']}]
            plan={'targetSpeed':1.1,'camera':{'anchor':[540,860],'keys':[[0,1.02],[.2,1.02],[.35,1.2],[.8,1.2]]},'scenes':[{'type':'impact','start':0,'end':.8,'word':'测试','kicker':'独立渲染验证','at':.2}], 'audio':{'music':{'mode':'none','reason':'Synthetic workflow test'},'sfx':[{'time':.2,'name':'tick','gain':.04}]}}
            for name,data in [('captions.json',captions),('plan.json',plan)]:
                (p/name).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            base=['--prepared',p/'prepared','--captions',p/'captions.json','--plan',p/'plan.json']
            cut=script('build_project.py',*base,'--dest',p/'cut','--end','.5',success=False)
            self.assertNotEqual(cut.returncode,0);self.assertFalse((p/'cut').exists())
            script('build_project.py',*base,'--dest',p/'project','--end','.8')
            if os.environ.get('NETFEEL_RENDER_TEST')=='1':
                script('render.py','video',p/'project',p/'smoke.mp4','--segments','2')
                data=json.loads(script('render.py','check',p/'smoke.mp4').stdout)
                self.assertEqual(data['video']['nb_frames'],'48')
                self.assertEqual(data['video']['avg_frame_rate'],'60/1')
                self.assertAlmostEqual(float(data['audio']['duration']),.8,places=2)
                self.assertTrue(data['completeDecode'])
                manifest=json.loads((p/'smoke.mp4.manifest.json').read_text(encoding='utf-8'))
                self.assertTrue(manifest['frameClock'])

if __name__=='__main__':unittest.main()
