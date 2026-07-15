"""只收集 ASRKit HTTP Sidecar 实际使用的 Uvicorn 运行模块。"""

hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
]
