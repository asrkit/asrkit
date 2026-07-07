# W3b-3 设计 v2 — `asrkit doctor`(体检命令)(含 Codex 评审修订)

> 状态:brainstorming + Codex(gpt-5.5)评审(采纳 7 项),待写实现计划。
> 目标波次:W3b 第三刀(doctor);P2 最后一项。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄";纯诊断(只读、无持久副作用);零新运行时依赖;网络 opt-in。
>
> **v2 修订**(Codex `.omc/artifacts/ask/codex-*2026-07-07T14-47-35*.md`):models 目录改**试写探针**(os.access 不可靠);**corrupt config 列为硬失败**(config.load 静默吞错、doctor 会漏);密钥只扫**已注册云端 vendor** 的精确 env 名;`--net` 探具体 URL + `timeout=2.0`;模型计数只统计 **store 管理的 sherpa meta**;引擎注明"包存在";可写探针抽 helper + 便携测试。

---

## 1. 背景与目标

roadmap P2:`asrkit doctor` —— 一条命令查"为啥装不上/跑不了",降低支持成本。**默认离线**(快、可靠),网络检查 `--net` opt-in(用户已定;网络慢/flaky)。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 网络检查 | opt-in `--net`;默认只跑离线检查 |
| D2 | 检查项(离线) | 版本 / 引擎(包存在否)/ 密钥(有没有,只报 vendor 不泄露)/ models 目录**可写(试写探针)**/ **config 完整性** |
| D3 | 退出码 | **硬问题**(models 存储不可用 / **config 损坏**)→ 非零(1);缺引擎/缺密钥/网络不可达/目录未建 = **信息**(退 0) |
| D4 | 网络项状态 | `--net` 探到不可达 → 记 `info`(不算 fail,网络瞬时且已被去优先);仅报可达/不可达 |
| D5 | 结构 | 新 `asrkit/doctor.py`:`diagnose(net) -> list[Check]`;cli 渲染 + 定退出码。不塞 god-file cli |
| D6 | 不做 | 自动修复、逐云端厂商探活、doctor 里跑真实推理 |

---

## 3. 设计

### 3.1 `asrkit/doctor.py`(新)

```python
@dataclass
class Check:
    name: str
    status: str   # "ok" | "info" | "fail"
    detail: str

def diagnose(net: bool = False) -> list[Check]: ...
```

**离线检查(始终)**:
1. **版本**:`asrkit` 版本、`python` 版本 → ok。
2. **引擎**:遍历 `engines.ENGINES`,`is_installed(name)` → 装了 `ok`("package present");没装 `info`("not installed — pip install asrkit[<extra>]")。detail 注明这是**包存在**(sherpa 另需 numpy/soundfile/soxr 做音频 io)。
3. **密钥**:从**已注册的云端 meta** 派生 vendor 集合;对每个 vendor 查 keystore(`config.get_creds(vendor)`)与**精确** env 名(`<VENDOR>_API_KEY`/`_APP_KEY`/`_ACCESS_KEY`,vendor 大写)→ 报"present (keystore/env)"或"none";**只报 vendor 与来源,绝不打印密钥值**;半对(如 doubao 只有 app_key)照实报。→ `info`。
4. **models 目录**:`store.models_root()` 路径 + **试写探针 `_writable(path)`**(存在→`tempfile.mkstemp` 写后 `finally` 删;不存在→探最近存在的父目录同法;**doctor 不创建 models 目录**)。目录不存在但父可写 → `info`("not created yet; created on first pull",退 0);非目录 / 父不可写 → `fail`。已装模型数/体积:**只统计 store 管理的 meta**(`provider=="sherpa-onnx"`),用 `store.is_installed(m)`/`store.dir_size(m)`(faster-whisper/transformers/whispercpp 用外部 HF 缓存,不在 models_root,不计)。
5. **config 完整性**:**直接读 `config.path()`**(不经会静默吞错的 `config.load()`):文件不存在 → `info`("no config yet");存在但**读不了/JSON 解析失败/section 类型不对** → `fail`("config corrupt: <path>");正常 → `ok`,附 default-engine、models-root 设置。

