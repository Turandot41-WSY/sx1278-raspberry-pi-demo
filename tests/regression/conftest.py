"""Shared beginner-readable fixtures for host-runner tests."""

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_endpoints import EvidenceSpy


@pytest.fixture
def golden_frame() -> bytes:
    """Return the frozen valid 64-byte CCSDS golden transfer frame.

    Direct call tree (static source order):
        golden_frame
        `-- bytes.fromhex
    """
    return bytes.fromhex(
        "2780123418000127d23400310001e240003e8fa0ffedb08000"
        "50df20ffed29790023caceffcb40eb000f1206ff986878009714"
        "b2020712341234b79134127822"
    )


@pytest.fixture
def fake_clock() -> FakeClock:
    """Return a new manually controlled monotonic and UTC clock.

    Direct call tree (static source order):
        fake_clock
        `-- FakeClock
    """
    return FakeClock()


@pytest.fixture
def evidence_spy() -> EvidenceSpy:
    """Return a new in-memory exact-wire evidence collector.

    Direct call tree (static source order):
        evidence_spy
        `-- EvidenceSpy
    """
    return EvidenceSpy()
