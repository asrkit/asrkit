# ASRKit 路线图 / 待办

> 活文档:记录**尚未做**的改进与**明确不做**的决定。初期"完善三组(输出格式/config/serve)"的详细计划见
> [roadmap-cli-completeness.md](roadmap-cli-completeness.md)(已全部完成)。
> 版本策略见 [CHANGELOG](../CHANGELOG.md):0.x 阶段功能/修复默认走 PATCH,MINOR 只留破坏性/里程碑。

---

## 已完成(近期)

- **0.5.0** 接口内核极简化(base 只留接口+云端,引擎全 opt-in)。
- **0.5.1** 加固(一轮 fresh-eyes 评审后):serve 不再卡死 + **按 model id 缓存 adapter**(本地模型不再每请求重载)、原子写 models.json、路径穿越防御、裸文件名不崩、插件告警、云端大文件守卫。

---

## 待办(按优先级)

### P2 · 值得做

- **`asrkit doctor`(体检命令)** —— 一条命令查:哪些引擎装了、哪些密钥配了、`~/.asrkit/models` 可写否、能否连通模型下载源/云端。降低"装不上/跑不了"的支持成本。
- **CI 加固** —— 纳入 `ruff`(lint)+ `mypy`(有了 `py.typed`);装 `asrkit[serve]` 让 serve 测试不 skip;确认覆盖 config/formats。
- **云端 HTTP 健壮性** —— 每个云端 adapter 现在是一次性 `requests.post`,无重试/退避/共享 Session。加:共享 `requests.Session`、统一超时、瞬时错误(429/5xx/超时)指数退避重试;doubao 轮询同理。serve 高频调云端时收益明显。
- **最小真实 E2E 回归** —— 从 [asr_bench](../../Documents/AI-Lab/asr_bench)(真机端到端所在,**只读参考**)挑一小段音频 + 一个小端侧模型(如 whisper-tiny)做一条端到端 CI,让 repo 内也有真实推理覆盖(现在只有冒烟)。

### P3 · 功能补全(按需)

- **流式转写** —— `BaseAdapter.transcribe_stream` 已声明但无人实现、CLI/serve 未暴露;实时字幕/边说边转需要。大工程。
- **批量 / 目录输入** —— `asrkit transcribe *.wav` 或传文件夹,ASR 常是批处理。
- **`--verbose` / 日志** —— serve 与调试用;现在信息只进 `result.error`,服务端不好排障。

### P4 · 打磨

- **`asrkit engine rm`(劝告版)** —— 打印手动 `pip uninstall <包>` + 提醒(可能被别的项目共享),并重置默认引擎若指向它;**绝不代跑 uninstall**。让命令面完整而不越权。

---

## 明确不做(已讨论定案,勿重复起意)

- **asrkit 自动 `pip uninstall` 引擎** —— 引擎是**共享 pip 包**,asrkit 无产权,删了会连累别的项目。装可帮(装对环境)、卸归用户。
- **为"卸引擎"引入隔离环境** —— 引擎体积小(几十 MB,torch 除外),不卸也罢;占体积的是模型,而模型 `pull`/`rm` 已对称干净。隔离得不偿失。
- **`engine disable` 开关** —— YAGNI:引擎既然不用卸,就不需要"不删包地拔"。
- **把 base 依赖装回去** —— 定位是"接口内核极小",引擎按需装是刻意设计,不回退。

---

## 所有权模型(一句话备忘)

- **模型 = asrkit 独占**(下到 `~/.asrkit/models`)→ `pull` / `rm` 对称、干净。
- **引擎 = 共享 pip 包** → `asrkit engine install`(帮你装对环境)/ 卸载归 `pip uninstall`(你的环境你做主)。
- **云端 = 内置**(仅 `requests`)。
