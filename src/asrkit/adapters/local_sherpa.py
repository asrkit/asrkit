"""通用端侧转接头：一个 adapter 吃下所有 sherpa-onnx 架构。

按 meta.config_type 分派到对应的 sherpa-onnx 构造器——逻辑移植自
asr_bench/desktop_bench/scripts/worker.py 的 build()/decode_*()。

模型目录解析优先级：config["model_dir"] > $ASRKIT_MODELS_ROOT/<folder> > ~/.asrkit/models/<folder>
其中 <folder> = 模型 id 去掉 "local/" 前缀。
"""
from __future__ import annotations

import glob
import os
import time

from ..registry import register_protocol
from ..types import AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult


def _find(d: str, *patterns: str) -> str:
    """按模式找文件（优先 int8）。移植自 worker.py:_find。"""
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(d, pat)))
        if hits:
            int8 = [h for h in hits if "int8" in os.path.basename(h)]
            return (int8 or hits)[0]
    raise FileNotFoundError(f"{d} 内找不到 {patterns}")


def _find_tokenizer_dir(d: str) -> str:
    """qwen3-asr / funasr-nano 的 HF tokenizer 目录。移植自 worker.py。"""
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isdir(p) and (
            os.path.exists(os.path.join(p, "vocab.json"))
            or os.path.exists(os.path.join(p, "tokenizer.json"))
        ):
            return p
    raise FileNotFoundError(f"{d} 内找不到 tokenizer 目录")


def _build(config_type: str, d: str, threads: int, lang_hint: str,
           streaming: bool, use_itn: bool):
    """按 config_type 构建 recognizer。逐分支对齐 worker.py:build()。"""
    import sherpa_onnx as so
    j = lambda *p: os.path.join(d, *p)

    if streaming:
        if config_type == "onlineParaformer":
            return so.OnlineRecognizer.from_paraformer(
                tokens=j("tokens.txt"), encoder=j("encoder.onnx"),
                decoder=j("decoder.onnx"), num_threads=threads)
        return so.OnlineRecognizer.from_transducer(
            tokens=j("tokens.txt"), encoder=j("encoder.onnx"),
            decoder=j("decoder.onnx"), joiner=j("joiner.onnx"), num_threads=threads)

    if config_type == "paraformer":
        return so.OfflineRecognizer.from_paraformer(
            paraformer=j("model.onnx"), tokens=j("tokens.txt"), num_threads=threads)
    if config_type == "senseVoice":
        return so.OfflineRecognizer.from_sense_voice(
            model=_find(d, "model.onnx", "model.int8.onnx"), tokens=j("tokens.txt"),
            num_threads=threads, use_itn=use_itn)
    if config_type == "whisper":
        return so.OfflineRecognizer.from_whisper(
            encoder=j("encoder.onnx"), decoder=j("decoder.onnx"),
            tokens=j("tokens.txt"), language=lang_hint, num_threads=threads)
    if config_type == "moonshine":
        return so.OfflineRecognizer.from_moonshine(
            preprocessor=j("preprocess.onnx"), encoder=j("encode.onnx"),
            uncached_decoder=j("uncached_decode.onnx"),
            cached_decoder=j("cached_decode.onnx"),
            tokens=j("tokens.txt"), num_threads=threads)
    if config_type in ("offlineTransducer", "nemoTransducer"):
        mt = "nemo_transducer" if config_type == "nemoTransducer" else "transducer"
        return so.OfflineRecognizer.from_transducer(
            encoder=j("encoder.onnx"), decoder=j("decoder.onnx"),
            joiner=j("joiner.onnx"), tokens=j("tokens.txt"),
            num_threads=threads, model_type=mt)
    if config_type == "telespeechCtc":
        return so.OfflineRecognizer.from_telespeech_ctc(
            model=j("model.onnx"), tokens=j("tokens.txt"), num_threads=threads)
    if config_type == "fireRedAsrCtc":
        return so.OfflineRecognizer.from_fire_red_asr_ctc(
            model=j("model.onnx"), tokens=j("tokens.txt"), num_threads=threads)
    if config_type == "fireRedAed":
        return so.OfflineRecognizer.from_fire_red_asr(
            encoder=_find(d, "encoder.onnx", "*encoder*.onnx"),
            decoder=_find(d, "decoder.onnx", "*decoder*.onnx"),
            tokens=_find(d, "tokens.txt", "*tokens*.txt"), num_threads=threads)
    if config_type == "qwen3Asr":
        return so.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=_find(d, "*conv*frontend*.onnx", "*frontend*.onnx"),
            encoder=_find(d, "*encoder*.onnx"), decoder=_find(d, "*decoder*.onnx"),
            tokenizer=_find_tokenizer_dir(d), num_threads=threads)
    if config_type == "funasrNano":
        return so.OfflineRecognizer.from_funasr_nano(
            encoder_adaptor=_find(d, "*encoder*adaptor*.onnx", "*adaptor*.onnx"),
            llm=_find(d, "*llm*.onnx"),
            embedding=_find(d, "*embedding*.onnx", "*embed*.onnx"),
            tokenizer=_find_tokenizer_dir(d), num_threads=threads)
    if config_type == "moonshineV2":
        return so.OfflineRecognizer.from_moonshine_v2(
            encoder=_find(d, "*encoder*.onnx", "*encoder*.ort", "*encode*"),
            decoder=_find(d, "*decoder*.onnx", "*decoder*.ort", "*decode*"),
            tokens=_find(d, "tokens.txt", "*tokens*.txt"), num_threads=threads)
    if config_type == "omnilingualCtc":
        return so.OfflineRecognizer.from_omnilingual_asr_ctc(
            model=_find(d, "model.int8.onnx", "model.onnx", "*.onnx"),
            tokens=_find(d, "tokens.txt", "*tokens*.txt"), num_threads=threads)
    if config_type == "dolphin":
        return so.OfflineRecognizer.from_dolphin_ctc(
            model=j("model.onnx"), tokens=j("tokens.txt"), num_threads=threads)
    raise ValueError(f"未知 config_type: {config_type}")


