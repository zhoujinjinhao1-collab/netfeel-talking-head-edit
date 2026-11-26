"""Render local talking-head infographic plans. Coordinates use a 720x1280 grid."""
import argparse
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageFilter

DEFAULT_STYLE = {
    "paper": "#f6f2e9", "ink": "#202b2a", "muted": "#83877f",
    "accent": "#235d50", "negative": "#ac4e49", "gold": "#e3ba67",
}


def ffmpeg():
    configured = os.environ.get("FFMPEG")
    if configured:
        return configured
    system = shutil.which("ffmpeg")
    if system:
        return system
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:])
    return result


def probe(source):
    result = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(source)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = result.stderr
    match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", log)
    if not match:
        raise ValueError("Cannot read media duration: " + log[-1500:])
    h, m, s = map(float, match.groups())
    return {"duration": h*3600+m*60+s, "audio": bool(re.search(r"Stream .*Audio:", log)),
            "metadata": log[:log.find("At least one output")]}


def validate(plan, source_duration=None):
    duration, fps, width = float(plan["duration"]), int(plan.get("fps", 30)), int(plan.get("width", 1080))
    if not math.isfinite(duration) or duration <= 0 or not 1 <= fps <= 60:
        raise ValueError("Invalid duration or fps")
    if width < 180 or width % 2 or (width*16/9) % 2:
        raise ValueError("Width must produce even 9:16 dimensions, e.g. 360, 720 or 1080")
    if abs(duration*fps-round(duration*fps)) > 1e-6:
        raise ValueError("duration * fps must be a whole frame count")
    clips = plan["clips"]
    if not clips:
        raise ValueError("At least one source clip is required")
    previous_end, total = -1, 0
    for clip in clips:
        a, b = float(clip["start"]), float(clip["end"])
        if not all(map(math.isfinite, [a, b])) or a < previous_end or b-a < 1/fps:
            raise ValueError("Source clips must be ordered, nonoverlapping and at least one frame")
        if a < 0 or source_duration is not None and b > source_duration + .01:
            raise ValueError("Source clip outside media duration")
        previous_end, total = b, total+b-a
    if total > duration+1e-6:
        raise ValueError("Clip duration exceeds output; choose complete speech boundaries instead")
    if duration-total > 1.5 and not plan.get("allow_long_hold", False):
        raise ValueError("More than 1.5 seconds of tail hold; do not pad a short excerpt")
    end = 0
    for scene in plan["scenes"]:
        a, b = float(scene["start"]), float(scene["end"])
        if abs(a-end) > 1e-6 or b <= a:
            raise ValueError("Scenes must continuously cover the output timeline")
        end = b
        if scene.get("background", "paper") not in ("paper", "video"):
            raise ValueError("background must be paper or video")
        for element in scene.get("elements", []):
            if element["type"] not in ("text", "rect", "line", "arrow", "image"):
                raise ValueError("Unknown graphic element")
            if float(element.get("enter", .35)) < 0:
                raise ValueError("enter must be nonnegative")
    if abs(end-duration) > 1e-6:
        raise ValueError("Scenes must end at duration")
    end = 0
    for caption in plan.get("captions", []):
        a, b = float(caption["start"]), float(caption["end"])
        if a < end-1e-6 or not 0 <= a < b <= duration or not caption["text"]:
            raise ValueError("Captions must be ordered, nonoverlapping and inside the output")
        if caption.get("highlight") and caption["highlight"] not in caption["text"]:
            raise ValueError("Caption highlight must occur in its text")
        end = b
    return total


def cover(image, width, height):
    scale = max(width/image.width, height/image.height)
    image = image.resize((math.ceil(image.width*scale), math.ceil(image.height*scale)), Image.Resampling.LANCZOS)
    x, y = (image.width-width)//2, (image.height-height)//2
    return image.crop((x, y, x+width, y+height))