**网络检查(仅 `--net`)**:
- `_probe(url, timeout=2.0) -> bool`(短超时、**无重试**、urllib 的 HEAD;不用 `_http`——那是 POST/重试专用)。
- 探**具体** URL:一个代表性 sherpa `download_url`(HEAD,失败可 `Range: bytes=0-0` 兜底);已配置云端 vendor 的 `default_base_url` origin。
- 可达 `ok`、不可达 `info`(**永不 fail**;网络瞬时且已去优先)。

### 3.2 `cli.py`

- `doctor` 子命令:`dp.add_argument("--net", action="store_true", help="also check network reachability (download source / cloud)")`。
- 处理:
  ```python
  if a.cmd == "doctor":
      from . import doctor
      checks = doctor.diagnose(net=a.net)
      marks = {"ok": "✓", "info": "○", "fail": "✗"}
      for c in checks:
          print(f"{marks.get(c.status, ' ')} {c.name}: {c.detail}")
      return 1 if any(c.status == "fail" for c in checks) else 0
  ```

---

## 4. 契约/行为影响

- **纯增量**:新 `doctor` 子命令 + `doctor.py`;不动任何 adapter/云端/其它命令。
- 只读诊断,不创建/修改文件(models 目录可写探针不留副作用:用 `os.access`,不写文件)。

---

## 5. 模块与改动清单

| 文件 | 改动 |
|---|---|
| `asrkit/doctor.py` | **新增**:`Check` + `diagnose(net)` + `_writable(path)` + `_probe(url, timeout=2.0)` |
| `asrkit/cli.py` | `doctor` 子命令 + 渲染 + 退出码 |
| `tests/test_doctor.py` | **新增** |
| `docs/usage.md` / `CHANGELOG.md` | 用法 + `[Unreleased]` |

---

## 6. 测试(离线为主,网络 mock)

- **`diagnose()` 离线**:返回项含 asrkit/python 版本、每个引擎、keys、models-dir、config;类型为 `Check`(name/status/detail)。
- **密钥不泄露**:`ASRKIT_CONFIG` 指临时文件、存一个 vendor 密钥,断言输出**含 vendor 名、不含密钥明文**;半对(只 app_key)照实报;无关 env 变量(如随便一个 `FOO_API_KEY` 非注册 vendor)**不被误报**。
- **models 目录不可写 → fail(便携)**:`monkeypatch doctor._writable` 返回 False,断言 models-dir 项 `status=="fail"` 且 cli 退出非零(不依赖 chmod);**另加** POSIX-only 真 chmod 测试(`chmod 0o500` + `ASRKIT_MODELS_ROOT`),用 `hasattr(os,"geteuid")` 且 `os.name!="nt"` 且非 root 才跑。
- **目录未建 → info 退 0**:`ASRKIT_MODELS_ROOT` 指一个不存在但父可写的路径,断言 models-dir 项 `info`、cli 退 0。
- **config 损坏 → fail**:`ASRKIT_CONFIG` 指一个写了非法 JSON 的文件,断言 config 项 `fail` 且 cli 退出非零。
- **cli 退出码**:全 ok → `cli.main(["doctor"])` 返回 0。
- **`--net`**:`monkeypatch doctor._probe` 返回 False/True(不打真网),断言含 net 项、net 不可达时**仍退 0**(info 不 fail)。
- **回归**:不影响其它命令。

---

## 7. 明确不做(YAGNI)

自动修复、逐云端厂商探活、深度网络诊断、doctor 里跑推理、检查 pip 包冲突/版本兼容。

---

## 8. 风险与兼容

- **纯只读诊断 + CLI 层**,回归面极小;不写文件(`os.access` 探可写,不留副作用)。
- 退出码保守:仅目录不可写才非零 —— 缺引擎/密钥/网络是常态信息,不误报失败。
- `--net` 探针短超时且 `info` 语义,不因网络抖动污染退出码。