def _decode_offline(rec, samples, sr):
    st = rec.create_stream()
    st.accept_waveform(sr, samples)
    rec.decode_stream(st)
    return st.result


def _decode_online(rec, samples, sr):
    import numpy as np
    st = rec.create_stream()
    st.accept_waveform(sr, samples)
    st.accept_waveform(sr, np.zeros(sr // 2, dtype=np.float32))  # 尾部静音
    st.input_finished()
    while rec.is_ready(st):
        rec.decode_stream(st)
    return rec.get_result(st)


@register_protocol("sherpa-onnx")
class SherpaLocal(BaseAdapter):
    def __init__(self, meta, config=None):
        super().__init__(meta, config)
        self._rec = None

    def _model_dir(self) -> str:
        d = self.config.get("model_dir")
        if d:
            return d
        folder = self.meta.id.split("/", 1)[-1]
        root = (self.config.get("models_root")
                or os.environ.get("ASRKIT_MODELS_ROOT")
                or os.path.expanduser("~/.asrkit/models"))
        return os.path.join(root, folder)

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        streaming = "streaming" in self.meta.modes
        try:
            t0 = time.perf_counter()
            if self._rec is None:
                self._rec = _build(
                    self.meta.config_type, self._model_dir(), 4,
                    opts.lang_hint or "", streaming, opts.enable_itn)
            load_ms = int((time.perf_counter() - t0) * 1000)

            t1 = time.perf_counter()
            r = (_decode_online if streaming else _decode_offline)(
                self._rec, audio.samples, audio.sample_rate)
            decode_ms = int((time.perf_counter() - t1) * 1000)

            text = r if isinstance(r, str) else getattr(r, "text", str(r))
            lang = getattr(r, "lang", "") or None
            dur = audio.duration_s or (len(audio.samples) / audio.sample_rate)
            return TranscribeResult(
                text=(text or "").strip(),
                lang=lang,
                latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms,
                         "rtf": round((decode_ms / 1000) / dur, 4) if dur else None},
            )
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")
