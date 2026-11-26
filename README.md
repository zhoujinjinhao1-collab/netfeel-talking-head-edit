# 网感口播剪辑

将真人口播制作成带分层字效、语义重点推近和资料注解的视频，交付 **MP4 + 可编辑 HTML/JS 工程**。

默认 **1.1 倍速、9:16、1080×1920、60fps**，保留原声、音调和台词顺序，加简体中文字幕。每条视频重新安排关键词和推近时机。

## 能做什么

- 逐句粗剪：删除重复起句、口误和明显卡顿，保留每句话最完整正确的一遍。
- 文字包装：大字提问、强调条、引语、阶段编号、关键词逐个展开、否定词强调、下划线和资料注解。
- 人物推近：在纠错、关键否定和判断转折处做轻/强 Zoom in，字幕与资料层保持稳定。
- 声音设计：原声主导，按动作放轻音效，使用本期许可明确的配乐；也支持无配乐。
- 新目录交付：字幕、分轨、来源记录、速度记录、可拖动预览、MP4和可编辑工程。

本仓库包含原创画面模板和独立本地渲染器，**不需要 adu-motion-video 或付费 MotionGit 模板**。粗剪和语义编排由有文件/命令执行能力的助手完成；所附脚本负责确定的速度、媒体装配与渲染工作。它不是剪映/PR插件，也不是双击即可全自动完成创作的桌面软件。

## 安装

需要 Git、Python 3.10+、Node.js 18+、FFmpeg/ffprobe 和 Chromium 浏览器。可用 Chrome/Edge，也可下载 Playwright Chromium。已安装的工具可直接复用。

从原片转写还需要助手可用的语音识别工具，例如本地faster-whisper；也可以提供已校对的带时间码字幕。基础依赖清单只包含制作与渲染所需的库，不包含语音识别模型；模型需要按使用环境另行安装或下载。

### Windows PowerShell

```powershell
git clone https://github.com/zhoujinjinhao1-collab/netfeel-talking-head-edit.git "$env:USERPROFILE\.codex\skills\netfeel-talking-head-edit"
Set-Location "$env:USERPROFILE\.codex\skills\netfeel-talking-head-edit"
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
```

如果FFmpeg或Node未安装，先安装并使其可从命令行访问。本机没有Chrome/Edge时，在技能目录执行：

```powershell
npx playwright install chromium
```

### macOS / Linux

```bash
git clone https://github.com/zhoujinjinhao1-collab/netfeel-talking-head-edit.git "$HOME/.codex/skills/netfeel-talking-head-edit"
cd "$HOME/.codex/skills/netfeel-talking-head-edit"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npx playwright install chromium
```

