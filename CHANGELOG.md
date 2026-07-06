# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.2] - 未发布

### 新增
- `asrkit --version` / `-V` 显示版本。
- `asrkit rm <model>` 删除已下载的本地模型（补全 pull/rm 生命周期，Ollama 对齐）。
- **本地模型名可省略 `local/` 前缀**：`asrkit pull sensevoice` = `local/sensevoice`（含精度别名 `sensevoice:fp32`）。全名与云端 `provider/model` 不受影响；命名空间仍是正式名（未来多引擎不打脸）。

### 说明
- 无 `update` 命令：模型按 id 钉死（换模型即 `pull` 另一个 id）；升级软件包用 `pip install -U asrkit`。

## [0.1.1] - 2026-07-06

### 变更
- **安装简化**：`pip install asrkit` 一步装好端云接口（sherpa-onnx + 云端 + 音频）——运行时依赖从 extras 提升为基础依赖，不再需要 `asrkit[all]`。模型权重仍按需 `asrkit pull`、云端填 API key。
- 新增 `asrkit show <model>` 显示模型详情（含许可证展示位）。

## [0.1.0] - 2026-07-06

首个有功能的版本：一套接口跑遍端云。

### 新增
- 统一接口：Python `transcribe()` + CLI（`list` / `pull` / `run` / `transcribe`）。
- 端侧 **47 个 sherpa-onnx 模型**，`pull` 即用（Ollama 式），支持精度标签寻址 `base:tag`（如 `local/sensevoice:fp32`）。
- 云端 **OpenAI 兼容协议**（硅基流动 SenseVoice）；`provider/model` 路由。
- **透明音频**：内核零处理；云端原样上传原始文件；本地格式守卫，采样率/声道/格式不符即诚实报错；`--convert` / `--segment` 为 opt-in；长音频超窗给 `warnings`。
- **pull 安全**：tar 路径穿越防护、下载超时、可选 sha256 校验、原子安装（`.partial` + rename）。
- 云端 API Key 环境变量兜底 `<VENDOR>_API_KEY`。

### 说明
- 评测 / bench 横评、流式转写、serve 常驻为**后续路线项**，本版不含。
- 契约见 `docs/adapter-spec.md`（音频透明原则二次修订后待重评审冻结）。
