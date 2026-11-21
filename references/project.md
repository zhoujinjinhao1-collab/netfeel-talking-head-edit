# 工程输入与命令

脚本在本技能目录内。先确认FFmpeg/ffprobe、Python、NumPy、fontTools、Node、Playwright，以及Chrome/Edge或Playwright Chromium。渲染器随包提供，不依赖adu-motion-video。可复用已有Python环境；不要把某台机器的视频路径或虚拟环境写成通用依赖。只有字体子集化缺fontTools时可复制完整字体，NumPy用于音频混合。

## 1. 倍速底片

输入应为已完成逐句粗剪的视频。正常速度粗剪：

```text
python scripts/prepare_talk.py 已粗剪.mp4 新建底片目录 --input-speed 1
```

默认目标为1.1倍。已确认1.1倍的底片使用 `--input-speed 1.1`，文件直接复制且记录“不再次加速”。已做1.2倍的旧底片使用 `--input-speed 1.2`，仅应用1.1/1.2；不能当成原速再乘1.1。本次另定速度可用 `--target-speed`。
输出 `talk.mp4`、`speed.json`。记录文件摘要、原始速度、目标速度、处理倍率和时长。不要凭语感猜速度；检查原项目或询问确实缺失的信息。对已登记的输入，错误的速度声明会被拒绝。

随后对**生成的talk.mp4**转写/校对。字幕、plan中的时间都是该完整底片的秒数。

## 2. 字幕与分镜

字幕可为SRT或JSON数组：

```json
[{"start":0.0,"end":1.5,"text":"原声实际说出的句子","highlights":["重点词"]}]
```

写一份本期plan JSON。这里只列形状，时间、文字和素材由新口播决定：

```json
{
  "targetSpeed":1.1,
  "framing":{"focusX":0.5,"focusY":0.5},
  "camera":{"anchor":[600,860],"keys":[[0,1.02],[3.5,1.02],[3.7,1.23],[4.3,1.23],[4.55,1.02]]},
  "scenes":[
    {"type":"question","start":0,"end":2.3,"line1":"问题主体","line2":"核心概念","line2At":0.8,"prompt":"必须二选一？","promptAt":0.6},
    {"type":"impact","start":2.56,"end":4.18,"kicker":"先纠正一个","word":"误解","at":3.56,"symbol":"×"},
    {"type":"keywords","start":10.5,"end":14.5,"kicker":"来港渠道","items":[{"text":"高才","at":11.64},{"text":"优才","at":12.32},{"text":"进修","at":12.78}]}
  ],
  "notes":[],
  "audio":{"music":{"mode":"none","reason":"本期只用原声和轻音效"},"sfx":[{"time":3.56,"name":"impact","gain":0.075}]}
}
```

`framing.focusX/Y` 为0–1的裁切位置（0左/上，1右/下），要根据抽帧决定。`camera.anchor` 是裁切后1080×1920的人物头肩锚点。`keys` 为 `[秒,缩放]`，时间严格递增。

`scenes` 支持以下类型；共同字段为type/start/end/kicker，`at`默认为start。内容均按纯文本处理，不接受任意HTML。

| type | 内容字段 |
| --- | --- |
| question | line1, line2, line2At, prompt, promptAt |
| impact | word, at, symbol（可省） |
| quote | text, at |
| underline | text, highlight（文字中的重点片段）, at |
| stages | count, items:[text,…], at；最多3项，较多时换排 |
| keywords | items:[{text,at},…]；同屏最多3项，更多内容拆段 |
| identity | number, text, highlight, band:true/false, caption, at |
| items | items:[{text,at},…]；同屏最多3项 |
| pivot | text, at, arrow（可省） |
| evidence | image（本地文件）, title, number（可省）, unit, condition, highlight, qualifier, source:{title,url或locator,retrieved,label} |

note为 `{start,end,text}`。evidence的数字/条件不是自动推导，必须先核实。图片复制入本期工程，原始来源写入 `来源/source-register.json`。

有配乐时使用 `audio.music:{mode:"track",path:"本期授权曲目",offset:0,source:"来源URL或本地授权说明",attribution:"发布署名"}`。曲目长度必须覆盖所用时间，offset不能为负；不自动循环。SFX支持tick/click/pop/swish/impact，gain通常0.04–0.075，最终需检查人声清晰度。

## 3. 组装

```text
python scripts/build_project.py --prepared 新建底片目录 --captions 字幕.json --plan 本期plan.json --dest 新建工程目录
```

样片可加 `--start S --end E`（完整倍速底片中的时间）；脚本重排所选区间的字幕、场景、相机与音效，配乐沿用整片偏移。选完整句的起止，脚本拒绝在字幕中间切样片。

输出本地画面模板、帧序列、底片、字幕、字体、mix.wav、分轨、plan、来源与速度记录，以及可拖动的preview.html。模板为起点；复杂的新分镜可直接编辑源码，保持window.renderAt(t)/READY确定性接口。

## 4. 静帧、导出、检查

```text
python scripts/render.py stills 工程目录 新建静帧目录 --times 1,3.7,17.2
python scripts/render.py video 工程目录 新成片.mp4 --segments 2
python scripts/render.py check 新成片.mp4
```

输出和截图目录均不得已存在。脚本使用随包的独立渲染器，默认1080×1920、60fps，导出时拒绝源文件变化并完整解码核对帧数/时间。内存不足用 `--segments 1`。不通过关闭用户应用腾内存。

完成后看真实成片关键帧和动态片段；check返回技术数据，不替代字幕专名、语义、构图和听感验收。
