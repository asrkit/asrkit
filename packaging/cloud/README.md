# asrkit-cloud 冻结构建

这里生成第一代自包含 `asrkit-cloud` 运行时。产物采用 PyInstaller `onedir`，携带 CPython 和全部云端/HTTP 依赖；目标机器无需安装 Python、pip 或 ASRKit。

## 本机构建

```bash
python packaging/cloud/bootstrap.py
```

`bootstrap.py` 默认在已忽略的 `build/asrkit-cloud-env/` 创建隔离 venv，安装 `cloud-build` extra，再调用实际构建器。这样开发机已经安装的 PIL、Torch、Rich 等包不会偶然进入运行时。已准备好干净环境的 CI 也可以直接执行 `python packaging/cloud/build.py`。

默认产物位于：

```text
dist/asrkit-cloud/
├── asrkit-cloud[.exe]
└── _internal/
```

构建器会自动执行 `smoke.py`。smoke 清除 `PYTHONPATH`、虚拟环境、动态库搜索路径和 ASRKit 环境变量，把冻结进程的 `PATH` 指向空目录，然后验证：

- `--version` 与 `--help`；
- embedded ready/shutdown NDJSON；
- 随机 loopback 端口；
- `/health`；
- Bearer 鉴权；
- cloud-only 的 10 个模型；
- multipart 转写主路由与未知模型错误；
- 父进程退出后的自动关停；
- stdout 不混入非协议文本、stderr 不泄漏 token。

可单独复验已有产物：

```bash
python packaging/cloud/smoke.py dist/asrkit-cloud/asrkit-cloud
```

## 边界

- `entrypoint.py` 只转发到 `asrkit.daemon.cli:main`，不复制运行逻辑。
- spec 显式收集动态加载的 cloud profile 与 Uvicorn 子模块。
- 自定义 Uvicorn hook 只保留 asyncio + h11 HTTP 栈，不携带 worker、WebSocket 和可选加速器。
- spec 排除本地 adapter、模型管理命令及其重依赖。
- `dist/`、`build/` 已由仓库忽略，二进制不进入源码提交。
- 当前脚本只建立可重复原型；签名、公证、SHA256、SBOM、第三方许可证清单和跨平台 CI 属于后续平台矩阵工作。