Linux无桌面环境可能还需要系统依赖，参见[Playwright浏览器安装说明](https://playwright.dev/docs/browsers)。本项目的Linux自动测试固定使用Ubuntu 24.04，避免`ubuntu-latest`升级带来的浏览器兼容问题；其他发行版请核对Playwright支持情况。渲染器也接受 `CHROME` 环境变量指定已安装浏览器的可执行文件。

使用自定义 `CODEX_HOME` 时，把技能放在该目录的 `skills/netfeel-talking-head-edit` 下。其他支持读取 `SKILL.md`、访问本地文件和执行命令的助手，也可加载本目录使用。

## 使用提示词

将口播视频提供给助手；有定稿就一起提供，用于核对专名和术语。

### 直接完成整条

```text
用 $netfeel-talking-head-edit 处理我刚上传的口播。
按这个技能的网感风格直接剪完整条，不再做样片。
固定1.1倍速，保留原声与台词顺序，加简体中文字幕。
文字包装丰富一些，在关键判断和否定词处做人物Zoom in。
导出MP4和可编辑工程，另存新目录。
```

### 先做样片

```text
用 $netfeel-talking-head-edit 处理我提供的口播。
先做20–30秒样片，展示分层文字包装和重点人物推近。
默认1.1倍速，确认后再做整条。
```

可附加“这条不要背景音乐”“人物推近克制一点”“院校名对照附上的定稿”。新安装者不需要之前的聊天；[SKILL.md](SKILL.md) 和[风格规范](references/style.md)包含完整风格说明。

## 手动制作接口

助手应先完成逐句粗剪，再用以下脚本。字幕和分镜使用**实际倍速后底片**的时间。

```text
python scripts/prepare_talk.py 粗剪.mp4 新底片目录 --input-speed 1
python scripts/build_project.py --prepared 新底片目录 --captions 字幕.json --plan 本期plan.json --dest 新工程目录
python scripts/render.py stills 新工程目录 新静帧目录 --times 1,3.7
python scripts/render.py video 新工程目录 新成片.mp4 --segments 2
python scripts/render.py check 新成片.mp4
```

请使用上面虚拟环境中的Python运行这些命令。字幕/分镜格式、样片区间、声音和来源记录详见[工程输入与命令](references/project.md)。不同机器需按实际人物构图检查字幕和裁切位置；模板不是人脸追踪器。

已做1.1倍的底片声明 `--input-speed 1.1`，直接复用；已做1.2倍的底片声明 `--input-speed 1.2`，只应用1.1/1.2。不要把已加速素材当成原速再加速。`--target-speed` 可显式覆盖本次目标。

渲染默认两段并行、每个编码器两线程；内存不足用 `--segments 1`。项目资源需要全部落地，不在渲染时加载远程图片。输出拒绝覆盖旧文件，写入成片前校验完整解码、帧数、逐帧时钟和源文件未变化。

## 许可与数据

代码、说明和模板为[MIT许可](LICENSE)。字体保留各自的SIL OFL，见[NOTICE](NOTICE)。素材、原声、音乐和事实出处由每次制作单独核查；仓库不附带私人视频、个人口播稿、音乐曲目、付费模板或平台凭据。

用于政策、身份、招生、投资或保险内容时，需要当期官方来源及适用条件。生成成功和技术检测通过不代表事实已经正确，也不代表已经逐秒人工试听。


## 新增：口播图解剪辑（独立技能）

仓库还提供 [talking-head-infographics](skills/talking-head-infographics/SKILL.md)，中文名「口播图解剪辑」。适合把口播重点做成动态对照、步骤、公式或证据图：人物缩窗，精致中文字体，主词放大，字幕与口播对齐。默认约25秒样片、原速、9:16、1080×1920、30fps；本次明确参数优先。

它与根目录的「网感口播剪辑」独立，安装时需要复制整个子目录，而不是只复制SKILL.md。用自定义CODEX_HOME时相应调整目标：

~~~powershell
git clone https://github.com/zhoujinjinhao1-collab/netfeel-talking-head-edit.git
Copy-Item -LiteralPath .\netfeel-talking-head-edit\skills\talking-head-infographics -Destination "$env:USERPROFILE\.codex\skills\talking-head-infographics" -Recurse
Set-Location "$env:USERPROFILE\.codex\skills\talking-head-infographics"
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

macOS/Linux：克隆后，将skills/talking-head-infographics复制到当前助手的技能目录，再用Python虚拟环境安装该子目录requirements.txt。此技能不需要Node.js或Chromium。FFmpeg可复用系统安装，也可用imageio-ffmpeg随附版本。ASR需要助手已有的本地工具或用户校对稿，不附带语音模型。

字体可按需从Adobe官方仓库下载到本期工程，或指定已授权中文字体。字体下载脚本校验SHA-256并保存OFL许可证，不依赖系统专用字体。

~~~text
用 $talking-head-infographics 处理我上传的口播，
先做25秒样片，重点优化文字美观、图解逻辑和排版，
保留原声，交付MP4。
~~~

详见[排版规范](skills/talking-head-infographics/references/style.md)及[计划格式与渲染命令](skills/talking-head-infographics/references/project-format.md)。工具交付MP4、SRT和可编辑计划JSON，不冒称剪映/PR原生工程。渲染器按计划工作，语义分镜、转写校对和事实核查仍由使用技能的助手完成。

本子技能不含私人原片、口播稿、成片、凭据或预装模型。测试仅使用合成测试画面；代码沿用MIT许可，下载的字体遵循其各自OFL。

