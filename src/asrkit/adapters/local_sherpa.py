"""通用端侧转接头：一个 adapter 吃下所有 sherpa-onnx 架构。

按 meta.config_type 分派到对应 sherpa-onnx 构造器；文件用 glob 查找（优先按精度 tag），
因此对"已规范命名的旧模型"和"新 pull 下来保留原名的模型"都通用。
逻辑源自 asr_bench/desktop_bench/scripts/worker.py。
"""
from __future__ import annotations

import glob
import importlib.util
import os
import time

from .. import store
from ..audio import AudioFormatError, load_samples
from ..registry import register_protocol
from ..types import AudioInput, BaseAdapter, TranscribeOptions, TranscribeResult

# sherpa-onnx 是可选引擎（不在基础安装内）；含端侧解码所需的音频 io。
_INSTALL_HINT = 'engine \'sherpa-onnx\' not installed. Run: pip install "asrkit[local]"'


def _available() -> bool:
    return all(importlib.util.find_spec(m) is not None
               for m in ("sherpa_onnx", "numpy", "soundfile", "soxr"))


def _find(d: str, prefer: str, *patterns: str) -> str:
    """按模式找文件，按精度偏好挑：prefer=fp32 取非 int8，否则优先 int8。"""
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(d, pat)))
        if not hits:
            continue
        int8 = [h for h in hits if "int8" in os.path.basename(h).lower()]
        non = [h for h in hits if "int8" not in os.path.basename(h).lower()]
        if prefer == "fp32":
            return (non or hits)[0]
        return (int8 or hits)[0]
    raise FileNotFoundError(f"none of {patterns} found in {d}")


def _find_tokenizer_dir(d: str) -> str:
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isdir(p) and (
            os.path.exists(os.path.join(p, "vocab.json"))
            or os.path.exists(os.path.join(p, "tokenizer.json"))
        ):
            return p
    raise FileNotFoundError(f"no tokenizer dir found in {d}")


