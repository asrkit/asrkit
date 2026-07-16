# ASRKit 模型管理设计（对标 Ollama + LiteLLM）

> 定位：ASR 界的 Ollama（本地）+ LiteLLM（云端）。本地照搬 Ollama 的成熟方案，
> 云端照搬 LiteLLM，两者统一在一个接口下。评测/横评不在本项目范围。

## 指导原则

- **ASRKit 管理的本地缓存 = Ollama**：`pull` 即拉即用、`模型:tag` 命名、本地存储、`list/run/show/rm`。外部引擎的共享缓存仍归引擎所有。
- **云端 = LiteLLM 式体验**：公开寻址统一为 `<source>/<model>`、按 vendor 解析环境变量 key、后期再考虑 Router 兜底。
- 目标用户零学习成本：用过 Ollama/LiteLLM 的人，直接会用 ASRKit。

---

## 一、命名规则

| 类型 | 格式 | 例子 | tag 含义 |
|---|---|---|---|
| 本地 | `model[:tag]` | `sensevoice`、`sensevoice:fp32` | tag = **量化精度**，默认 `int8` |
| 云端 | `<source>/<model>` | `siliconflow/sensevoice` | LiteLLM 式，无精度概念 |

- 不写 tag → 用默认精度（端侧默认 **int8**，图小图快）。
- **只有"同一份权重、不同量化位数"才算 tag**；蒸馏/语言/大小档都是**独立模型**，不用 tag。
  （如 `sensevoice:int8` vs `sensevoice:fp32` 是精度；`sensevoice` vs `sensevoice-nano` 是两个模型。）

---

## 二、本地存储（Ollama 式）

- 根目录：`~/.asrkit/models/`（可用 `$ASRKIT_MODELS_ROOT` 覆盖）。
- **v0.x（实现现状）**：**平铺** `models/<folder>/`，folder = 模型 id 去掉首段 namespace（如 `sherpa/sensevoice` → `models/sensevoice/`）。`tag` 只是**寻址别名**（`sensevoice:fp32` → 目录 `sensevoice-fp32`），**不是子目录**。每次 pull 使用私有临时目录和 staging,完成校验后在同分区原子 rename 到目标目录。
- **破坏性操作边界**：`pull`/`rm`/`add-model --model-dir` 会拒绝把文件系统根、用户家目录、系统临时根、当前工作目录或 ASRKit 包/源码根当作 models root。若目标目录已经存在但不能通过该模型的安装文件校验，`pull` 不会覆盖，`rm` 也不会递归删除；请先人工确认并移走该目录。自定义 models root 仍是由操作者指定的信任边界，宜使用专门的空子目录。
- **未来**（记着，不急做）：抄 Ollama 的 **manifest + 内容寻址 blob 去重** —— int8/fp32 共享的 `tokens.txt` 只存一份。ASR 的 onnx 文件大，去重有价值，但 v0.x 不做。

### 缓存所有权与运行时就绪

`installed` 与 `cached` 是两个不同事实：

- `installed` 是 adapter-defined legacy installed/readiness signal,保留既有 `list --installed` 语义且随引擎而异：sherpa 检查受管模型文件,外部引擎通常检查运行时包是否存在。
- `cached` 表示模型权重是否已知在本机缓存。ASRKit 不扫描或猜测 HuggingFace、whisper.cpp 等共享缓存，因此这些引擎返回 `null`（unknown）。
- `cache_owner=asrkit` 的 sherpa/用户模型可由 `asrkit rm` 删除；`engine`、`none`、`unknown` 均拒绝删除，避免误删上游共享资产。

`list --json` 增量提供 `cached`、`cache_owner`、`removable`；既有 `installed` 和 `size_bytes` 字段仍保留。

Python 契约用冻结的 `ModelCacheState(owner, cached, removable, location, size_bytes)` 表达同一事实。`BaseAdapter.cache_state()` 默认只检查 ASRKit 明确拥有的 store,不会扫描外部缓存；`remove_cached_model()` 仅在 owner 为 `asrkit` 时进入 store 删除。第三方 `AdapterMeta.cache_owner` 的默认值是 `unknown`,插件只有在确实拥有完整生命周期时才应改为 `asrkit`。

---

## 三、CLI 动词（对齐 Ollama）

```bash
asrkit pull  model[:tag] [--url URL]   # ✅ 通过 adapter 获取；ASRKit 自管模型按内容识别压缩格式并原子安装，外部引擎可委托其上游缓存
asrkit run   model[:tag] 音频          # ✅ 确保 adapter 就绪后 transcribe；ASRKit 自管模型缺失时先 pull
asrkit list                             # ✅ 列出全部（✓=adapter-defined legacy installed/readiness）；支持 --json/--installed/--ids/--source/--lang/--arch 过滤
asrkit show  model                      # ✅ 详情：架构/精度/许可证/语言/multilingual（许可证数据待核实填充）
asrkit transcribe 音频 -m model         # ✅ 只转写（不自动下载）
asrkit rm    model[:tag]                # ✅ 仅删除 ASRKit 管理的模型缓存；外部引擎缓存会安全拒绝
asrkit search term                      # ✅ 按 id/名称子串搜索模型
asrkit stream model 音频 [--mic]        # ✅ 流式转写（文件分块或麦克风实时输入，见 result-contract.md §五）
asrkit serve                            # ✅ 启动 OpenAI 兼容 HTTP 转写网关
asrkit doctor [--net]                   # ✅ 体检安装/密钥/models 目录/config
asrkit completion <bash|zsh|fish>       # ✅ 打印 shell 补全脚本
asrkit engine list/install/default/rm   # ✅ 引擎管理（见 engines-and-addressing.md §八）
asrkit config set-key/get-key/set/list/path   # ✅ 密钥与配置管理（见 §七）
asrkit add-model <id> [--url ...] [--sha256 ...] [--model-dir ...]   # ✅ 注册自定义模型，见 engines-and-addressing.md §九
# —— 以下为路线项，尚未实现 ——
asrkit list --available            # 🔜 目前没有"仅列可远程获取"的过滤开关；list 总是列出全部内置+已注册模型（--installed 只能筛出 installed/readiness 为 true 的本地项）
```

