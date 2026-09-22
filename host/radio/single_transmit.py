"""Transmit saved frames through the production Nano endpoint protocol.

Function call tree:
load_saved_frames() -> verify input identity and select unchanged frame bytes
configure_transmitter() -> HELLO -> RESET -> APPLY_PROFILE -> SET_PA
transmit_frame() -> LOAD_TX -> START_TX -> matching TX_DONE
EndpointTransport performs framing, CRC, sequence checks and serial evidence.
The endpoint firmware owns SPI, FIFO loading and the radio interrupt state machine.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from host.radio.profile_truth import ProfileTruth
from host.radio import serial_protocol as protocol
from host.radio.serial_transport import EndpointTransport


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


class TransmitEvidence:
    """Persist run events and exact production protocol wires as JSON lines."""

    def __init__(self, path: Path):
        """Open a new event log and initialize its zero-based record index.

        Uses exclusive creation so an earlier experiment log cannot be overwritten.

        Direct call tree (static source order):
            __init__
            `-- path.open
        """
        self.file = path.open("x", encoding="utf-8")
        self.index = 0

    def record(self, event: str, **fields) -> int:
        """Append and sync one event before allowing the experiment to advance.

        Direct call tree (static source order):
            record
            +-- row.update
            +-- self.file.write
            +-- json.dumps
            +-- self.file.flush
            +-- os.fsync
            `-- self.file.fileno
        """
        index = self.index
        row = {"index": index, "event": event}
        row.update(fields)
        self.file.write(json.dumps(row, sort_keys=True) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        self.index += 1
        return index

    def append_wire(self, monotonic_ns, utc_ns, endpoint_id, direction, wire_bytes):
        """Record the complete wire bytes accepted by EndpointTransport.

        Direct call tree (static source order):
            append_wire
            +-- self.record
            `-- wire_bytes.hex
        """
        return self.record("wire", monotonic_ns=monotonic_ns, utc_ns=utc_ns,
                           endpoint_id=endpoint_id, direction=direction,
                           wire_hex=wire_bytes.hex())

    def close(self):
        """Close the run evidence file.

        Direct call tree (static source order):
            close
            `-- self.file.close
        """
        self.file.close()


def _check_registers(observed, expected):
    """Compare the ordered register report with the selected configuration.

    Processing flow:
        Require matching count -> compare addresses and masked values -> accept.

    Direct call tree (static source order):
        _check_registers
        +-- len
        +-- ValueError
        `-- range
    """
    if len(observed) != len(expected):
        raise ValueError("CONFIG_REPORT register count differs")
    for index in range(len(expected)):
        address, mask, value = expected[index]
        register = observed[index]
        if register.address != address or register.value & mask != value:
            raise ValueError(f"CONFIG_REPORT readback differs at register {address:#04x}")


def configure_transmitter(transport: EndpointTransport, truth: ProfileTruth,
                          manifest: dict, profile_id: str, pa_dbm: int,
                          timeout_ms: int = 2000) -> None:
    """Verify the flashed identity and configure the production radio driver.

    Processing flow:
        Select shared profile/PA -> verify HELLO hashes -> reset to standby
        -> apply profile and compare masked registers -> apply PA and readbacks.

    Direct call tree (static source order):
        configure_transmitter
        +-- ValueError
        +-- protocol.ProfileCode
        +-- protocol.pack_hello
        +-- transport.command
        +-- protocol.unpack_hello_report
        +-- hello.firmware_hash.hex
        +-- hello.board_profile_hash.hex
        +-- hello.profile_table_hash.hex
        +-- protocol.pack_reset_to_standby
        +-- protocol.unpack_ack
        +-- protocol.pack_apply_profile
        +-- protocol.unpack_config_report
        +-- expected.append
        +-- _check_registers
        `-- protocol.pack_set_pa
    """
    profile = None
    pa = None
    for candidate in truth.profiles:
        if candidate.profile_id == profile_id:
            profile = candidate
    for candidate in truth.pa_settings:
        if candidate.pa_command_dbm == pa_dbm:
            pa = candidate
    if profile is None or pa is None:
        raise ValueError("profile or PA setting does not exist in config truth")
    profile_code = protocol.ProfileCode(profile.profile_code)
    hello_payload = protocol.pack_hello()
    message = transport.command(
        protocol.MessageType.HELLO,
        hello_payload,
        {protocol.MessageType.HELLO_REPORT},
        timeout_ms,
    )
    hello = protocol.unpack_hello_report(message.payload)
    if hello.endpoint_id != manifest["endpoint_id"] or hello.reg_version != 0x12:
        raise ValueError("Nano identity or SX1278 version differs")
    if hello.firmware_hash.hex() != manifest["firmware_sha256"]:
        raise ValueError("flashed firmware differs; upload the documented production build")
    if hello.board_profile_hash.hex() != manifest["board_sha256"]:
        raise ValueError("flashed board configuration differs")
    if hello.profile_table_hash.hex() != truth.profile_registers_sha256:
        raise ValueError("flashed profile table differs from config/profile_registers.csv")
    reset_payload = protocol.pack_reset_to_standby()
    message = transport.command(
        protocol.MessageType.RESET_TO_STANDBY,
        reset_payload,
        {protocol.MessageType.ACK},
        timeout_ms,
    )
    reset_acknowledgement = protocol.unpack_ack(message.payload)
    if reset_acknowledgement.related_type != protocol.MessageType.RESET_TO_STANDBY:
        raise ValueError("RESET acknowledgement differs")
    profile_payload = protocol.pack_apply_profile(profile_code, hello.profile_table_hash)
    message = transport.command(
        protocol.MessageType.APPLY_PROFILE,
        profile_payload,
        {protocol.MessageType.CONFIG_REPORT},
        timeout_ms,
    )
    report = protocol.unpack_config_report(message.payload)
    if report.related_type != protocol.MessageType.APPLY_PROFILE or report.profile_code != profile_code:
        raise ValueError("profile configuration response differs")
    expected = []
    for row in truth.register_rows:
        if row.profile_id == profile_id:
            expected.append((row.address, row.readback_mask, row.expected_readback))
    _check_registers(report.registers, expected)
    power_payload = protocol.pack_set_pa(pa_dbm, pa.reg_ocp)
    message = transport.command(
        protocol.MessageType.SET_PA,
        power_payload,
        {protocol.MessageType.CONFIG_REPORT},
        timeout_ms,
    )
    report = protocol.unpack_config_report(message.payload)
    if report.related_type != protocol.MessageType.SET_PA or report.profile_code != profile_code:
        raise ValueError("PA configuration response differs")
    if (report.pa_command_dbm, report.reg_pa_config, report.reg_pa_dac, report.reg_ocp) != (
            pa_dbm, pa.reg_pa_config, pa.reg_pa_dac, pa.reg_ocp):
        raise ValueError("PA configuration readback differs")
    # Use the shared PA table; the protocol reports these three registers in this order.
    _check_registers(report.registers, [(0x09, 255, pa.reg_pa_config),
                                      (0x4D, 255, pa.reg_pa_dac), (0x0B, 255, pa.reg_ocp)])


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
