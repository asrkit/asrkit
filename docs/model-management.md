# ASRKit 模型管理设计（对标 Ollama + LiteLLM）

> 定位：ASR 界的 Ollama（本地）+ LiteLLM（云端）。本地照搬 Ollama 的成熟方案，
> 云端照搬 LiteLLM，两者统一在一个接口下。评测/横评不在本项目范围。

## 指导原则

- **本地 = Ollama**：`pull` 即拉即用、`模型:tag` 命名、本地存储、`list/run/show`。
- **云端 = LiteLLM**：`provider/model` 字符串、按 vendor 的环境变量 key 约定、（后期）Router 兜底。
- 目标用户零学习成本：用过 Ollama/LiteLLM 的人，直接会用 ASRKit。

---

## 一、命名规则

| 类型 | 格式 | 例子 | tag 含义 |
|---|---|---|---|
| 本地 | `model[:tag]` | `sensevoice`、`sensevoice:fp32` | tag = **量化精度**，默认 `int8` |
| 云端 | `provider/model` | `siliconflow/sensevoice` | LiteLLM 式，无精度概念 |

- 不写 tag → 用默认精度（端侧默认 **int8**，图小图快）。
- **只有"同一份权重、不同量化位数"才算 tag**；蒸馏/语言/大小档都是**独立模型**，不用 tag。
  （如 `sensevoice:int8` vs `sensevoice:fp32` 是精度；`sensevoice` vs `sensevoice-nano` 是两个模型。）

---

## 二、本地存储（Ollama 式）

- 根目录：`~/.asrkit/models/`（可用 `$ASRKIT_MODELS_ROOT` 覆盖）。
- **v0.x**：一变体一目录 —— `models/<model>/<tag>/`（如 `models/sensevoice/int8/`）。同一模型多精度共存不打架。
- **未来**（记着，不急做）：抄 Ollama 的 **manifest + 内容寻址 blob 去重** —— int8/fp32 共享的 `tokens.txt` 只存一份。ASR 的 onnx 文件大，去重有价值，但 v0.x 不做。

---

## 三、CLI 动词（对齐 Ollama）

```bash
asrkit pull  model[:tag]          # 下载（+解压+按精度就位）
asrkit run   model[:tag] 音频     # = pull（若缺）+ transcribe，Ollama 式一步到位
asrkit list                        # 已安装的
asrkit list --available            # 索引里可拉的全部
asrkit show  model                 # 详情：架构/各精度/体积/许可证/语言
asrkit rm    model[:tag]           # 删除（可选，后补）
```

`transcribe` 保留（编程/明确语义）；`run` 是 Ollama 式的傻瓜入口。

---

## 四、模型索引（registry）

一张 curated 表，每个模型登记：

```
sensevoice:
  架构(config_type): senseVoice
  语言: [zh,en,ja,ko,yue]
  许可证: Apache-2.0        # LiteLLM/Ollama 都不标，这是 ASRKit 的加分项
  默认精度: int8
  精度:
    int8: { download_url: A, 装完选文件: model.int8.onnx, 体积: 228M }
    fp32: { download_url: B, 装完选文件: model.onnx,      体积: 894M }
```

- **同包双精度** → 两 tag 同一 `download_url`，加载时挑不同文件（复用 worker.py `_find` 的 int8 优先逻辑）。
- **独立包** → 不同 `download_url`。
- **只有一种** → 只登记一个 tag。
- **无需自建服务器**：`download_url` 直连 sherpa-onnx 的 GitHub releases。数据源：你已有的 `models.dart` / `registry.json` / 下载脚本。

---

## 五、云端约定（LiteLLM 式）

- **key 解析顺序**：显式 `config["api_key"]` > 环境变量（按 vendor，如 `SILICONFLOW_API_KEY` / `DASHSCOPE_API_KEY`）> 配置文件。
- **`provider/model` 路由**：已实现（协议 adapter 按 provider 分派）。
- **密钥按 vendor 共享**：同厂商多模型共用一个 key（已在契约体现）。
- **后期（阶段 4，抄 LiteLLM Router）**：兜底（端侧失败切云端）、重试、超时、多 key 轮换。现在不做。

---

## 六、v0.x 落地范围

**做**：`模型:精度` 命名 + `models/<model>/<tag>/` 存储 + `pull` / `run` / `list` / `show`；精度只填 `int8`(默认) / `fp32`；云端加"环境变量 key"约定。

**不做**：blob 去重、Router 兜底、评测/横评。

**顺序**：先按本设计**重构注册表**（平铺 47 条 → 模型 + 精度 tag），再做 `pull`（有了命名/存储地基才能下对、放对）。
