"""
codec.errors — the exception hierarchy raised by the codec layer.

WHY A DEDICATED MODULE
    Callers (the UI, the workspace, tests) need to distinguish "this file is not
    a valid .esx" from "this bank is internally incoherent" from "our own writer
    produced bytes that do not read back". Separate exception types let each be
    caught and reported differently without string-matching messages.
"""

from __future__ import annotations


class CodecError(Exception):
    """Base class for every error originating in the codec layer."""


class FormatError(CodecError):
    """The bytes are not a structurally valid .esx image.

    Raised by the reader when a magic number, region size, or file length is
    inconsistent with the format specification (TDD §02) — i.e. before any
    coherence checking. A FormatError means "cannot parse", not "parsed but
    self-contradictory" (that is the validator's job, see codec.validator).
    """


class RoundTripError(CodecError):
    """The writer produced bytes that do not read back to the same model.

    Raised by the write-side safety path (TDD §4.5 step 2) when re-reading the
    serialized bytes yields a model that differs from what was intended. It
    signals a codec bug and MUST abort the write before anything is replaced.
    """
