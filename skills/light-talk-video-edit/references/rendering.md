# 渲染器配置与执行

`scripts/render_light.py` 为快速试剪提供可复用构图；`assets/example-project.json` 给出最小可修改范例。运行前读取范例并替换本次素材、字幕与时间，不原样套用示例文案。

## 命令

```text
python scripts/render_light.py --config project.json --check
python scripts/render_light.py --config project.json --preview
python scripts/render_light.py --config project.json
python scripts/verify_video.py output.mp4 --ffmpeg /path/to/ffmpeg --expected-duration 12
```

渲染器输出 MP4、实际采用的成片字幕、配置副本和关键画面。默认不覆盖已有成片；确定需要覆盖时传 `--overwrite`。临时中间文件放在成片旁的 `.<成片名>_work`，便于复查。分辨率为 720×1280，帧率由配置决定；其他版式/高分辨率原生制作需适配脚本或使用合适的编辑工具。

## 路径与时间

所有相对路径相对于配置文件。`source` 是原视频；`output` 是成片路径；`ffmpeg` 可省略并从环境发现。

- `keep`: 原片秒数区间，按播放顺序串联。省略时保留整片。区间不应重叠，除非确实需要重复播放。
- `source_captions`: `[原片开始秒, 原片结束秒, 文本]`；脚本按 keep 映射到成片。
- `captions`: `[成片开始秒, 成片结束秒, 文本]`。两种字幕字段只选一种。
- `scenes` 的 `start/end`、`appear` 和 `preview_times` **全部是成片秒数**，不能直接填原片秒数。
- `audio_source`: 可选，取该文件完整音轨用于只改包装的版本；其时长必须与成片一致到约一帧。`copy_audio: true` 时直接复制兼容音轨。
- `normalize_voice`: 默认 false。新片需要语音响度调整时可以开启，纯视觉改版则使用既有音轨。

不能把完整原片的音轨直接接在删减后的画面上。仅换皮时，推荐将已经删减、没有包装的干净视频作为 `source`，将认可版 MP4 作为 `audio_source`，省略 keep，沿用成片时间的字幕与场景。

## 风格与取景

`brand`: 顶部的 `title`、英文 `english`、片尾/底栏 `footer`。

`theme`: 可覆盖设计规范里的 `ink, green, sage, peach, paper, muted` 色值。

`fonts`: 可指定 `regular, bold, latin, serif` 字体路径。未指定时尝试本机常用字体。中文/混合文本始终由 regular/bold 字体绘制。

`pip_crop`: `[x,y,w,h]`，相对于归一化后的 720×1280 主画面，值域 0–1。提供它才显示人物窗；未提供时不猜测脸部位置。脚本先将 source 等比例填充并中心裁成 9:16，因此横屏或构图变化明显的片子应先另作取景，且必须抽查裁切。

## 场景

未覆盖的区间显示人物画面和常规字幕。场景不重叠；需要覆盖字幕之外的装饰时，合并到对应场景中。

共同字段：`kind,start,end,title,subtitle,kicker,photo,credit,number,items,appear`。photo 和 credit 仅在需要图片时填写。不给图片时脚本显示概念图底，不伪造资料截图。

| kind | 构图 | 主要配置 |
|---|---|---|
| talking | 人物+浅色标题卡 | title/subtitle，可省略标题只留字幕 |
| photo | 浅色画布+大照片+人物窗 | photo/credit/title/subtitle |
| gateway | 照片或概念面板+三个连接节点 | 三个 items，可指定 label、英文 secondary、icon；appear 控制逐项出现 |
| identity | 叠层主卡+并列小卡 | card_title，最多三个 items；可改为任意并列主题 |
| stability | 简洁建筑或概念插画+纵向条目 | 最多三个 items；建筑象征不适合主题时改图或另用其他构图 |
| end | 人物+留言卡 | title/subtitle，采用本次获准的行动文案 |

`items`: 例如 `{"label":"全球","secondary":"GLOBAL","icon":"globe"}`。可用图标为 `city,globe,edu,shield,check,chat`；不认识的图标会报错，避免默默画错图。

`appear`: 数组，数量和 items 一致，每个值为条目出现的成片秒数。默认从场景开始分批加入。需要字幕/语气同步时填写真实提示点，不依赖默认间隔。

## 检查与限制

渲染器能验证区间、资源、字幕是否过长等结构问题，不能自动确认口播准确性、素材版权或脸部取景。`--preview` 只检查静态布局，仍需核对动态入场和声画同步。

`verify_video.py --audio-reference approved.mp4` 可以比较压缩音频包的哈希，只适用于直接复制音轨的改版。音频重新编码时哈希必然不同，不能据此判断听感质量。