def _build(ct: str, d: str, threads: int, lang_hint: str, streaming: bool,
           use_itn: bool, prefer: str):
    import sherpa_onnx as so
    # 按需查找 tokens.txt（qwen3/funasr-nano 用 tokenizer 目录，无 tokens.txt，不能提前强求）
    def _tok():
        return _find(d, prefer, "tokens*.txt", "*tokens.txt", "*tokens*.txt")

    if streaming:
        if ct == "onlineParaformer":
            return so.OnlineRecognizer.from_paraformer(
                tokens=_tok(), encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
                decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"), num_threads=threads)
        return so.OnlineRecognizer.from_transducer(
            tokens=_tok(), encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
            decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"),
            joiner=_find(d, prefer, "joiner*.onnx", "*joiner*.onnx"), num_threads=threads)

    if ct == "paraformer":
        return so.OfflineRecognizer.from_paraformer(
            paraformer=_find(d, prefer, "model*.onnx", "*.onnx"), tokens=_tok(), num_threads=threads)
    if ct == "senseVoice":
        return so.OfflineRecognizer.from_sense_voice(
            model=_find(d, prefer, "model*.onnx", "*.onnx"), tokens=_tok(),
            num_threads=threads, use_itn=use_itn)
    if ct == "whisper":
        return so.OfflineRecognizer.from_whisper(
            encoder=_find(d, prefer, "*encoder*.onnx"), decoder=_find(d, prefer, "*decoder*.onnx"),
            tokens=_tok(), language=lang_hint, num_threads=threads)
    if ct == "moonshine":
        return so.OfflineRecognizer.from_moonshine(
            preprocessor=_find(d, prefer, "preprocess*.onnx", "*preprocess*.onnx"),
            encoder=_find(d, prefer, "encode*.onnx"),
            uncached_decoder=_find(d, prefer, "uncached_decode*.onnx"),
            cached_decoder=_find(d, prefer, "cached_decode*.onnx"),
            tokens=_tok(), num_threads=threads)
    if ct in ("offlineTransducer", "nemoTransducer"):
        mt = "nemo_transducer" if ct == "nemoTransducer" else "transducer"
        return so.OfflineRecognizer.from_transducer(
            encoder=_find(d, prefer, "encoder*.onnx", "*encoder*.onnx"),
            decoder=_find(d, prefer, "decoder*.onnx", "*decoder*.onnx"),
            joiner=_find(d, prefer, "joiner*.onnx", "*joiner*.onnx"),
            tokens=_tok(), num_threads=threads, model_type=mt)
    if ct == "telespeechCtc":
        return so.OfflineRecognizer.from_telespeech_ctc(
            model=_find(d, prefer, "model*.onnx", "*.onnx"), tokens=_tok(), num_threads=threads)
    if ct == "fireRedAsrCtc":
        return so.OfflineRecognizer.from_fire_red_asr_ctc(
            model=_find(d, prefer, "model*.onnx", "*.onnx"), tokens=_tok(), num_threads=threads)
    if ct == "fireRedAed":
        return so.OfflineRecognizer.from_fire_red_asr(
            encoder=_find(d, prefer, "*encoder*.onnx"), decoder=_find(d, prefer, "*decoder*.onnx"),
            tokens=_tok(), num_threads=threads)
    if ct == "qwen3Asr":
        return so.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=_find(d, prefer, "*conv*frontend*.onnx", "*frontend*.onnx"),
            encoder=_find(d, prefer, "*encoder*.onnx"), decoder=_find(d, prefer, "*decoder*.onnx"),
            tokenizer=_find_tokenizer_dir(d), num_threads=threads)
    if ct == "funasrNano":
        return so.OfflineRecognizer.from_funasr_nano(
            encoder_adaptor=_find(d, prefer, "*encoder*adaptor*.onnx", "*adaptor*.onnx"),
            llm=_find(d, prefer, "*llm*.onnx"),
            embedding=_find(d, prefer, "*embedding*.onnx", "*embed*.onnx"),
            tokenizer=_find_tokenizer_dir(d), num_threads=threads)
    if ct == "moonshineV2":
        return so.OfflineRecognizer.from_moonshine_v2(
            encoder=_find(d, prefer, "*encoder*.onnx", "*encoder*.ort", "*encode*"),
            decoder=_find(d, prefer, "*decoder*.onnx", "*decoder*.ort", "*decode*"),
            tokens=_tok(), num_threads=threads)
    if ct == "omnilingualCtc":
        return so.OfflineRecognizer.from_omnilingual_asr_ctc(
            model=_find(d, prefer, "model*.onnx", "*.onnx"), tokens=_tok(), num_threads=threads)
    if ct == "dolphin":
        return so.OfflineRecognizer.from_dolphin_ctc(
            model=_find(d, prefer, "model*.onnx", "*.onnx"), tokens=_tok(), num_threads=threads)
    raise ValueError(f"unknown config_type: {ct}")


def _decode_offline(rec, samples, sr):
    st = rec.create_stream()
    st.accept_waveform(sr, samples)
    rec.decode_stream(st)
    return st.result


