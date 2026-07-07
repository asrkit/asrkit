# W3b-3 设计 — `asrkit doctor`(体检命令)

> 状态:已通过 brainstorming,待写实现计划。
> 目标波次:W3b 第三刀(doctor);P2 最后一项。落地默认下个 PATCH,升号先问人类。
> 定位约束:守住"接口内核极薄";纯诊断(只读不修);零新运行时依赖;网络检查 opt-in。

---

## 1. 背景与目标

roadmap P2:`asrkit doctor` —— 一条命令查"为啥装不上/跑不了",降低支持成本。**默认离线**(快、可靠),网络检查 `--net` opt-in(用户已定;网络慢/flaky)。

---

## 2. 已定决策

| # | 决策 | 取值 |
|---|---|---|
| D1 | 网络检查 | opt-in `--net`;默认只跑离线检查 |
| D2 | 检查项(离线) | 版本 / 引擎装没装 / 密钥有没有(打码不泄露)/ models 目录可写否 / 配置 |
| D3 | 退出码 | 仅**硬问题**(models 目录不可写)→ 非零(1);缺引擎/缺密钥/网络不可达 = **信息**(退 0) |
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
2. **引擎**:遍历 `engines.ENGINES`,`is_installed(name)` → 装了 `ok`("installed");没装 `info`("not installed — pip install asrkit[<extra>]")。
3. **密钥**:`config.load()` 的 `keys` 里哪些 vendor 有凭据(**只列 vendor 名,不打印任何密钥值**)+ 扫 `os.environ` 里的 `*_API_KEY`/`*_APP_KEY`/`*_ACCESS_KEY`(只报 vendor,不报值)→ `info`(有无都不算失败)。
4. **models 目录**:`store.models_root()` 路径;存在?**可写?**(探针:目录存在则 `os.access(root, os.W_OK)`,否则测父目录可写);已装模型数/总体积。可写 → `ok`;**不可写 → `fail`**(唯一会让退出码非零的项)。
5. **配置**:`config.path()`、default-engine、models-root 设置 → `ok`/`info`。

**网络检查(仅 `--net`)**:
- 探 sherpa 下载源主机(GitHub release base)、一个云端 host 可达否。经 `_probe(url) -> bool`(短超时 HEAD/GET,便于测试 monkeypatch)。可达 `ok`、不可达 `info`(**不 fail**)。

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
| `asrkit/doctor.py` | **新增**:`Check` + `diagnose(net)` + `_probe(url)` |
| `asrkit/cli.py` | `doctor` 子命令 + 渲染 + 退出码 |
| `tests/test_doctor.py` | **新增** |
| `docs/usage.md` / `CHANGELOG.md` | 用法 + `[Unreleased]` |

---

## 6. 测试(离线为主,网络 mock)

- **`diagnose()` 离线**:返回项含 asrkit/python 版本、每个引擎、keys、models-dir、config;类型为 `Check`(name/status/detail)。
- **密钥不泄露**:`monkeypatch` config 存一个 vendor 密钥(`ASRKIT_CONFIG` 指临时文件),断言输出**含 vendor 名、不含密钥明文**。
- **models 目录不可写 → fail**:临时目录 `chmod 0o500` 设 `ASRKIT_MODELS_ROOT`,断言有 `status=="fail"` 的 models-dir 项;`os.geteuid()==0` 时 `pytest.skip`(root 绕过权限)。
- **cli 退出码**:全 ok → `cli.main(["doctor"])` 返回 0;不可写目录 → 非零。
- **`--net`**:`monkeypatch doctor._probe` 返回 False/True(不打真网),断言含 net 项、且 net 不可达时**仍退 0**(info 不 fail)。
- **回归**:不影响其它命令。

---

## 7. 明确不做(YAGNI)

自动修复、逐云端厂商探活、深度网络诊断、doctor 里跑推理、检查 pip 包冲突/版本兼容。

---

## 8. 风险与兼容

- **纯只读诊断 + CLI 层**,回归面极小;不写文件(`os.access` 探可写,不留副作用)。
- 退出码保守:仅目录不可写才非零 —— 缺引擎/密钥/网络是常态信息,不误报失败。
- `--net` 探针短超时且 `info` 语义,不因网络抖动污染退出码。
