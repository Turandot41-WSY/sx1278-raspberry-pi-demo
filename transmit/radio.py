"""Transmit saved frames through the production Nano endpoint protocol.

Function call tree:
load_saved_frames() -> verify input identity and select unchanged frame bytes
transmit_frame() -> LOAD_TX -> START_TX -> matching TX_DONE
EndpointTransport performs framing, CRC, sequence checks and serial evidence.
The endpoint firmware owns SPI, FIFO loading and the radio interrupt state machine.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path

from firmware.host import serial_protocol as protocol
from firmware.host.serial_transport import EndpointTransport


@dataclass(frozen=True)
class SavedFrames:
    """Hold the exact saved input and its selected zero-based frame range."""

    source: Path
    sha256: str
    data: bytes
    start: int
    count: int

    def frame(self, index: int) -> bytes:
        """Return one unchanged 64-byte frame within the selected range.

        Processing flow:
            Validate selected index -> calculate byte offset -> return saved slice.

        Direct call tree (static source order):
            frame
            `-- ValueError
        """
        if index < self.start or index >= self.start + self.count:
            raise ValueError("frame index is outside the selected range")
        offset = index * 64
        end_offset = offset + 64
        frame_bytes = self.data[offset:end_offset]
        return frame_bytes


def load_saved_frames(path: Path, expected_sha256: str, start: int, count: str) -> SavedFrames:
    """Verify saved bytes and select a frame range before opening hardware.

    Processing flow:
        Read exact source -> verify SHA-256 and frame alignment -> validate range
        -> immutable input snapshot used for every serial payload.

    Direct call tree (static source order):
        load_saved_frames
        +-- path.resolve
        +-- source.read_bytes
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- ValueError
        +-- len
        +-- int
        `-- SavedFrames
    """
    source = path.resolve()
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError("saved frame SHA-256 differs from the configured input")
    if not data or len(data) % 64:
        raise ValueError("saved input must contain complete 64-byte frames")
    requested = len(data) // 64 - start
    if count != "all":
        requested = int(count)
    if start < 0 or requested <= 0 or start + requested > len(data) // 64:
        raise ValueError("selected frame range is outside the saved input")
    if start + requested > 0x100000000:
        raise ValueError("frame indices exceed the protocol's unsigned 32-bit range")
    return SavedFrames(source, digest, data, start, requested)


def transmit_frame(transport: EndpointTransport, frame: bytes, frame_index: int,
                   run_token: int, reg_frf_word: int, timeout_ms: int = 2000) -> None:
    """Transmit one saved frame and require its matching firmware TX_DONE event.

    TX_STARTED acknowledges one issued request; it is not a measured RF start
    time. Only the matching TX_DONE terminal completes this operation.

    Processing flow:
        Unchanged frame -> LOAD_TX -> verify attempt and FRF readback -> START_TX
        -> verify TX_STARTED -> await matching TX_DONE; any failure stops without retry.

    Direct call tree (static source order):
        transmit_frame
        +-- protocol.pack_load_tx
        +-- transport.command
        +-- protocol.unpack_tx_ready
        +-- ValueError
        +-- protocol.pack_start_tx
        +-- protocol.unpack_tx_started
        +-- transport.wait_event_receipt
        `-- protocol.unpack_tx_done
    """
    payload = protocol.pack_load_tx(run_token, frame_index, reg_frf_word, frame)
    reply = transport.command(protocol.MessageType.LOAD_TX, payload,
                              {protocol.MessageType.TX_READY}, timeout_ms)
    ready = protocol.unpack_tx_ready(reply.payload)
    if (ready.run_token, ready.attempt_index, ready.reg_frf_readback) != (
            run_token, frame_index, reg_frf_word):
        raise ValueError("TX_READY context or frequency readback differs")
    start_payload = protocol.pack_start_tx(run_token, frame_index)
    reply = transport.command(
        protocol.MessageType.START_TX,
        start_payload,
        {protocol.MessageType.TX_STARTED},
        timeout_ms,
    )
    started = protocol.unpack_tx_started(reply.payload)
    if (started.run_token, started.attempt_index) != (run_token, frame_index):
        raise ValueError("TX_STARTED context differs")
    receipt = transport.wait_event_receipt(timeout_ms)
    if receipt.message.message_type != protocol.MessageType.TX_DONE:
        raise ValueError("firmware did not report TX_DONE")
    done = protocol.unpack_tx_done(receipt.message.payload)
    if (done.run_token, done.attempt_index) != (run_token, frame_index):
        raise ValueError("TX_DONE context differs")
