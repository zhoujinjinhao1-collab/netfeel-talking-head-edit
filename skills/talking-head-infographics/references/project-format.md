# 计划格式与命令

使用Python 3.10+安装requirements.txt。支持系统FFmpeg（FFMPEG环境变量或命令行ffmpeg），其次使用imageio-ffmpeg。

## 创建当期工程

把assets/example.plan.json复制到本期目录并改写，不直接修改技能示例。以下命令在技能目录执行，或使用脚本绝对路径：

~~~text
python scripts/fetch_fonts.py --dest 本期工程/fonts
python scripts/render.py preview --input 原片.mp4 --plan 本期工程/plan.json --output 本期工程/预览01
python scripts/render.py video --input 原片.mp4 --plan 本期工程/plan.json --output 本期工程/成片01
python scripts/render.py check 本期工程/成片01/video.mp4
~~~

输出目录必须不存在；预览和正式导出使用不同目录。字体和图片路径相对计划JSON解析。可用自己的中文字体，不强制下载，也不在渲染时加载远程素材。

## 时钟和字段

- duration：输出秒数。fps默认30，width默认1080且需为偶数；高度按9:16计算。
- clips：原片时间区间列表，每项start/end，严格保留顺序。拼接后从0计时，所有字幕、scene和入场at使用该输出时钟。
- duration不能短于剪辑总时长；多出的短尾默认最多1.5秒。不要用长定帧把17秒冒充有25秒内容的样片。
- fonts：display/body两个本地文件路径；主标题选family: display，其余默认body。自行检查中文覆盖，脚本不能识别每一个缺字方框。
- style：paper/ink/muted/accent/negative/gold可选颜色；元素用$accent等引用。
- captions：start/end/text及可选highlight，highlight必须是字幕原文子串。字幕位于下部，来自实际保留语音。
- scenes：连续覆盖[0,duration]的start/end；background为paper或video。section为右上章节名，可留空。portrait可省略；有则用box:[x,y,w,h]，可选crop:[left,top,right,bottom]是0到1归一化坐标。原视频先中心裁为9:16；横片需按人物位置先制作合适底片。

坐标使用720×1280逻辑画布，与输出像素无关。字幕在下部，图解避让；人物框位置按本期素材确认。

## 元素

scene的elements从前向后绘制：

- text：x/y、text、size，可选family、color、align（left/center/right）。x/y指可见文字边界；多行用独立元素明确行距。
- rect：box:[left,top,right,bottom]、fill，可选radius、outline、stroke。
- line和arrow：points:[[x1,y1],[x2,y2]]、color、stroke。线随入场展开。
- image：本地path和box:[x,y,w,h]，按框中心裁切。

at是开始入场的输出时间，默认scene.start；enter默认0.35秒，move_y默认12逻辑像素；until表示停止显示。花字轮换或逐项展开用多个元素，不在字符串里执行表达式。

渲染器拒绝越界文字、纸色页被人物框遮挡的文字及进入字幕区的图解文字。确有叠加设计可为该文字设置allow_overlap: true，并自行检查。文字与底色矩形叠放属于正常设计。

## 产物与限制

preview输出联系表和独立关键帧；video输出video.mp4、captions.srt、plan.json、report.json。报告记录输入摘要、时长/帧数和实际响度检测结果。输入不修改。

脚本按计划渲染，不自动选take、校对ASR、判断图解逻辑、追踪人脸或核查事实，不承诺原生剪映/PR工程。正式导出要求原片有音轨。

## 安装到助手

复制整个talking-head-infographics目录到当前助手的技能目录；Codex通常为CODEX_HOME/skills，未自定义时为用户目录下.codex/skills。不要只复制SKILL.md。另建Python虚拟环境安装本目录requirements.txt。调用：

~~~text
用 $talking-head-infographics 处理我上传的口播，
先做25秒样片，重点优化中文字体、图解逻辑和排版，
保留原声，交付MP4。
~~~