def _decode_online(rec, samples, sr):
    import numpy as np
    st = rec.create_stream()
    st.accept_waveform(sr, samples)
    st.accept_waveform(sr, np.zeros(sr // 2, dtype=np.float32))
    st.input_finished()
    while rec.is_ready(st):
        rec.decode_stream(st)
    return rec.get_result(st)


def _vad_segments(samples, sr, vad_model):
    """opt-in 长音频分段：silero-VAD 按停顿切段。移植自 worker.py:vad_segments。"""
    import numpy as np
    import sherpa_onnx as so
    cfg = so.VadModelConfig()
    cfg.silero_vad.model = vad_model
    cfg.silero_vad.min_silence_duration = 0.5
    cfg.silero_vad.max_speech_duration = 20.0
    cfg.sample_rate = sr
    vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=180)
    win = 512
    for i in range(0, len(samples) - win + 1, win):
        vad.accept_waveform(samples[i:i + win])
    if hasattr(vad, "flush"):
        vad.flush()
    segs = []
    while not vad.empty():
        segs.append(np.ascontiguousarray(vad.front.samples, dtype=np.float32))
        vad.pop()
    return segs or [samples]


@register_protocol("sherpa-onnx")
class SherpaLocal(BaseAdapter):
    def __init__(self, meta, config=None):
        super().__init__(meta, config)
        self._rec = None

    def is_installed(self):
        return store.is_installed(self.meta, self.config)

    def install(self, log=print, url=None):
        return store.pull(self.meta, self.config, log=log, url=url)

    def transcribe(self, audio: AudioInput, opts: TranscribeOptions) -> TranscribeResult:
        if not _available():
            return TranscribeResult(text="", error=_INSTALL_HINT)
        streaming = "streaming" in self.meta.modes
        prefer = self.meta.tag or "int8"
        try:
            d = store.model_dir(self.meta, self.config)
            if not os.path.isdir(d):
                return TranscribeResult(
                    text="", error=f"model not installed: {self.meta.id}. Run `asrkit pull {self.meta.id}` first.")

            # 解码 + 格式守卫（内核零处理，解码在此；convert=False 时不符即诚实报错）
            try:
                samples, sr = load_samples(audio.original_path, 16000, 1, convert=opts.convert)
            except AudioFormatError as e:
                return TranscribeResult(text="", error=str(e))

            dur = len(samples) / sr if sr else 0.0
            warnings = []
            win = self.meta.capabilities.get("max_input_duration_s")

            t0 = time.perf_counter()
            if self._rec is None:
                self._rec = _build(self.meta.config_type, d, 4,
                                   opts.lang_hint or "", streaming, opts.enable_itn, prefer)
            load_ms = int((time.perf_counter() - t0) * 1000)

            t1 = time.perf_counter()
            if streaming:
                r = _decode_online(self._rec, samples, sr)
                text = r if isinstance(r, str) else getattr(r, "text", str(r))
                lang = getattr(r, "lang", "") or None
            elif opts.segment and win and dur > win:
                # opt-in 长音频分段（需 VAD 模型）
                vad_model = self.config.get("vad_model") or os.environ.get("ASRKIT_VAD_MODEL")
                if not vad_model or not os.path.exists(vad_model):
                    return TranscribeResult(
                        text="", error="--segment needs a VAD model: set ASRKIT_VAD_MODEL "
                        "or config['vad_model'] to silero_vad.onnx.")
                parts = []
                for seg in _vad_segments(samples, sr, vad_model):
                    rr = _decode_offline(self._rec, seg, sr)
                    parts.append((rr if isinstance(rr, str) else getattr(rr, "text", "")).strip())
                text = " ".join(p for p in parts if p)
                lang = None
            else:
                r = _decode_offline(self._rec, samples, sr)
                text = r if isinstance(r, str) else getattr(r, "text", str(r))
                lang = getattr(r, "lang", "") or None
                if win and dur > win:
                    warnings.append(
                        f"audio is {dur:.0f}s but this model's window is {win}s; "
                        f"only the first {win}s may be recognized. "
                        f"Use --segment / opts.segment=True for the full audio.")
            decode_ms = int((time.perf_counter() - t1) * 1000)

            return TranscribeResult(
                text=(text or "").strip(), lang=lang, latency_ms=load_ms + decode_ms,
                metrics={"load_ms": load_ms, "decode_ms": decode_ms,
                         "duration_s": round(dur, 3) if dur else None,
                         "rtf": round((decode_ms / 1000) / dur, 4) if dur else None},
                warnings=warnings or None)
        except Exception as e:
            return TranscribeResult(text="", error=f"{type(e).__name__}: {e}")
