"""Argument parser construction for the asrkit CLI."""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    from .. import __version__
    from . import config, diagnostics, engines, models, stream, transcribe

    p = argparse.ArgumentParser(
        prog="asrkit",
        description="One interface to run and compare any speech-to-text model — local & cloud.",
    )
    p.add_argument("-V", "--version", action="version", version=f"asrkit {__version__}")
    sub = p.add_subparsers(dest="cmd")

    models.add_parsers(sub)
    engines.add_parsers(sub)
    config.add_parsers(sub)
    models.add_model_parser(sub)
    diagnostics.add_parsers(sub)
    transcribe.add_parsers(sub)
    stream.add_parsers(sub)
    return p