def intersects(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


class Composer:
    def __init__(self, plan, base):
        self.plan, self.base = plan, Path(base)
        self.width = int(plan.get("width", 1080))
        self.height, self.scale = self.width*16//9, self.width/720
        self.style = dict(DEFAULT_STYLE, **plan.get("style", {}))
        self.font_paths = {k: self.local(v) for k, v in plan["fonts"].items()}
        for family in ("display", "body"):
            if not self.font_paths[family].is_file():
                raise ValueError(f"Missing {family} font; run fetch_fonts.py or set a local font")
        self.paper = Image.new("RGBA", (self.width, self.height), self.style["paper"])

    def local(self, path):
        if "://" in str(path):
            raise ValueError("Rendering accepts local assets only")
        return (self.base / path).resolve()

    def q(self, value):
        return round(value*self.scale)

    def color(self, value):
        return self.style[value[1:]] if isinstance(value, str) and value.startswith("$") else value

    @lru_cache(maxsize=100)
    def font(self, size, family):
        return ImageFont.truetype(str(self.font_paths[family]), self.q(size))

    @lru_cache(maxsize=400)
    def glyph(self, value, size, family, color):
        font = self.font(size, family)
        box = font.getbbox(value)
        layer = Image.new("RGBA", (box[2]-box[0]+8, box[3]-box[1]+8))
        ImageDraw.Draw(layer).text((4-box[0], 4-box[1]), value, font=font, fill=color)
        return layer

    def text(self, image, x, y, value, size=24, family="body", color="$ink",
             opacity=1, align="left", scene=None, allow_overlap=False):
        layer = self.glyph(value, size, family, self.color(color)).copy()
        px, py = self.q(x), self.q(y)
        visible_width, visible_height = layer.width-8, layer.height-8
        if align == "center":
            px -= visible_width//2
        elif align == "right":
            px -= visible_width
        bounds = [px, py, px+visible_width, py+visible_height]
        if min(px, py) < 0 or bounds[2] > self.width or bounds[3] > self.height:
            raise ValueError(f"Text outside canvas: {value}")
        if scene and not allow_overlap:
            if bounds[3] > self.q(1110):
                raise ValueError(f"Graphic enters subtitle zone: {value}")
            portrait = scene.get("portrait")
            if portrait and scene.get("background", "paper") == "paper":
                x1, y1, w, h = portrait["box"]
                if intersects(bounds, list(map(self.q, [x1, y1, x1+w, y1+h]))):
                    raise ValueError(f"Graphic hidden by portrait: {value}")
        if opacity < 1:
            layer.putalpha(layer.getchannel("A").point(lambda a: round(a*opacity)))
        image.alpha_composite(layer, (px-4, py-4))

    def rect(self, image, box, fill, radius=8, outline=None, stroke=1):
        ImageDraw.Draw(image).rounded_rectangle(tuple(map(self.q, box)), self.q(radius),
            fill=self.color(fill), outline=self.color(outline), width=max(1, self.q(stroke)))

    def portrait(self, image, raw, config):
        x, y, w, h = config["box"]
        crop = config.get("crop", [0, .10, 1, .97])
        if not 0 <= crop[0] < crop[2] <= 1 or not 0 <= crop[1] < crop[3] <= 1:
            raise ValueError("portrait crop must contain normalized left, top, right, bottom")
        if x < 0 or y < 0 or x+w > 720 or y+h > 1110:
            raise ValueError("Portrait must fit above the subtitle zone")
        src = raw.crop((round(crop[0]*raw.width), round(crop[1]*raw.height),
                        round(crop[2]*raw.width), round(crop[3]*raw.height)))
        view = cover(src, self.q(w), self.q(h)).convert("RGBA")
        mask = Image.new("L", view.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, view.width-1, view.height-1), self.q(8), fill=255)
        view.putalpha(mask)
        self.rect(image, [x-2, y-2, x+w+2, y+h+2], "#e9e3d7", 10)
        image.alpha_composite(view, (self.q(x), self.q(y)))

    def frame(self, raw, t):
        scene = next(s for s in self.plan["scenes"] if s["start"] <= t < s["end"])
        video = scene.get("background", "paper") == "video"
        image = cover(raw, self.width, self.height).convert("RGBA") if video else self.paper.copy()
        if video:
            shade = Image.new("RGBA", (1, self.height))
            d = ImageDraw.Draw(shade)
            for y in range(self.height):
                d.point((0, y), fill=(10, 16, 14, int(min(190, max(0, (y/self.height-.48)*450)))))
            image.alpha_composite(shade.resize(image.size))
        self.rect(image, [48, 51, 220, 90], "$negative", 2)
        self.text(image, 60, 58, self.plan.get("title", "口播图解"), 20, color="#f6f1e7")
        self.text(image, 672, 61, scene.get("section", ""), 16,
                  color="#f6f1e7" if video else "$ink", align="right")
        for element in scene.get("elements", []):
            at = float(element.get("at", scene["start"]))
            if t < at or t >= float(element.get("until", scene["end"])):
                continue
            duration = float(element.get("enter", .35))
            linear = min(1, (t-at)/duration) if duration else 1
            p = 1-(1-linear)**3
            layer = Image.new("RGBA", image.size)
            kind = element["type"]
            if kind == "text":
                self.text(layer, element["x"], element["y"]+element.get("move_y", 12)*(1-p),
                    element["text"], element.get("size", 40), element.get("family", "body"),
                    element.get("color", "$ink"), p, element.get("align", "left"), scene,
                    element.get("allow_overlap", False))
            elif kind == "rect":
                self.rect(layer, element["box"], element.get("fill", "$paper"),
                    element.get("radius", 8), element.get("outline"), element.get("stroke", 1))
                layer.putalpha(layer.getchannel("A").point(lambda a: round(a*p)))
            elif kind in ("line", "arrow"):
                start, end = element["points"]
                point = [start[0]+(end[0]-start[0])*p, start[1]+(end[1]-start[1])*p]
                d = ImageDraw.Draw(layer)
                color, width = self.color(element.get("color", "$accent")), max(1, self.q(element.get("stroke", 3)))
                points = [tuple(map(self.q, start)), tuple(map(self.q, point))]
                d.line(points, fill=color, width=width)
                if kind == "arrow" and p > .8:
                    angle = math.atan2(end[1]-start[1], end[0]-start[0])
                    a = [point[0]-16*math.cos(angle-.55), point[1]-16*math.sin(angle-.55)]
                    b = [point[0]-16*math.cos(angle+.55), point[1]-16*math.sin(angle+.55)]
                    d.line([tuple(map(self.q, a)), points[1], tuple(map(self.q, b))], fill=color, width=width)
            elif kind == "image":
                x, y, w, h = element["box"]
                with Image.open(self.local(element["path"])) as asset:
                    asset = cover(asset, self.q(w), self.q(h)).convert("RGBA")
                    asset.putalpha(asset.getchannel("A").point(lambda a: round(a*p)))
                    layer.alpha_composite(asset, (self.q(x), self.q(y)))
            image.alpha_composite(layer)
        if scene.get("portrait"):
            self.portrait(image, raw, scene["portrait"])
        caption = next((c for c in self.plan.get("captions", []) if c["start"] <= t < c["end"]), None)
        if caption:
            value, size = caption["text"], 27
            length = self.font(size, "body").getlength(value)/self.scale
            if length > 624:
                raise ValueError("Caption too long: split it at a speech boundary")
            x = (720-length)/2
            if video:
                shadow = Image.new("RGBA", image.size)
                self.text(shadow, x, 1142, value, size, color="#000000")
                image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(self.q(3))))
            self.text(image, x, 1138, value, size, color="#fffdf7" if video else "$ink")
            key = caption.get("highlight")
            if key:
                px = x+self.font(size, "body").getlength(value.split(key)[0])/self.scale
                self.text(image, px, 1138, key, size, color="$gold" if video else "$accent")
        d = ImageDraw.Draw(image)
        d.line([(self.q(48), self.q(1219)), (self.q(672), self.q(1219))], fill="#bfc1b5")
        d.line([(self.q(48), self.q(1219)), (self.q(48+624*t/self.plan["duration"]), self.q(1219))],
               fill=self.style["gold" if video else "accent"], width=max(1, self.q(2)))
        return image.convert("RGB")