`transcribe` 保留（编程/明确语义）；`run` 是 Ollama 式的傻瓜入口。

---

## 四、模型索引（registry）

一张 curated 表，每个模型登记：

```
sensevoice:
  架构(config_type): senseVoice
  语言: [zh,en,ja,ko,yue]
  许可证: Apache-2.0        # 目标字段示例;当前内置本地模型的 license 覆盖尚未完成
  默认精度: int8
  精度:
    int8: { download_url: A, 装完选文件: model.int8.onnx, 体积: 228M }
    fp32: { download_url: B, 装完选文件: model.onnx,      体积: 894M }
```

- **同包双精度** → 两 tag 同一 `download_url`，加载时挑不同文件（复用 worker.py `_find` 的 int8 优先逻辑）。
- **独立包** → 不同 `download_url`。
- **只有一种** → 只登记一个 tag。
- **无需自建服务器**：`download_url` 直连 sherpa-onnx 的 GitHub releases。数据源：你已有的 `models.dart` / `registry.json` / 下载脚本。
- **下载格式自动识别**：`pull` 不依赖 URL 后缀，而是按文件内容（magic bytes）识别压缩格式——支持 `.tar.bz2`/`.tar.gz`/`.tar.xz`、纯 `.tar`、`.zip`；解压时对 tar 与 zip 均有路径穿越防护（`store.py` 的 `_safe_extract`/`_safe_extract_zip`），不会因恶意压缩包写到目标目录之外。
- **自定义下载地址**：`asrkit pull <model> --url <URL>` 可覆盖模型的默认 `download_url`，从任意地址下载（同样按内容识别格式）。
- **元数据覆盖现状**：`license`/官方来源/`sha256` 字段已经存在,但内置本地模型尚未完成覆盖,不能把空字段当作已核验。补齐计划见 [roadmap.md](roadmap.md)。
- **用户自定义模型（模型开放）**：不在内置表里的 sherpa 模型，写进 `~/.asrkit/models.json`（或 `$ASRKIT_MODELS_JSON`）即可注册。也可用 `asrkit add-model <id> --url <URL> --arch <config_type> --langs zh,en` 一条命令登记；`--sha256` 可校验下载文件。已有文件时用 `--model-dir <path>`：ASRKit 在 models root 内创建 leaf symlink，安装判断和运行时正常跟随；`rm` 只删除链接、保留外部目录。来源必须是已存在目录，且不能包含将要创建的链接；父路径软链与 `.`/`..` ID 会被拒绝。

---

## 五、云端约定（LiteLLM 式）

- **key 解析顺序**（✅ 已实现）：显式 `config["api_key"]` > 环境变量 `<VENDOR>_API_KEY`（如 `SILICONFLOW_API_KEY`）> `~/.asrkit/config.json` 本地明文配置（权限 0600，`asrkit config set-key <vendor>` 写入，见 §七）。
- **`<source>/<model>` 寻址**：已实现。外部 source 对云端通常是 vendor namespace、对本地是 engine namespace;内部 `provider` 是协议 adapter key,不要与公开 model id 首段混为一谈。
- **密钥按 vendor 共享**：同厂商多模型共用一个 key（已在契约体现）。
- **已实现**：共享 HTTP 分级重试/退避、请求超时、豆包轮询 deadline。
- **尚未实现**：端侧失败自动切云、策略路由和多 key 轮换;有真实需求后再设计。

---

## 六、v0.x 落地范围

**已完成**：`模型:精度` 命名 + 平铺 `models/<model>/` 存储 + ASRKit 自管缓存的 `pull`（支持 `--url`、多压缩格式自动识别）/安全 `rm` + `run` / `list` / `show` / `search` / `add-model`；精度 `int8`(默认) / `fp32`；云端 `<source>/<model>` 路由 + 环境变量/配置文件 key 解析。

**不做**：blob 去重、Router 兜底、评测/横评（见 `roadmap.md` 的独立项目决定）。

## 七、配置与体检

模型管理离不开密钥存储、模型根目录配置、装机自检，三者都由独立子命令承担：

```bash
asrkit config set-key <vendor>          # 存储云端厂商密钥（写入 ~/.asrkit/config.json）
asrkit config get-key <vendor>          # 查看已存密钥（掩码显示）
asrkit config set models-root <path>    # 等价于设置 ASRKIT_MODELS_ROOT；优先级：显式 config > env > config.json > 默认 ~/.asrkit/models
asrkit config set default-engine <name> # 设默认引擎（裸名解析依据）
asrkit config list                       # 显示全部配置（密钥掩码）
asrkit config path                       # 打印配置文件路径
asrkit doctor [--net]                    # 体检：引擎安装状态 / 密钥是否配置 / models 目录 / config 内容
```
