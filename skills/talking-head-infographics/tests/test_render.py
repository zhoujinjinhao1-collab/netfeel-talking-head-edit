"""Tests use a synthetic video, never a user's footage."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render.py"
spec = importlib.util.spec_from_file_location("infographic_render", SCRIPT)
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


def plan():
    return {
        "title": "Test", "duration": 3, "fps": 10, "width": 360,
        "clips": [{"start": 0, "end": 1}, {"start": 2, "end": 3}],
        "captions": [{"start": 0, "end": .8, "text": "Keep the meaning", "highlight": "meaning"}],
        "scenes": [{"start": 0, "end": 3, "background": "paper",
                    "portrait": {"box": [450, 805, 214, 302]},
                    "elements": [{"type": "text", "x": 50, "y": 190,
                                  "text": "One clear point", "size": 36}]}],
    }


class TimelineTests(unittest.TestCase):
    def test_cut_clock_and_complete_duration(self):
        p = plan()
        self.assertEqual(render.validate(p, 3), 2)
        self.assertAlmostEqual(render.source_time(p, 1.2), 2.2)
        p["duration"], p["scenes"][0]["end"] = 1.8, 1.8
        with self.assertRaisesRegex(ValueError, "exceeds"):
            render.validate(p, 3)

    def test_rejects_scene_gaps_and_wrong_highlight(self):
        p = plan()
        p["scenes"][0]["start"] = .2
        with self.assertRaisesRegex(ValueError, "continuously"):
            render.validate(p, 3)
        p = plan()
        p["captions"][0]["highlight"] = "not in the speech"
        with self.assertRaisesRegex(ValueError, "highlight"):
            render.validate(p, 3)

    def test_no_long_padding_or_out_of_source_cuts(self):
        p = plan()
        p["duration"], p["scenes"][0]["end"] = 5, 5
        with self.assertRaisesRegex(ValueError, "tail"):
            render.validate(p, 3)
        with self.assertRaisesRegex(ValueError, "outside media"):
            render.validate(plan(), 2.5)


@unittest.skipUnless(os.environ.get("TEST_FONT_DIR"), "Set TEST_FONT_DIR to verified Source Han fonts")
class RenderTests(unittest.TestCase):
    def fonts(self, p):
        directory = Path(os.environ["TEST_FONT_DIR"]).resolve()
        p["fonts"] = {
            "display": str(directory / "SourceHanSerifSC-Heavy.otf"),
            "body": str(directory / "SourceHanSansSC-Medium.otf"),
        }
        return p

    def test_example_layout_and_boundaries_fit(self):
        from PIL import Image
        path = SCRIPT.parents[1] / "assets" / "example.plan.json"
        p = self.fonts(json.loads(path.read_text(encoding="utf-8")))
        render.validate(p, 25)
        composer = render.Composer(p, path.parent)
        raw = Image.new("RGB", (720, 1280), "#647067")
        for scene in p["scenes"]:
            for t in [scene["start"]+.03, (scene["start"]+scene["end"])/2, scene["end"]-.01]:
                composer.frame(raw, t)

    def test_graphic_cannot_hide_behind_portrait_or_subtitles(self):
        from PIL import Image
        p = self.fonts(plan())
        composer = render.Composer(p, Path.cwd())
        image = Image.new("RGB", (720, 1280))
        p["scenes"][0]["elements"][0].update(x=460, y=840, text="Hidden")
        with self.assertRaisesRegex(ValueError, "portrait"):
            composer.frame(image, .7)
        p["scenes"][0]["elements"][0].update(x=50, y=1140)
        with self.assertRaisesRegex(ValueError, "subtitle"):
            composer.frame(image, .7)

    def test_real_export_unicode_paths_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="infographic-test-") as temp:
            root = Path(temp)
            source, output = root/"测试 input.mp4", root/"result"
            render.run([render.ffmpeg(), "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=10:duration=3",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(source)])
            original_hash = render.file_hash(source)
            for clips in [[{"start": 0, "end": 1}, {"start": 2, "end": 3}],
                          [{"start": .2, "end": 2.7}]]:
                p = self.fonts(plan())
                p["clips"] = clips
                output = root/("single" if len(clips) == 1 else "result")
                plan_path = root/"plan.json"
                plan_path.write_text(json.dumps(p), encoding="utf-8")
                render.run([os.sys.executable, str(SCRIPT), "video", "--input", str(source),
                            "--plan", str(plan_path), "--output", str(output)])
                report = json.loads((output/"report.json").read_text(encoding="utf-8"))
                self.assertTrue(report["decode_ok"])
                self.assertEqual(report["decoded_frames"], 30)
                self.assertEqual(report["duration"], 3)
                self.assertEqual(report["input_sha256"], original_hash)
                self.assertEqual(render.file_hash(source), original_hash)
                with self.assertRaises(RuntimeError):
                    render.run([os.sys.executable, str(SCRIPT), "video", "--input", str(source),
                                "--plan", str(plan_path), "--output", str(output)])


if __name__ == "__main__":
    unittest.main()