def source_time(plan, t):
    cursor = 0
    for clip in plan["clips"]:
        length = clip["end"]-clip["start"]
        if t < cursor+length:
            return clip["start"]+t-cursor
        cursor += length
    return plan["clips"][-1]["end"]-.04


def still(source, time):
    data = subprocess.check_output([ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", str(time),
        "-i", str(source), "-frames:v", "1", "-vf",
        "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    return Image.frombytes("RGB", (720, 1280), data)


def preview(source, plan, composer, output, times=None):
    if times is None:
        times = [s["start"]+min(.18, (s["end"]-s["start"])/3) for s in plan["scenes"]]
        times += [(s["start"]+s["end"])/2 for s in plan["scenes"]]
        times = sorted(set(times))
    board = Image.new("RGB", (4*240, math.ceil(len(times)/4)*455), "#26342e")
    d = ImageDraw.Draw(board)
    for i, t in enumerate(times):
        if not 0 <= t < plan["duration"]:
            raise ValueError("Preview time outside output")
        frame = composer.frame(still(source, source_time(plan, t)), t)
        frame.save(output/f"frame-{t:07.3f}.jpg", quality=92)
        x, y = i%4*240, i//4*455
        board.paste(frame.resize((240, 427), Image.Resampling.LANCZOS), (x, y))
        d.text((x+8, y+433), f"{t:.2f}s", fill="white")
    board.save(output/"contact.jpg", quality=94)


def media_filter(plan, stream):
    clips, kind = plan["clips"], "v" if stream == "video" else "a"
    parts = []
    if len(clips) > 1:
        parts.append(f"[0:{kind}]{'split' if kind == 'v' else 'asplit'}={len(clips)}"+
                     "".join(f"[s{i}]" for i in range(len(clips))))
    for i, clip in enumerate(clips):
        src = f"s{i}" if len(clips) > 1 else f"0:{kind}"
        parts.append(f"[{src}]{'trim' if kind == 'v' else 'atrim'}=start={clip['start']}:end={clip['end']},"+
                     f"{'setpts' if kind == 'v' else 'asetpts'}=PTS-STARTPTS[p{i}]")
    joined = "".join(f"[p{i}]" for i in range(len(clips)))
    parts.append(joined+f"concat=n={len(clips)}:v={int(kind == 'v')}:a={int(kind == 'a')}[joined]")
    if kind == "v":
        parts.append(f"[joined]fps={plan.get('fps',30)},scale=720:1280:"+
                     "force_original_aspect_ratio=increase,crop=720:1280[result]")
    else:
        speech = sum(c["end"]-c["start"] for c in clips)
        parts.append("[joined]highpass=f=75,loudnorm=I=-16:TP=-1.5:LRA=9,"+
                     f"afade=t=in:d=0.015,afade=t=out:st={max(0,speech-.03)}:d=0.03,"+
                     f"apad=pad_dur={max(0,plan['duration']-speech)}[result]")
    return ";".join(parts)


def check(source):
    info = probe(source)
    args = [ffmpeg(), "-hide_banner", "-i", str(source)]
    if info["audio"]:
        args += ["-af", "ebur128=peak=true"]
    result = run(args+["-f", "null", "-"])
    frames = re.findall(r"frame=\s*(\d+)", result.stderr)
    return {"duration": info["duration"], "audio": info["audio"], "decode_ok": True,
            "decoded_frames": int(frames[-1]) if frames else None,
            "audio_measurement": result.stderr[result.stderr.rfind("Summary:"):] if info["audio"] else "",
            "metadata": info["metadata"], "realtime_listening": False}


def srt_time(t):
    ms = round(t*1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export(source, plan, composer, output, info):
    if not info["audio"]:
        raise ValueError("Original speech audio is required for video export")
    fps = int(plan.get("fps", 30))
    count = round(plan["duration"]*fps)
    speech_count = round(sum(c["end"]-c["start"] for c in plan["clips"])*fps)
    visual = output/"visual.mp4"
    with (output/"decoder.log").open("w", encoding="utf-8") as dl, (output/"encoder.log").open("w", encoding="utf-8") as el:
        decoder = subprocess.Popen([ffmpeg(), "-hide_banner", "-loglevel", "error", "-threads", "2",
            "-i", str(source), "-filter_complex", media_filter(plan, "video"), "-map", "[result]",
            "-frames:v", str(speech_count), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            stdout=subprocess.PIPE, stderr=dl)
        encoder = subprocess.Popen([ffmpeg(), "-hide_banner", "-loglevel", "warning", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{composer.width}x{composer.height}", "-r", str(fps),
            "-i", "pipe:0", "-an", "-c:v", "libx264", "-threads", "2", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(visual)], stdin=subprocess.PIPE, stderr=el)
        raw, decoded = None, 0
        try:
            for i in range(count):
                if i < speech_count:
                    data = decoder.stdout.read(720*1280*3)
                    if len(data) == 720*1280*3:
                        raw = Image.frombytes("RGB", (720, 1280), data)
                        decoded += 1
                    elif i < speech_count-1:
                        raise RuntimeError("Source decoder ended before the planned speech")
                if raw is None:
                    raise RuntimeError("No source frame decoded")
                encoder.stdin.write(composer.frame(raw, i/fps).tobytes())
                if i % (fps*5) == 0:
                    print(f"Rendered {i}/{count}", flush=True)
            encoder.stdin.close()
            decoder.stdout.close()
            if encoder.wait() or decoder.wait():
                raise RuntimeError("Encoder/decoder failed; inspect logs in output directory")
        finally:
            for process in (encoder, decoder):
                if process.poll() is None:
                    process.kill()
                    process.wait()
    target = output/"video.mp4"
    audio_filter = media_filter(plan, "audio").replace("[0:a]", "[1:a]")
    run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(visual), "-i", str(source),
        "-filter_complex", audio_filter, "-map", "0:v:0", "-map", "[result]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", str(plan["duration"]), "-movflags", "+faststart", str(target)])
    result = check(target)
    if abs(result["duration"]-plan["duration"]) > 1/fps or result["decoded_frames"] != count:
        raise RuntimeError("Final duration/frame count disagrees with plan")
    result["input_sha256"] = file_hash(source)
    result["planned_frames"] = count
    result["decoded_source_frames"] = decoded
    (output/"report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    captions = [f"{i+1}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n"
                for i, c in enumerate(plan.get("captions", []))]
    (output/"captions.srt").write_text("\n".join(captions), encoding="utf-8-sig")
    saved = json.loads(json.dumps(plan))
    saved["fonts"] = {k: str(v) for k, v in composer.font_paths.items()}
    for scene in saved["scenes"]:
        for e in scene.get("elements", []):
            if e["type"] == "image":
                e["path"] = str(composer.local(e["path"]))
    (output/"plan.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target, flush=True)


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024*1024), b""):
            h.update(data)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("video", type=Path)
    for mode in ("preview", "video"):
        p = sub.add_parser(mode)
        p.add_argument("--input", required=True, type=Path)
        p.add_argument("--plan", required=True, type=Path)
        p.add_argument("--output", required=True, type=Path)
        if mode == "preview":
            p.add_argument("--times", help="Comma-separated output timestamps")
    args = parser.parse_args()
    if args.command == "check":
        print(json.dumps(check(args.video), ensure_ascii=False, indent=2))
        return
    source = args.input.resolve()
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    info = probe(source)
    validate(plan, info["duration"])
    if args.command == "video" and plan.get("example_only", False):
        raise ValueError("Example text is not a transcript: adapt it to actual speech and remove example_only")
    composer = Composer(plan, args.plan.resolve().parent)
    args.output.mkdir(parents=True, exist_ok=False)
    if args.command == "preview":
        times = [float(v) for v in args.times.split(",")] if args.times else None
        preview(source, plan, composer, args.output, times)
    else:
        export(source, plan, composer, args.output, info)


if __name__ == "__main__":
    main()
