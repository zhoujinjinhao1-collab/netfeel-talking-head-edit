from pathlib import Path
import hashlib,json,os,shutil,subprocess

SKILL=Path(__file__).resolve().parent.parent

def setup_path():
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as k:
                extra=winreg.QueryValueEx(k,'Path')[0]
            os.environ['PATH']+=os.pathsep+os.path.expandvars(extra)
        except OSError:
            pass
    os.environ.setdefault('PYTHONIOENCODING','utf-8')

def run(args,raw=False):
    p=subprocess.run([str(x) for x in args],capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8','replace')[-6000:])
    return p.stdout if raw else p.stdout.decode('utf-8','replace')

def probe(path):
    return json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',path]))

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def save(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def need_tools(*names):
    missing=[n for n in names if not shutil.which(n)]
    if missing:raise RuntimeError('Missing tools: '+', '.join(missing))

def new_dir(path):
    path=Path(path).resolve()
    path.mkdir(parents=True,exist_ok=False)
    return path
