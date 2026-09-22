"""Strict binary codec for the benchmark's USB serial control link."""

from __future__ import annotations

from typing import TypeVar


import struct
from dataclasses import dataclass, field
from enum import IntEnum

_EnumT = TypeVar("_EnumT", bound="IntEnum")


# Project choice: identify USB control packets with a magic value and version,
# bound memory use, and discard an incomplete fragment after 250 ms. This
# deadline applies between serial bytes; RF completion has its own timeout.
MAGIC = 0x5358
VERSION = 1
BAUD_RATE = 115_200
INTER_BYTE_TIMEOUT_MS = 250
MAX_PAYLOAD_LENGTH = 118
MAX_DECODED_LENGTH = 128
MAX_COBS_FRAGMENT_LENGTH = 129
MAX_WIRE_LENGTH = 130
_HEADER = struct.Struct(">HBBHH")
_CONTEXT = struct.Struct(">II")
_CRC_LENGTH = 2


# Project choice: stable numeric message, profile, state and error codes
# let Python and Nano exchange the same bytes across implementations.
class MessageType(IntEnum):
    """Identify every command, response, and event in protocol version 1."""

    HELLO = 0x01
    RESET_TO_STANDBY = 0x02
    APPLY_PROFILE = 0x10
    SET_PA = 0x11
    LOAD_TX = 0x20
    ARM_RX = 0x21
    START_TX = 0x22
    CANCEL_ATTEMPT = 0x23
    GET_ATTEMPT_STATUS = 0x24
    ACK = 0x80
    HELLO_REPORT = 0x81
    CONFIG_REPORT = 0x90
    TX_READY = 0xA0
    RX_ARMED = 0xA1
    TX_STARTED = 0xA2
    TX_DONE = 0xA3
    RX_PACKET = 0xA4
    RX_TIMEOUT = 0xA5
    ATTEMPT_STATUS = 0xA6
    ENDPOINT_ERROR = 0xE0


class ProfileCode(IntEnum):
    """Identify the six frozen SX1278 physical-layer profiles."""

    LORA = 0
    FSK = 1
    GFSK = 2
    MSK = 3
    GMSK = 4
    OOK = 5


class AttemptState(IntEnum):
    """Describe the endpoint state for one transmission attempt."""

    STANDBY = 0
    TX_LOADED = 1
    RX_ARMED = 2
    TX_STARTED = 3
    TX_DONE = 4
    RX_PACKET = 5
    RX_TIMEOUT = 6
    ERROR = 7


class ErrorCode(IntEnum):
    """Classify machine-readable protocol and endpoint failures."""

    BAD_COBS = 1
    BAD_MAGIC = 2
    BAD_VERSION = 3
    BAD_LENGTH = 4
    BAD_CRC = 5
    UNKNOWN_TYPE = 6
    BAD_STATE = 7
    CONTEXT_MISMATCH = 8
    FRAME_LENGTH = 9
    PROFILE = 10
    PA = 11
    REGISTER_READBACK = 12
    FRF_READBACK = 13
    DEVICE_RADIO_TIMEOUT = 14
    SERIAL_OVERFLOW = 15
    ENDPOINT_RESET = 16


HOST_COMMAND_TYPES = (
    MessageType.HELLO,
    MessageType.RESET_TO_STANDBY,
    MessageType.APPLY_PROFILE,
    MessageType.SET_PA,
    MessageType.LOAD_TX,
    MessageType.ARM_RX,
    MessageType.START_TX,
    MessageType.CANCEL_ATTEMPT,
    MessageType.GET_ATTEMPT_STATUS,
)

CONFIG_REPORT_RELATED_TYPES = (
    MessageType.APPLY_PROFILE,
    MessageType.SET_PA,
)


class ProtocolError(ValueError):
    """Carry one stable error code with a human-readable explanation."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: str | int | None = None,
    ) -> None:
        """Attach the protocol error code and diagnostic detail to an exception.

        Direct call tree (static source order):
            __init__
            +-- super
            `-- super(...).__init__
        """
        super().__init__(message)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Message:
    """Hold one validated protocol message and its optional encoded forms."""

    message_type: MessageType
    msg_seq: int
    payload: bytes
    decoded_bytes: bytes = field(default=b"", compare=False, repr=False)
    wire_bytes: bytes = field(default=b"", compare=False, repr=False)

    def __post_init__(self) -> None:
        """Reject message fields whose types or lengths violate the wire contract.

        Processing flow:
            Typed message fields -> sequence/payload checks -> encoded-size checks.

        Direct call tree (static source order):
            __post_init__
            +-- isinstance
            +-- TypeError
            +-- _require_uint
            +-- _require_bytes
            +-- len
            `-- ValueError
        """
        message_type_is_valid = isinstance(self.message_type, MessageType)
        if not message_type_is_valid:
            raise TypeError("message_type must be a MessageType")
        _require_uint("msg_seq", self.msg_seq, 16)
        _require_bytes("payload", self.payload)
        _require_bytes("decoded_bytes", self.decoded_bytes)
        _require_bytes("wire_bytes", self.wire_bytes)
        payload_is_too_large = len(self.payload) > MAX_PAYLOAD_LENGTH
        if payload_is_too_large:
            raise ValueError("payload must contain at most 118 bytes")
        decoded_bytes_are_present = len(self.decoded_bytes) > 0
        if decoded_bytes_are_present:
            decoded_bytes_are_too_large = len(self.decoded_bytes) > MAX_DECODED_LENGTH
            if decoded_bytes_are_too_large:
                raise ValueError("decoded_bytes must contain at most 128 bytes")
        wire_bytes_are_present = len(self.wire_bytes) > 0
        if wire_bytes_are_present:
            wire_bytes_are_too_large = len(self.wire_bytes) > MAX_WIRE_LENGTH
            if wire_bytes_are_too_large:
                raise ValueError("wire_bytes must contain at most 130 bytes")


# Each immutable view names the fields of one project USB message. Named
# attributes make payload inspection and validation explicit.
@dataclass(frozen=True)
class HelloPayload:
    """Represent the empty HELLO payload."""

    def __post_init__(self) -> None:
        """Confirm that HELLO has no typed payload fields.

        Direct call tree (static source order):
            __post_init__
            `-- [no direct function calls; local state/return only]
        """
        return None


@dataclass(frozen=True)
class ResetToStandbyPayload:
    """Represent the empty RESET_TO_STANDBY payload."""

    def __post_init__(self) -> None:
        """Confirm that RESET_TO_STANDBY has no typed payload fields.

        Direct call tree (static source order):
            __post_init__
            `-- [no direct function calls; local state/return only]
        """
        return None


@dataclass(frozen=True)
class ApplyProfilePayload:
    """Carry a profile code and the exact 32-byte profile-table hash."""

    profile_code: ProfileCode
    profile_table_hash: bytes

    def __post_init__(self) -> None:
        """Validate the profile enum and exact SHA-256 digest bytes.

        Direct call tree (static source order):
            __post_init__
            +-- _require_enum
            `-- _require_exact_bytes
        """
        _require_enum("profile_code", self.profile_code, ProfileCode)
        _require_exact_bytes("profile_table_hash", self.profile_table_hash, 32)


@dataclass(frozen=True)
class SetPaPayload:
    """Carry the requested PA output and the complete RegOcp byte."""

    pa_command_dbm: int
    reg_ocp: int

    def __post_init__(self) -> None:
        """Validate the signed PA command and complete RegOcp byte.

        Direct call tree (static source order):
            __post_init__
            +-- _require_int8
            `-- _require_uint
        """
        _require_int8("pa_command_dbm", self.pa_command_dbm)
        _require_uint("reg_ocp", self.reg_ocp, 8)


@dataclass(frozen=True)
class LoadTxPayload:
    """Carry one immutable frame and its absolute SX1278 FRF word."""

    run_token: int
    attempt_index: int
    reg_frf_word: int
    frame: bytes

    def __post_init__(self) -> None:
        """Validate one nonzero attempt context, FRF word, and 64-byte frame.

        Direct call tree (static source order):
            __post_init__
            +-- _require_context
            +-- _require_uint
            `-- _require_exact_bytes
        """
        _require_context(self.run_token, self.attempt_index)
        _require_uint("reg_frf_word", self.reg_frf_word, 24)
        _require_exact_bytes("frame", self.frame, 64)


@dataclass(frozen=True)
class ArmRxPayload:
    """Carry the receive attempt identity and receive-window duration."""

    run_token: int
    attempt_index: int
    rx_window_ms: int

    def __post_init__(self) -> None:
        """Validate one nonzero attempt context and uint16 receive window.

        Processing flow:
            ARM_RX fields -> validate the attempt identity -> require a uint16 receive window
            -> reject zero duration before admitting the payload.

        Direct call tree (static source order):
            __post_init__
            +-- _require_context
            +-- _require_uint
            `-- ValueError
        """
        _require_context(self.run_token, self.attempt_index)
        _require_uint("rx_window_ms", self.rx_window_ms, 16)
        if self.rx_window_ms == 0:
            raise ValueError("rx_window_ms must be positive")


@dataclass(frozen=True)
class StartTxPayload:
    """Carry the attempt identity for START_TX."""

    run_token: int
    attempt_index: int

    def __post_init__(self) -> None:
        """Validate the nonzero START_TX attempt context.

        Direct call tree (static source order):
            __post_init__
            `-- _require_context
        """
        _require_context(self.run_token, self.attempt_index)


@dataclass(frozen=True)
class CancelAttemptPayload:
    """Carry the attempt identity for CANCEL_ATTEMPT."""

    run_token: int
    attempt_index: int

    def __post_init__(self) -> None:
        """Validate the nonzero CANCEL_ATTEMPT context.

        Direct call tree (static source order):
            __post_init__
            `-- _require_context
        """
        _require_context(self.run_token, self.attempt_index)


@dataclass(frozen=True)
class GetAttemptStatusPayload:
    """Carry the attempt identity for GET_ATTEMPT_STATUS."""

    run_token: int
    attempt_index: int

    def __post_init__(self) -> None:
        """Validate the nonzero GET_ATTEMPT_STATUS context.

        Direct call tree (static source order):
            __post_init__
            `-- _require_context
        """
        _require_context(self.run_token, self.attempt_index)


@dataclass(frozen=True)
class AckPayload:
    """Acknowledge one related message with the version-1 zero status."""

    related_type: MessageType
    status: int

    def __post_init__(self) -> None:
        """Validate the related type and protocol-v1 zero status.

        Processing flow:
            ACK fields -> require a typed related host command
            -> validate the status byte -> require zero status for protocol version 1.

        Direct call tree (static source order):
            __post_init__
            +-- _require_enum
            +-- ValueError
            `-- _require_uint
        """
        _require_enum("related_type", self.related_type, MessageType)
        if self.related_type not in HOST_COMMAND_TYPES:
            raise ValueError("ACK related_type must be a host command")
        _require_uint("status", self.status, 8)
        status_is_not_zero = self.status != 0
        if status_is_not_zero:
            raise ValueError("ACK status must be zero in protocol version 1")


@dataclass(frozen=True)
class HelloReportPayload:
    """Report endpoint identity, state, radio version, and build hashes."""

    endpoint_id: int
    boot_count: int
    reg_version: int
    state: AttemptState
    firmware_hash: bytes
    profile_table_hash: bytes
    board_profile_hash: bytes

    def __post_init__(self) -> None:
        """Validate endpoint counters, state, and three exact SHA-256 digests.

        Direct call tree (static source order):
            __post_init__
            +-- _require_uint
            +-- _require_enum
            `-- _require_exact_bytes
        """
        _require_uint("endpoint_id", self.endpoint_id, 32)
        _require_uint("boot_count", self.boot_count, 32)
        _require_uint("reg_version", self.reg_version, 8)
        _require_enum("state", self.state, AttemptState)
        _require_exact_bytes("firmware_hash", self.firmware_hash, 32)
        _require_exact_bytes("profile_table_hash", self.profile_table_hash, 32)
        _require_exact_bytes("board_profile_hash", self.board_profile_hash, 32)


@dataclass(frozen=True)
class RegisterValue:
    """Represent one SX1278 address and read-back value pair."""

    address: int
    value: int

    def __post_init__(self) -> None:
        """Validate one SX1278 register address and read-back byte.

        Direct call tree (static source order):
            __post_init__
            `-- _require_uint
        """
        _require_uint("register address", self.address, 8)
        _require_uint("register value", self.value, 8)


@dataclass(frozen=True)
class ConfigReportPayload:
    """Report the applied profile, PA bytes, and register read-backs."""

    related_type: MessageType
    profile_code: ProfileCode
    pa_command_dbm: int
    reg_pa_config: int
    reg_pa_dac: int
    reg_ocp: int
    registers: tuple[RegisterValue, ...]

    def __post_init__(self) -> None:
        """Validate fixed configuration fields and at most 55 register values.

        Processing flow:
            Configuration report -> require APPLY_PROFILE or SET_PA as the related command
            -> validate profile, PA command and register bytes
            -> require at most 55 typed register values in an immutable tuple.

        Direct call tree (static source order):
            __post_init__
            +-- _require_enum
            +-- ValueError
            +-- _require_int8
            +-- _require_uint
            +-- isinstance
            +-- TypeError
            `-- len
        """
        _require_enum("related_type", self.related_type, MessageType)
        if self.related_type not in CONFIG_REPORT_RELATED_TYPES:
            raise ValueError("CONFIG_REPORT must relate to APPLY_PROFILE or SET_PA")
        _require_enum("profile_code", self.profile_code, ProfileCode)
        _require_int8("pa_command_dbm", self.pa_command_dbm)
        _require_uint("reg_pa_config", self.reg_pa_config, 8)
        _require_uint("reg_pa_dac", self.reg_pa_dac, 8)
        _require_uint("reg_ocp", self.reg_ocp, 8)
        registers_are_a_tuple = isinstance(self.registers, tuple)
        if not registers_are_a_tuple:
            raise TypeError("registers must be a tuple")
        register_count = len(self.registers)
        register_count_is_too_large = register_count > 55
        if register_count_is_too_large:
            raise ValueError("CONFIG_REPORT may contain at most 55 registers")
        for register in self.registers:
            register_is_typed = isinstance(register, RegisterValue)
            if not register_is_typed:
                raise TypeError("each register must be a RegisterValue")


@dataclass(frozen=True)
class TxReadyPayload:
    """Report that TX data is loaded with the requested FRF read-back."""

    run_token: int
    attempt_index: int
    reg_frf_readback: int

    def __post_init__(self) -> None:
        """Validate the TX_READY context and 24-bit FRF read-back.

        Direct call tree (static source order):
            __post_init__
            +-- _require_context
            `-- _require_uint
        """
        _require_context(self.run_token, self.attempt_index)
        _require_uint("reg_frf_readback", self.reg_frf_readback, 24)


@dataclass(frozen=True)
class RxArmedPayload:
    """Report the armed receive context, FRF read-back, and window."""

    run_token: int
    attempt_index: int
    reg_frf_readback: int
    rx_window_ms: int

    def __post_init__(self) -> None:
        """Validate the RX_ARMED context, FRF read-back, and receive window.

        Direct call tree (static source order):
            __post_init__
            +-- _require_context
            `-- _require_uint
        """
        _require_context(self.run_token, self.attempt_index)
        _require_uint("reg_frf_readback", self.reg_frf_readback, 24)
        _require_uint("rx_window_ms", self.rx_window_ms, 16)


@dataclass(frozen=True)
class TxStartedPayload:
    """Report the attempt identity whose transmitter entered TX."""

    run_token: int
    attempt_index: int

    def __post_init__(self) -> None:
        """Validate the nonzero TX_STARTED attempt context.

        Direct call tree (static source order):
            __post_init__
            `-- _require_context
        """
        _require_context(self.run_token, self.attempt_index)


@dataclass(frozen=True)
class TxDonePayload:
    """Report the attempt identity whose packet transmission completed."""

    run_token: int
    attempt_index: int

    def __post_init__(self) -> None:
        """Validate the nonzero TX_DONE attempt context.

        Direct call tree (static source order):
            __post_init__
            `-- _require_context
        """
        _require_context(self.run_token, self.attempt_index)


@dataclass(frozen=True)
class RxPacketPayload:
    """Carry observed radio metadata and the FIFO bytes retained within 64 bytes.

    Project choice: received_length is the actual radio length, from zero to 255.
    Lengths above 64 carry an empty packet because the FIFO body was not read.
    Lengths through 64 carry exactly that many bytes. CRC remains an independent
    observation so the classifier can apply PHY CRC before wireless length.
    """

    run_token: int
    attempt_index: int
    phy_crc_ok: int
    received_length: int
    metrics_flags: int
    rssi_raw: int
    snr_raw: int
    packet: bytes

    def __post_init__(self) -> None:
        """Validate actual radio length, retained packet bytes, CRC and metrics.

        Inputs: Dataclass fields describing one keyed radio observation.
        Returns: None; invalid metadata or retained bytes raise an exception.

        Processing flow:
            Context and IRQ fields -> actual length -> body retention rule -> metrics.

        Direct call tree (static source order):
            __post_init__
            +-- _require_context
            +-- _require_uint
            +-- ValueError
            +-- _require_int8
            +-- _require_max_bytes
            `-- len
        """
        _require_context(self.run_token, self.attempt_index)
        _require_uint("phy_crc_ok", self.phy_crc_ok, 8)
        crc_status_is_zero = self.phy_crc_ok == 0
        crc_status_is_one = self.phy_crc_ok == 1
        crc_status_is_invalid = True
        if crc_status_is_zero:
            crc_status_is_invalid = False
        if crc_status_is_one:
            crc_status_is_invalid = False
        if crc_status_is_invalid:
            raise ValueError("phy_crc_ok must be 0 or 1")
        _require_uint("received_length", self.received_length, 8)
        _require_uint("metrics_flags", self.metrics_flags, 8)
        unsupported_flag_bits = self.metrics_flags & 0xFC
        flags_are_invalid = unsupported_flag_bits != 0
        if flags_are_invalid:
            raise ValueError("metrics_flags may only use bits 0 and 1")
        _require_uint("rssi_raw", self.rssi_raw, 8)
        _require_int8("snr_raw", self.snr_raw)
        _require_max_bytes("packet", self.packet, 64)
        packet_length = len(self.packet)
        if self.received_length > 64:
            if packet_length != 0:
                raise ValueError("packet must be empty when received_length exceeds 64")
        else:
            if self.received_length != packet_length:
                raise ValueError("received_length must equal packet length")
        rssi_flag = self.metrics_flags & 0x01
        rssi_is_absent = rssi_flag == 0
        if rssi_is_absent:
            rssi_value_is_not_zero = self.rssi_raw != 0
            if rssi_value_is_not_zero:
                raise ValueError("rssi_raw must be zero when RSSI flag is clear")
        snr_flag = self.metrics_flags & 0x02
        snr_is_absent = snr_flag == 0
        if snr_is_absent:
            snr_value_is_not_zero = self.snr_raw != 0
            if snr_value_is_not_zero:
                raise ValueError("snr_raw must be zero when SNR flag is clear")


@dataclass(frozen=True)
class RxTimeoutPayload:
    """Report the attempt identity whose receive window expired."""

    run_token: int
    attempt_index: int

    def __post_init__(self) -> None:
        """Validate the nonzero RX_TIMEOUT attempt context.

        Direct call tree (static source order):
            __post_init__
            `-- _require_context
        """
        _require_context(self.run_token, self.attempt_index)


@dataclass(frozen=True)
class AttemptStatusPayload:
    """Report one attempt state and its last known error code."""

    run_token: int
    attempt_index: int
    state: AttemptState
    last_error_code: int

    def __post_init__(self) -> None:
        """Validate attempt state and the zero-or-known last error value.

        Processing flow:
            Attempt status -> validate attempt identity and typed state
            -> validate the width of the last error field -> require zero or a known error code.

        Direct call tree (static source order):
            __post_init__
            +-- _require_context
            +-- _require_enum
            +-- _require_uint
            `-- ValueError
        """
        _require_context(self.run_token, self.attempt_index)
        _require_enum("state", self.state, AttemptState)
        _require_uint("last_error_code", self.last_error_code, 16)
        last_error_is_unknown = self.last_error_code > ErrorCode.ENDPOINT_RESET.value
        if last_error_is_unknown:
            raise ValueError("last_error_code must be zero or a known ErrorCode")


@dataclass(frozen=True)
class EndpointErrorPayload:
    """Report a classified endpoint error with context and detail."""

    run_token: int
    attempt_index: int
    related_type: MessageType | int
    error_code: ErrorCode
    detail: int

    def __post_init__(self) -> None:
        """Validate classified endpoint error context, enums, and detail.

        Direct call tree (static source order):
            __post_init__
            +-- _require_endpoint_context
            +-- _require_uint
            `-- _require_enum
        """
        _require_endpoint_context(self.run_token, self.attempt_index)
        _require_uint("related_type", self.related_type, 8)
        _require_enum("error_code", self.error_code, ErrorCode)
        _require_uint("detail", self.detail, 16)


def _require_bytes(name: str, value: bytes) -> bytes:
    """Require an immutable byte string without silently converting input.

    Processing flow:
        Protocol byte field -> require immutable bytes -> return the original value.

    Direct call tree (static source order):
        _require_bytes
        +-- isinstance
        `-- TypeError
    """
    value_is_bytes = isinstance(value, bytes)
    if not value_is_bytes:
        raise TypeError(f"{name} must be bytes")
    return value


def _require_exact_bytes(name: str, value: bytes, expected_length: int) -> bytes:
    """Require immutable bytes with one exact protocol field length.

    Processing flow:
        Protocol byte field -> require immutable bytes -> compare with the exact field width
        -> retain a matching value or reject its byte count.

    Direct call tree (static source order):
        _require_exact_bytes
        +-- _require_bytes
        +-- len
        `-- ValueError
    """
    _require_bytes(name, value)
    actual_length = len(value)
    length_is_wrong = actual_length != expected_length
    if length_is_wrong:
        raise ValueError(f"{name} must contain exactly {expected_length} bytes")
    return value


def _require_max_bytes(name: str, value: bytes, maximum_length: int) -> bytes:
    """Require immutable bytes no longer than one protocol field limit.

    Processing flow:
        Protocol byte field -> require immutable bytes -> enforce its maximum byte count
        -> retain the bounded payload or reject an oversized value.

    Direct call tree (static source order):
        _require_max_bytes
        +-- _require_bytes
        +-- len
        `-- ValueError
    """
    _require_bytes(name, value)
    actual_length = len(value)
    length_is_too_large = actual_length > maximum_length
    if length_is_too_large:
        raise ValueError(f"{name} must contain at most {maximum_length} bytes")
    return value


def _require_uint(name: str, value: int, bits: int) -> int:
    """Require an integer inside one unsigned fixed-width field.

    Processing flow:
        Unsigned protocol field -> reject Boolean values and values of any other type than integer
        -> require a value from zero through 2^bits - 1 -> return the accepted integer.

    Direct call tree (static source order):
        _require_uint
        +-- isinstance
        +-- TypeError
        `-- ValueError
    """
    value_is_boolean = isinstance(value, bool)
    if value_is_boolean:
        raise TypeError(f"{name} must be an integer")
    value_is_integer = isinstance(value, int)
    if not value_is_integer:
        raise TypeError(f"{name} must be an integer")
    value_is_negative = value < 0
    if value_is_negative:
        raise ValueError(f"{name} must fit in {bits} unsigned bits")
    exclusive_limit = 1 << bits
    value_is_too_large = value >= exclusive_limit
    if value_is_too_large:
        raise ValueError(f"{name} must fit in {bits} unsigned bits")
    return value


def _require_int8(name: str, value: int) -> int:
    """Require an integer inside one signed eight-bit field.

    Processing flow:
        Signed protocol field -> reject Boolean values and values of any other type than integer
        -> enforce the inclusive -128 through 127 range -> return the accepted integer.

    Direct call tree (static source order):
        _require_int8
        +-- isinstance
        +-- TypeError
        `-- ValueError
    """
    value_is_boolean = isinstance(value, bool)
    if value_is_boolean:
        raise TypeError(f"{name} must be an integer")
    value_is_integer = isinstance(value, int)
    if not value_is_integer:
        raise TypeError(f"{name} must be an integer")
    value_is_too_small = value < -128
    if value_is_too_small:
        raise ValueError(f"{name} must fit in 8 signed bits")
    value_is_too_large = value > 127
    if value_is_too_large:
        raise ValueError(f"{name} must fit in 8 signed bits")
    return value


def _require_enum(name: str, value: IntEnum, enum_type: type[IntEnum]) -> IntEnum:
    """Require an explicit member of the requested protocol enumeration.

    Processing flow:
        Protocol enumeration field -> require a member of the declared enum type
        -> retain the typed member without coercing a raw integer.

    Direct call tree (static source order):
        _require_enum
        +-- isinstance
        `-- TypeError
    """
    value_is_expected_enum = isinstance(value, enum_type)
    if not value_is_expected_enum:
        raise TypeError(f"{name} must be {enum_type.__name__}")
    return value


def _require_context(run_token: int, attempt_index: int) -> None:
    """Require one nonzero uint32 run token and one uint32 attempt index.

    Processing flow:
        Attempt identity -> require a run token within the uint32 range -> reject zero
        -> require an attempt index within the uint32 range.

    Direct call tree (static source order):
        _require_context
        +-- _require_uint
        `-- ValueError
    """
    _require_uint("run_token", run_token, 32)
    run_token_is_zero = run_token == 0
    if run_token_is_zero:
        raise ValueError("run_token must be nonzero")
    _require_uint("attempt_index", attempt_index, 32)


def _require_endpoint_context(run_token: int, attempt_index: int) -> None:
    """Require uint32 endpoint context fields while allowing the paired sentinel.

    Processing flow:
        Endpoint attempt identity -> apply the bounds for run token and attempt index
        -> permit the paired 0xFFFFFFFF sentinel for absent context and other valid contexts.

    Direct call tree (static source order):
        _require_endpoint_context
        `-- _require_context
    """
    _require_context(run_token, attempt_index)
    no_context_value = 0xFFFFFFFF
    run_marks_no_context = run_token == no_context_value
    attempt_marks_no_context = attempt_index == no_context_value
    if run_marks_no_context:
        if attempt_marks_no_context:
            return None
    # One maximum field by itself is an ordinary active-context uint32 value.
    return None


def _decode_enum(
    name: str,
    value: int,
    enum_type: type[_EnumT],
    code: ErrorCode,
) -> _EnumT:
    """Convert a wire integer to a known enum or raise a classified error.

    Processing flow:
        Wire integer -> decode the requested protocol enum
        -> map an unknown enum value to the supplied classified protocol error.

    Direct call tree (static source order):
        _decode_enum
        +-- enum_type
        `-- ProtocolError
    """
    try:
        return enum_type(value)
    except ValueError as error:
        raise ProtocolError(code, f"unknown {name}: {value}") from error


def _require_payload_length(payload: bytes, expected: int, message_name: str) -> None:
    """Reject a decoded payload whose byte count is not exactly expected.

    Processing flow:
        Decoded message payload -> require immutable bytes -> compare the exact message width
        -> raise BAD_LENGTH when the payload differs from that layout.

    Direct call tree (static source order):
        _require_payload_length
        +-- _require_bytes
        +-- len
        `-- ProtocolError
    """
    _require_bytes("payload", payload)
    if len(payload) != expected:
        raise ProtocolError(
            ErrorCode.BAD_LENGTH,
            f"{message_name} payload must contain exactly {expected} bytes",
        )


def _pack_context(run_token: int, attempt_index: int) -> bytes:
    """Pack one nonzero run token and one unsigned attempt index.

    Direct call tree (static source order):
        _pack_context
        +-- _require_context
        `-- _CONTEXT.pack
    """
    _require_context(run_token, attempt_index)
    return _CONTEXT.pack(run_token, attempt_index)


def _unpack_context(payload: bytes, message_name: str) -> tuple[int, int]:
    """Unpack and validate one exact eight-byte attempt identity.

    Processing flow:
        Attempt payload -> require the exact context layout of eight bytes
        -> unpack run token and attempt index -> reject a zero token before returning context.

    Direct call tree (static source order):
        _unpack_context
        +-- _require_payload_length
        +-- _CONTEXT.unpack
        `-- ProtocolError
    """
    _require_payload_length(payload, _CONTEXT.size, message_name)
    run_token, attempt_index = _CONTEXT.unpack(payload)
    if run_token == 0:
        raise ProtocolError(ErrorCode.CONTEXT_MISMATCH, "run_token must be nonzero")
    return run_token, attempt_index


def _pack_uint24(value: int, name: str) -> bytes:
    """Pack one unsigned 24-bit integer in protocol byte order.

    Direct call tree (static source order):
        _pack_uint24
        +-- _require_uint
        `-- value.to_bytes
    """
    _require_uint(name, value, 24)
    return value.to_bytes(3, "big")


def _unpack_uint24(value: bytes, name: str) -> int:
    """Unpack one exact unsigned 24-bit integer in protocol byte order.

    Processing flow:
        Register-word bytes -> require exactly three octets
        -> decode the unsigned value in protocol byte order.

    Direct call tree (static source order):
        _unpack_uint24
        +-- len
        +-- ProtocolError
        `-- int.from_bytes
    """
    if len(value) != 3:
        raise ProtocolError(ErrorCode.BAD_LENGTH, f"{name} must contain 3 bytes")
    return int.from_bytes(value, "big")


def crc16_ccitt_false(data: bytes) -> int:
    """Compute CRC-16/CCITT-FALSE over an immutable byte string.

    Processing flow:
        Input bytes -> initial remainder -> MSB-first bit updates -> CRC integer

    Direct call tree (static source order):
        crc16_ccitt_false
        +-- _require_bytes
        `-- range
    """
    _require_bytes("data", data)
    remainder = 0xFFFF
    for octet in data:
        remainder ^= octet << 8
        for _ in range(8):
            if remainder & 0x8000:
                remainder = ((remainder << 1) ^ 0x1021) & 0xFFFF
            else:
                remainder = (remainder << 1) & 0xFFFF
    return remainder


def cobs_encode(data: bytes) -> bytes:
    """Encode at most 128 decoded bytes with Consistent Overhead Byte Stuffing.

    References:
        Stuart Cheshire and Mary Baker, "Consistent Overhead Byte Stuffing", IEEE/ACM
        Transactions on Networking, vol. 7, no. 2, 1999, section 3.

    Processing flow:
        Decoded bytes -> split at zero or 254-byte run -> code blocks -> fragment

    Direct call tree (static source order):
        cobs_encode
        +-- _require_bytes
        +-- len
        +-- ProtocolError
        +-- bytearray
        +-- encoded.append
        `-- bytes
    """
    _require_bytes("data", data)
    if len(data) > MAX_DECODED_LENGTH:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "COBS input exceeds 128 bytes")

    encoded = bytearray((0,))
    code_position = 0
    code = 1
    for octet in data:
        if octet == 0:
            encoded[code_position] = code
            code_position = len(encoded)
            encoded.append(0)
            code = 1
        else:
            encoded.append(octet)
            code += 1
            if code == 0xFF:
                encoded[code_position] = code
                code_position = len(encoded)
                encoded.append(0)
                code = 1
    encoded[code_position] = code
    if len(encoded) > MAX_COBS_FRAGMENT_LENGTH:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "COBS output exceeds 129 bytes")
    return bytes(encoded)


def cobs_decode(fragment: bytes) -> bytes:
    """Decode one delimiter-free COBS fragment with strict structural checks.

    References:
        Stuart Cheshire and Mary Baker, "Consistent Overhead Byte Stuffing", IEEE/ACM
        Transactions on Networking, vol. 7, no. 2, 1999, section 3.

    Processing flow:
        Fragment -> validate code blocks -> restore implicit zeros -> decoded bytes

    Direct call tree (static source order):
        cobs_decode
        +-- _require_bytes
        +-- len
        +-- ProtocolError
        +-- bytearray
        +-- decoded.extend
        +-- decoded.append
        `-- bytes
    """
    _require_bytes("fragment", fragment)
    fragment_is_empty = len(fragment) == 0
    if fragment_is_empty:
        raise ProtocolError(ErrorCode.BAD_COBS, "invalid COBS fragment length")
    fragment_is_too_large = len(fragment) > MAX_COBS_FRAGMENT_LENGTH
    if fragment_is_too_large:
        raise ProtocolError(ErrorCode.BAD_COBS, "invalid COBS fragment length")
    if 0 in fragment:
        raise ProtocolError(ErrorCode.BAD_COBS, "COBS fragment contains zero")

    decoded = bytearray()
    index = 0
    while index < len(fragment):
        code = fragment[index]
        index += 1
        block_end = index + code - 1
        if block_end > len(fragment):
            raise ProtocolError(ErrorCode.BAD_COBS, "COBS code exceeds fragment")
        decoded.extend(fragment[index:block_end])
        index = block_end
        code_represents_short_block = code < 0xFF
        if code_represents_short_block:
            more_blocks_follow = index < len(fragment)
            if more_blocks_follow:
                decoded.append(0)
        if len(decoded) > MAX_DECODED_LENGTH:
            raise ProtocolError(ErrorCode.BAD_LENGTH, "decoded message exceeds 128 bytes")
    return bytes(decoded)


def encode_wire(message: Message) -> bytes:
    """Encode one validated message as one COBS fragment and one zero delimiter.

    Processing flow:
        Validated message fields -> encode binary header/payload and CRC -> COBS encode -> append zero frame delimiter.

    Direct call tree (static source order):
        encode_wire
        +-- isinstance
        +-- TypeError
        +-- _HEADER.pack
        +-- len
        +-- crc16_ccitt_false
        +-- crc_value.to_bytes
        +-- cobs_encode
        `-- ValueError
    """
    if not isinstance(message, Message):
        raise TypeError("message must be a Message")
    header = _HEADER.pack(
        MAGIC,
        VERSION,
        message.message_type.value,
        message.msg_seq,
        len(message.payload),
    )
    protected = header + message.payload
    crc_value = crc16_ccitt_false(protected)
    crc_bytes = crc_value.to_bytes(2, "big")
    decoded = protected + crc_bytes
    wire = cobs_encode(decoded) + b"\x00"
    if len(wire) > MAX_WIRE_LENGTH:
        raise ValueError("wire message exceeds 130 bytes")
    return wire


def decode_wire(wire: bytes) -> Message:
    """Decode one complete wire message and reject every malformed field.

    Processing flow:
        Wire bytes -> delimiter check -> COBS decode -> envelope checks
             -> length and CRC checks -> typed Message with preserved bytes

    Direct call tree (static source order):
        decode_wire
        +-- _require_bytes
        +-- len
        +-- ProtocolError
        +-- cobs_decode
        +-- _HEADER.unpack
        +-- int.from_bytes
        +-- crc16_ccitt_false
        +-- _decode_enum
        `-- Message
    """
    _require_bytes("wire", wire)
    wire_is_empty = len(wire) == 0
    if wire_is_empty:
        raise ProtocolError(ErrorCode.BAD_COBS, "wire must have exactly one final delimiter")
    final_byte_is_not_delimiter = wire[-1] != 0
    if final_byte_is_not_delimiter:
        raise ProtocolError(ErrorCode.BAD_COBS, "wire must have exactly one final delimiter")
    body_contains_delimiter = 0 in wire[:-1]
    if body_contains_delimiter:
        raise ProtocolError(ErrorCode.BAD_COBS, "wire must have exactly one final delimiter")
    if len(wire) > MAX_WIRE_LENGTH:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "wire exceeds 130 bytes")
    decoded = cobs_decode(wire[:-1])
    if len(decoded) < _HEADER.size + _CRC_LENGTH:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "decoded envelope is too short")

    header_bytes = decoded[: _HEADER.size]
    magic, version, type_code, msg_seq, payload_length = _HEADER.unpack(header_bytes)
    if magic != MAGIC:
        raise ProtocolError(ErrorCode.BAD_MAGIC, "message magic is not 0x5358")
    if version != VERSION:
        raise ProtocolError(ErrorCode.BAD_VERSION, "message version is not 1")
    expected_length = _HEADER.size + payload_length + _CRC_LENGTH
    payload_is_too_large = payload_length > MAX_PAYLOAD_LENGTH
    if payload_is_too_large:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "payload length does not match envelope")
    decoded_length_is_wrong = len(decoded) != expected_length
    if decoded_length_is_wrong:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "payload length does not match envelope")

    protected = decoded[:-2]
    received_crc = int.from_bytes(decoded[-2:], "big")
    if crc16_ccitt_false(protected) != received_crc:
        raise ProtocolError(ErrorCode.BAD_CRC, "message CRC does not match")
    message_type = _decode_enum(
        "message type", type_code, MessageType, ErrorCode.UNKNOWN_TYPE
    )
    payload = decoded[_HEADER.size:-2]
    return Message(message_type, msg_seq, payload, decoded, wire)


class StreamDecoder:
    """Reassemble complete wire messages from arbitrary serial byte chunks."""

    def __init__(self) -> None:
        """Start an empty serial fragment and separate decoded-message/error queues.

        Direct call tree (static source order):
            __init__
            `-- bytearray
        """
        self._fragment = bytearray()
        self._discarding = False
        self._last_byte_ms: int | None = None
        self._pending_messages: list[Message] = []
        self._pending_errors: list[ProtocolError] = []

    def drain_messages(self) -> tuple[Message, ...]:
        """Return every saved valid message in arrival order and clear the queue.

        Processing flow:
            Pending message list -> immutable ordered tuple -> cleared list

        Direct call tree (static source order):
            drain_messages
            +-- tuple
            `-- self._pending_messages.clear
        """
        messages = tuple(self._pending_messages)
        self._pending_messages.clear()
        return messages

    def feed(self, data: bytes, now_ms: int | None = None) -> tuple[Message, ...]:
        """Consume a chunk, saving valid messages and reporting one queued error.

        Processing flow:
            New bytes -> discard or append -> decode every delimiter boundary
                      -> save valid messages / queue errors -> raise or drain

        Direct call tree (static source order):
            feed
            +-- _require_bytes
            +-- _require_uint
            +-- bytes
            +-- self._fragment.clear
            +-- decode_wire
            +-- self._pending_errors.append
            +-- self._pending_messages.append
            +-- self._fragment.append
            +-- len
            +-- ProtocolError
            +-- self._pending_errors.pop
            `-- self.drain_messages
        """
        _require_bytes("data", data)
        if now_ms is not None:
            _require_uint("now_ms", now_ms, 63)

        for octet in data:
            if self._discarding:
                if octet == 0:
                    self._discarding = False
                continue
            if octet == 0:
                wire = bytes(self._fragment) + b"\x00"
                self._fragment.clear()
                self._last_byte_ms = None
                try:
                    message = decode_wire(wire)
                except ProtocolError as error:
                    self._pending_errors.append(error)
                    continue
                self._pending_messages.append(message)
                continue
            self._fragment.append(octet)
            self._last_byte_ms = now_ms
            if len(self._fragment) > MAX_COBS_FRAGMENT_LENGTH:
                self._fragment.clear()
                self._last_byte_ms = None
                self._discarding = True
                overflow_error = ProtocolError(
                    ErrorCode.SERIAL_OVERFLOW,
                    "serial fragment exceeded 129 bytes before delimiter",
                    "fragment_length",
                )
                self._pending_errors.append(overflow_error)

        pending_error_count = len(self._pending_errors)
        errors_are_waiting = pending_error_count > 0
        if errors_are_waiting:
            pending_error = self._pending_errors.pop(0)
            raise pending_error
        return self.drain_messages()

    def poll_timeout(self, now_ms: int) -> bool:
        """Discard one stale partial fragment and report its single timeout.

        Processing flow:
            Current time -> compare last byte -> keep fragment or enter discard

        Direct call tree (static source order):
            poll_timeout
            +-- _require_uint
            +-- len
            +-- self._fragment.clear
            `-- ProtocolError
        """
        _require_uint("now_ms", now_ms, 63)
        if self._discarding:
            return False
        fragment_is_empty = len(self._fragment) == 0
        if fragment_is_empty:
            return False
        if self._last_byte_ms is None:
            return False
        elapsed = now_ms - self._last_byte_ms
        if elapsed < INTER_BYTE_TIMEOUT_MS:
            return False
        self._fragment.clear()
        self._last_byte_ms = None
        self._discarding = True
        raise ProtocolError(
            ErrorCode.SERIAL_OVERFLOW,
            "serial fragment exceeded the 250 ms inter-byte timeout",
            "interbyte_timeout",
        )


def pack_hello() -> bytes:
    """Pack the empty HELLO payload defined by protocol version 1.

    Processing flow:
        No fields -> exact empty byte string

    Direct call tree (static source order):
        pack_hello
        `-- [no direct function calls; local state/return only]
    """
    return b""


def unpack_hello(payload: bytes) -> HelloPayload:
    """Decode the exact empty HELLO payload.

    Processing flow:
        Input bytes -> exact-length check -> empty typed payload

    Direct call tree (static source order):
        unpack_hello
        +-- _require_payload_length
        `-- HelloPayload
    """
    _require_payload_length(payload, 0, "HELLO")
    return HelloPayload()


def pack_reset_to_standby() -> bytes:
    """Pack the empty RESET_TO_STANDBY payload defined by version 1.

    Processing flow:
        No fields -> exact empty byte string

    Direct call tree (static source order):
        pack_reset_to_standby
        `-- [no direct function calls; local state/return only]
    """
    return b""


def unpack_reset_to_standby(payload: bytes) -> ResetToStandbyPayload:
    """Decode the exact empty RESET_TO_STANDBY payload.

    Processing flow:
        Input bytes -> exact-length check -> empty typed payload

    Direct call tree (static source order):
        unpack_reset_to_standby
        +-- _require_payload_length
        `-- ResetToStandbyPayload
    """
    _require_payload_length(payload, 0, "RESET_TO_STANDBY")
    return ResetToStandbyPayload()


def pack_apply_profile(profile_code: ProfileCode, profile_table_hash: bytes) -> bytes:
    """Pack a profile code and exact 32-byte profile-table hash.

    Processing flow:
        Typed fields -> enum/hash validation -> exact 33-byte payload

    Direct call tree (static source order):
        pack_apply_profile
        +-- _require_enum
        +-- _require_bytes
        +-- len
        +-- ValueError
        `-- bytes
    """
    _require_enum("profile_code", profile_code, ProfileCode)
    _require_bytes("profile_table_hash", profile_table_hash)
    if len(profile_table_hash) != 32:
        raise ValueError("profile_table_hash must contain exactly 32 bytes")
    return bytes((profile_code.value,)) + profile_table_hash


def unpack_apply_profile(payload: bytes) -> ApplyProfilePayload:
    """Decode and validate one APPLY_PROFILE payload.

    Processing flow:
        33 bytes -> enum validation -> immutable hash view

    Direct call tree (static source order):
        unpack_apply_profile
        +-- _require_payload_length
        +-- _decode_enum
        `-- ApplyProfilePayload
    """
    _require_payload_length(payload, 33, "APPLY_PROFILE")
    profile_code = _decode_enum("profile code", payload[0], ProfileCode, ErrorCode.PROFILE)
    return ApplyProfilePayload(profile_code, payload[1:])


def pack_set_pa(pa_command_dbm: int, reg_ocp: int) -> bytes:
    """Pack a signed PA command and complete RegOcp register byte.

    Processing flow:
        PA and OCP -> signed/unsigned checks -> exact two-byte payload

    Direct call tree (static source order):
        pack_set_pa
        +-- _require_int8
        +-- _require_uint
        `-- struct.pack
    """
    _require_int8("pa_command_dbm", pa_command_dbm)
    _require_uint("reg_ocp", reg_ocp, 8)
    return struct.pack(">bB", pa_command_dbm, reg_ocp)


def unpack_set_pa(payload: bytes) -> SetPaPayload:
    """Decode one exact SET_PA payload.

    Processing flow:
        Two bytes -> exact-length check -> typed signed/unsigned fields

    Direct call tree (static source order):
        unpack_set_pa
        +-- _require_payload_length
        +-- struct.unpack
        `-- SetPaPayload
    """
    _require_payload_length(payload, 2, "SET_PA")
    pa_command_dbm, reg_ocp = struct.unpack(">bB", payload)
    return SetPaPayload(pa_command_dbm, reg_ocp)


def pack_load_tx(
    run_token: int,
    attempt_index: int,
    reg_frf_word: int,
    frame: bytes,
) -> bytes:
    """Pack one 64-byte TM frame with its attempt and absolute FRF word.

    Processing flow:
        Context -> FRF uint24 -> fixed length byte -> unchanged 64-byte frame

    Direct call tree (static source order):
        pack_load_tx
        +-- _pack_context
        +-- _pack_uint24
        +-- _require_bytes
        +-- len
        `-- ValueError
    """
    context = _pack_context(run_token, attempt_index)
    frf = _pack_uint24(reg_frf_word, "reg_frf_word")
    _require_bytes("frame", frame)
    if len(frame) != 64:
        raise ValueError("frame must contain exactly 64 bytes")
    return context + frf + b"\x40" + frame


def unpack_load_tx(payload: bytes) -> LoadTxPayload:
    """Decode one exact LOAD_TX payload without altering its frame bytes.

    Processing flow:
        76 bytes -> context -> FRF uint24 -> frame-length check -> typed payload

    Direct call tree (static source order):
        unpack_load_tx
        +-- _require_payload_length
        +-- _unpack_context
        +-- _unpack_uint24
        +-- ProtocolError
        `-- LoadTxPayload
    """
    _require_payload_length(payload, 76, "LOAD_TX")
    run_token, attempt_index = _unpack_context(payload[:8], "LOAD_TX context")
    reg_frf_word = _unpack_uint24(payload[8:11], "reg_frf_word")
    if payload[11] != 64:
        raise ProtocolError(ErrorCode.FRAME_LENGTH, "LOAD_TX frame length must be 64")
    return LoadTxPayload(run_token, attempt_index, reg_frf_word, payload[12:])


def pack_arm_rx(run_token: int, attempt_index: int, rx_window_ms: int) -> bytes:
    """Pack an ARM_RX context and unsigned receive-window duration.

    Processing flow:
        Attempt context -> window validation -> exact ten-byte payload

    Direct call tree (static source order):
        pack_arm_rx
        +-- _pack_context
        +-- _require_uint
        +-- ValueError
        `-- rx_window_ms.to_bytes
    """
    context = _pack_context(run_token, attempt_index)
    _require_uint("rx_window_ms", rx_window_ms, 16)
    if rx_window_ms == 0:
        raise ValueError("rx_window_ms must be positive")
    return context + rx_window_ms.to_bytes(2, "big")


def unpack_arm_rx(payload: bytes) -> ArmRxPayload:
    """Decode one exact ARM_RX payload.

    Processing flow:
        Ten bytes -> context/window checks -> typed payload

    Direct call tree (static source order):
        unpack_arm_rx
        +-- _require_payload_length
        +-- _unpack_context
        +-- int.from_bytes
        `-- ArmRxPayload
    """
    _require_payload_length(payload, 10, "ARM_RX")
    run_token, attempt_index = _unpack_context(payload[:8], "ARM_RX context")
    rx_window_ms = int.from_bytes(payload[8:], "big")
    return ArmRxPayload(run_token, attempt_index, rx_window_ms)


def pack_start_tx(run_token: int, attempt_index: int) -> bytes:
    """Pack the exact START_TX attempt identity.

    Direct call tree (static source order):
        pack_start_tx
        `-- _pack_context
    """
    return _pack_context(run_token, attempt_index)


def unpack_start_tx(payload: bytes) -> StartTxPayload:
    """Decode the exact START_TX attempt identity.

    Direct call tree (static source order):
        unpack_start_tx
        +-- _unpack_context
        `-- StartTxPayload
    """
    run_token, attempt_index = _unpack_context(payload, "START_TX")
    return StartTxPayload(run_token, attempt_index)


def pack_cancel_attempt(run_token: int, attempt_index: int) -> bytes:
    """Pack the exact CANCEL_ATTEMPT identity.

    Direct call tree (static source order):
        pack_cancel_attempt
        `-- _pack_context
    """
    return _pack_context(run_token, attempt_index)


def unpack_cancel_attempt(payload: bytes) -> CancelAttemptPayload:
    """Decode the exact CANCEL_ATTEMPT identity.

    Direct call tree (static source order):
        unpack_cancel_attempt
        +-- _unpack_context
        `-- CancelAttemptPayload
    """
    run_token, attempt_index = _unpack_context(payload, "CANCEL_ATTEMPT")
    return CancelAttemptPayload(run_token, attempt_index)


def pack_get_attempt_status(run_token: int, attempt_index: int) -> bytes:
    """Pack the exact GET_ATTEMPT_STATUS identity.

    Direct call tree (static source order):
        pack_get_attempt_status
        `-- _pack_context
    """
    return _pack_context(run_token, attempt_index)


def unpack_get_attempt_status(payload: bytes) -> GetAttemptStatusPayload:
    """Decode the exact GET_ATTEMPT_STATUS identity.

    Direct call tree (static source order):
        unpack_get_attempt_status
        +-- _unpack_context
        `-- GetAttemptStatusPayload
    """
    run_token, attempt_index = _unpack_context(payload, "GET_ATTEMPT_STATUS")
    return GetAttemptStatusPayload(run_token, attempt_index)


def pack_ack(related_type: MessageType, status: int = 0) -> bytes:
    """Pack an ACK whose version-1 status is exactly zero.

    Processing flow:
        Related type/status -> enum/zero checks -> exact two-byte payload

    Direct call tree (static source order):
        pack_ack
        +-- _require_enum
        +-- ValueError
        +-- _require_uint
        `-- bytes
    """
    _require_enum("related_type", related_type, MessageType)
    if related_type not in HOST_COMMAND_TYPES:
        raise ValueError("ACK related_type must be a host command")
    _require_uint("status", status, 8)
    if status != 0:
        raise ValueError("ACK status must be zero in protocol version 1")
    return bytes((related_type.value, status))


def unpack_ack(payload: bytes) -> AckPayload:
    """Decode an ACK and reject nonzero version-1 status.

    Processing flow:
        Two bytes -> type/status checks -> typed acknowledgement

    Direct call tree (static source order):
        unpack_ack
        +-- _require_payload_length
        +-- _decode_enum
        +-- ProtocolError
        `-- AckPayload
    """
    _require_payload_length(payload, 2, "ACK")
    related_type = _decode_enum(
        "related type", payload[0], MessageType, ErrorCode.UNKNOWN_TYPE
    )
    if payload[1] != 0:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "ACK status must be zero")
    return AckPayload(related_type, 0)


def pack_hello_report(
    endpoint_id: int,
    boot_count: int,
    reg_version: int,
    state: AttemptState,
    firmware_hash: bytes,
    profile_table_hash: bytes,
    board_profile_hash: bytes,
) -> bytes:
    """Pack endpoint identity, state, radio version, and three build hashes.

    Processing flow:
        Identity fields -> radio/state bytes -> validate hashes -> 106 bytes

    Direct call tree (static source order):
        pack_hello_report
        +-- _require_uint
        +-- _require_enum
        +-- _require_bytes
        +-- len
        +-- ValueError
        `-- struct.pack
    """
    _require_uint("endpoint_id", endpoint_id, 32)
    _require_uint("boot_count", boot_count, 32)
    _require_uint("reg_version", reg_version, 8)
    _require_enum("state", state, AttemptState)
    hashes = (firmware_hash, profile_table_hash, board_profile_hash)
    for value in hashes:
        _require_bytes("hash", value)
        if len(value) != 32:
            raise ValueError("HELLO_REPORT hashes must contain exactly 32 bytes")
    prefix = struct.pack(">IIBB", endpoint_id, boot_count, reg_version, state.value)
    return prefix + firmware_hash + profile_table_hash + board_profile_hash


def unpack_hello_report(payload: bytes) -> HelloReportPayload:
    """Decode one exact HELLO_REPORT payload.

    Processing flow:
        106 bytes -> identity fields -> state enum -> three unchanged hashes

    Direct call tree (static source order):
        unpack_hello_report
        +-- _require_payload_length
        +-- struct.unpack
        +-- _decode_enum
        `-- HelloReportPayload
    """
    _require_payload_length(payload, 106, "HELLO_REPORT")
    endpoint_id, boot_count, reg_version, state_code = struct.unpack(
        ">IIBB", payload[:10]
    )
    state = _decode_enum("attempt state", state_code, AttemptState, ErrorCode.BAD_STATE)
    return HelloReportPayload(
        endpoint_id,
        boot_count,
        reg_version,
        state,
        payload[10:42],
        payload[42:74],
        payload[74:106],
    )


def pack_config_report(
    related_type: MessageType,
    profile_code: ProfileCode,
    pa_command_dbm: int,
    reg_pa_config: int,
    reg_pa_dac: int,
    reg_ocp: int,
    registers: tuple[tuple[int, int], ...],
) -> bytes:
    """Pack applied configuration and at most 55 register read-back pairs.

    Processing flow:
        Fixed fields -> validate count -> encode address/value pairs -> payload

    Direct call tree (static source order):
        pack_config_report
        +-- _require_enum
        +-- ValueError
        +-- _require_int8
        +-- _require_uint
        +-- isinstance
        +-- TypeError
        +-- len
        +-- bytearray
        +-- encoded_registers.extend
        +-- struct.pack
        `-- bytes
    """
    _require_enum("related_type", related_type, MessageType)
    if related_type not in CONFIG_REPORT_RELATED_TYPES:
        raise ValueError("CONFIG_REPORT must relate to APPLY_PROFILE or SET_PA")
    _require_enum("profile_code", profile_code, ProfileCode)
    _require_int8("pa_command_dbm", pa_command_dbm)
    _require_uint("reg_pa_config", reg_pa_config, 8)
    _require_uint("reg_pa_dac", reg_pa_dac, 8)
    _require_uint("reg_ocp", reg_ocp, 8)
    if not isinstance(registers, tuple):
        raise TypeError("registers must be a tuple")
    if len(registers) > 55:
        raise ValueError("CONFIG_REPORT may contain at most 55 registers")
    encoded_registers = bytearray()
    for pair in registers:
        pair_is_a_tuple = isinstance(pair, tuple)
        if not pair_is_a_tuple:
            raise TypeError("each register must be an (address, value) tuple")
        pair_has_wrong_length = len(pair) != 2
        if pair_has_wrong_length:
            raise TypeError("each register must be an (address, value) tuple")
        address, value = pair
        _require_uint("register address", address, 8)
        _require_uint("register value", value, 8)
        encoded_registers.extend((address, value))
    prefix = struct.pack(
        ">BBbBBBB",
        related_type.value,
        profile_code.value,
        pa_command_dbm,
        reg_pa_config,
        reg_pa_dac,
        reg_ocp,
        len(registers),
    )
    return prefix + bytes(encoded_registers)


def unpack_config_report(payload: bytes) -> ConfigReportPayload:
    """Decode a CONFIG_REPORT with an exact register count and no trailing data.

    Processing flow:
        Prefix -> enum/count checks -> exact length -> register pairs -> view

    Direct call tree (static source order):
        unpack_config_report
        +-- _require_bytes
        +-- len
        +-- ProtocolError
        +-- struct.unpack
        +-- _decode_enum
        +-- RegisterValue
        +-- register_items.append
        +-- tuple
        `-- ConfigReportPayload
    """
    _require_bytes("payload", payload)
    if len(payload) < 7:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "CONFIG_REPORT is shorter than 7 bytes")
    related, profile, pa_dbm, pa_config, pa_dac, ocp, count = struct.unpack(
        ">BBbBBBB", payload[:7]
    )
    count_is_too_large = count > 55
    if count_is_too_large:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "CONFIG_REPORT register count mismatches")
    expected_length = 7 + 2 * count
    payload_length_is_wrong = len(payload) != expected_length
    if payload_length_is_wrong:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "CONFIG_REPORT register count mismatches")
    related_type = _decode_enum(
        "related type", related, MessageType, ErrorCode.UNKNOWN_TYPE
    )
    profile_code = _decode_enum("profile code", profile, ProfileCode, ErrorCode.PROFILE)
    register_items: list[RegisterValue] = []
    index = 7
    while index < len(payload):
        register = RegisterValue(payload[index], payload[index + 1])
        register_items.append(register)
        index += 2
    registers = tuple(register_items)
    return ConfigReportPayload(
        related_type, profile_code, pa_dbm, pa_config, pa_dac, ocp, registers
    )


def pack_tx_ready(run_token: int, attempt_index: int, reg_frf_readback: int) -> bytes:
    """Pack a TX_READY context and absolute FRF register read-back.

    Processing flow:
        Attempt context -> FRF uint24 check -> exact eleven-byte payload

    Direct call tree (static source order):
        pack_tx_ready
        +-- _pack_context
        `-- _pack_uint24
    """
    context = _pack_context(run_token, attempt_index)
    frf = _pack_uint24(reg_frf_readback, "reg_frf_readback")
    return context + frf


def unpack_tx_ready(payload: bytes) -> TxReadyPayload:
    """Decode one exact TX_READY payload.

    Processing flow:
        Eleven bytes -> context/FRF checks -> typed payload

    Direct call tree (static source order):
        unpack_tx_ready
        +-- _require_payload_length
        +-- _unpack_context
        +-- _unpack_uint24
        `-- TxReadyPayload
    """
    _require_payload_length(payload, 11, "TX_READY")
    run_token, attempt_index = _unpack_context(payload[:8], "TX_READY context")
    reg_frf_readback = _unpack_uint24(payload[8:], "reg_frf_readback")
    return TxReadyPayload(run_token, attempt_index, reg_frf_readback)


def pack_rx_armed(
    run_token: int,
    attempt_index: int,
    reg_frf_readback: int,
    rx_window_ms: int,
) -> bytes:
    """Pack an RX_ARMED context, FRF read-back, and receive window.

    Processing flow:
        Context -> FRF/window checks -> exact thirteen-byte payload

    Direct call tree (static source order):
        pack_rx_armed
        +-- _pack_context
        +-- _pack_uint24
        +-- _require_uint
        `-- rx_window_ms.to_bytes
    """
    context = _pack_context(run_token, attempt_index)
    frf = _pack_uint24(reg_frf_readback, "reg_frf_readback")
    _require_uint("rx_window_ms", rx_window_ms, 16)
    return context + frf + rx_window_ms.to_bytes(2, "big")


def unpack_rx_armed(payload: bytes) -> RxArmedPayload:
    """Decode one exact RX_ARMED payload.

    Processing flow:
        Thirteen bytes -> context/FRF/window checks -> typed payload

    Direct call tree (static source order):
        unpack_rx_armed
        +-- _require_payload_length
        +-- _unpack_context
        +-- int.from_bytes
        +-- RxArmedPayload
        `-- _unpack_uint24
    """
    _require_payload_length(payload, 13, "RX_ARMED")
    run_token, attempt_index = _unpack_context(payload[:8], "RX_ARMED context")
    rx_window_ms = int.from_bytes(payload[11:13], "big")
    return RxArmedPayload(
        run_token,
        attempt_index,
        _unpack_uint24(payload[8:11], "reg_frf_readback"),
        rx_window_ms,
    )


def pack_tx_started(run_token: int, attempt_index: int) -> bytes:
    """Pack the exact TX_STARTED attempt identity.

    Direct call tree (static source order):
        pack_tx_started
        `-- _pack_context
    """
    return _pack_context(run_token, attempt_index)


def unpack_tx_started(payload: bytes) -> TxStartedPayload:
    """Decode the exact TX_STARTED attempt identity.

    Direct call tree (static source order):
        unpack_tx_started
        +-- _unpack_context
        `-- TxStartedPayload
    """
    run_token, attempt_index = _unpack_context(payload, "TX_STARTED")
    return TxStartedPayload(run_token, attempt_index)


def pack_tx_done(run_token: int, attempt_index: int) -> bytes:
    """Pack the exact TX_DONE attempt identity.

    Direct call tree (static source order):
        pack_tx_done
        `-- _pack_context
    """
    return _pack_context(run_token, attempt_index)


def unpack_tx_done(payload: bytes) -> TxDonePayload:
    """Decode the exact TX_DONE attempt identity.

    Direct call tree (static source order):
        unpack_tx_done
        +-- _unpack_context
        `-- TxDonePayload
    """
    run_token, attempt_index = _unpack_context(payload, "TX_DONE")
    return TxDonePayload(run_token, attempt_index)


def pack_rx_packet(
    run_token: int,
    attempt_index: int,
    phy_crc_ok: int,
    metrics_flags: int,
    rssi_raw: int,
    snr_raw: int,
    packet: bytes,
    *,
    received_length: int | None = None,
) -> bytes:
    """Pack actual radio metadata and the FIFO bytes retained within the buffer.

    Inputs: Attempt context, CRC status, metric flags and raw values, retained
        packet bytes, and optional actual radio length. Omitted received_length
        uses the packet length to preserve ordinary report callers.
    Returns: RX_PACKET payload bytes; lengths above 64 require an empty packet.

    Processing flow:
        Actual or inferred length -> validated observation -> context -> metadata/body.

    Direct call tree (static source order):
        pack_rx_packet
        +-- _require_bytes
        +-- len
        +-- RxPacketPayload
        +-- _pack_context
        `-- struct.pack
    """
    _require_bytes("packet", packet)
    if received_length is None:
        received_length = len(packet)
    observation = RxPacketPayload(
        run_token,
        attempt_index,
        phy_crc_ok,
        received_length,
        metrics_flags,
        rssi_raw,
        snr_raw,
        packet,
    )
    context = _pack_context(observation.run_token, observation.attempt_index)
    prefix = struct.pack(
        ">BBBBb",
        observation.phy_crc_ok,
        observation.received_length,
        observation.metrics_flags,
        observation.rssi_raw,
        observation.snr_raw,
    )
    return context + prefix + observation.packet


def unpack_rx_packet(payload: bytes) -> RxPacketPayload:
    """Decode RX_PACKET while distinguishing radio length from retained bytes.

    Inputs: RX_PACKET payload bytes from one validated serial envelope.
    Returns: An observation containing the actual radio length, CRC and metrics.
        Lengths above 64 require exactly the prefix of 13 bytes and retain no body.

    Processing flow:
        Prefix -> context/IRQ checks -> body retention rule -> typed observation.

    Direct call tree (static source order):
        unpack_rx_packet
        +-- _require_bytes
        +-- len
        +-- ProtocolError
        +-- _unpack_context
        +-- struct.unpack
        `-- RxPacketPayload
    """
    _require_bytes("payload", payload)
    if len(payload) < 13:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "RX_PACKET is shorter than 13 bytes")
    run_token, attempt_index = _unpack_context(payload[:8], "RX_PACKET context")
    phy_crc_ok, received_length, flags, rssi_raw, snr_raw = struct.unpack(
        ">BBBBb", payload[8:13]
    )
    if phy_crc_ok not in (0, 1):
        raise ProtocolError(ErrorCode.BAD_LENGTH, "phy_crc_ok must be 0 or 1")
    if flags & ~0x03:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "invalid RX_PACKET metrics flags")
    expected_length = 13
    if received_length <= 64:
        expected_length += received_length
    payload_length_is_wrong = len(payload) != expected_length
    if payload_length_is_wrong:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "RX_PACKET length mismatches")
    rssi_flag = flags & 0x01
    rssi_is_absent = rssi_flag == 0
    if rssi_is_absent:
        rssi_value_is_not_zero = rssi_raw != 0
        if rssi_value_is_not_zero:
            raise ProtocolError(ErrorCode.BAD_LENGTH, "invalid absent RSSI raw value")
    snr_flag = flags & 0x02
    snr_is_absent = snr_flag == 0
    if snr_is_absent:
        snr_value_is_not_zero = snr_raw != 0
        if snr_value_is_not_zero:
            raise ProtocolError(ErrorCode.BAD_LENGTH, "invalid absent SNR raw value")
    return RxPacketPayload(
        run_token,
        attempt_index,
        phy_crc_ok,
        received_length,
        flags,
        rssi_raw,
        snr_raw,
        payload[13:],
    )


def pack_rx_timeout(run_token: int, attempt_index: int) -> bytes:
    """Pack the exact RX_TIMEOUT attempt identity.

    Direct call tree (static source order):
        pack_rx_timeout
        `-- _pack_context
    """
    return _pack_context(run_token, attempt_index)


def unpack_rx_timeout(payload: bytes) -> RxTimeoutPayload:
    """Decode the exact RX_TIMEOUT attempt identity.

    Direct call tree (static source order):
        unpack_rx_timeout
        +-- _unpack_context
        `-- RxTimeoutPayload
    """
    run_token, attempt_index = _unpack_context(payload, "RX_TIMEOUT")
    return RxTimeoutPayload(run_token, attempt_index)


def pack_attempt_status(
    run_token: int,
    attempt_index: int,
    state: AttemptState,
    last_error_code: int,
) -> bytes:
    """Pack an ATTEMPT_STATUS state and zero-or-known error code.

    Processing flow:
        Context/state/error -> range checks -> exact eleven-byte payload

    Direct call tree (static source order):
        pack_attempt_status
        +-- _pack_context
        +-- _require_enum
        +-- _require_uint
        +-- ValueError
        +-- bytes
        `-- last_error_code.to_bytes
    """
    context = _pack_context(run_token, attempt_index)
    _require_enum("state", state, AttemptState)
    _require_uint("last_error_code", last_error_code, 16)
    if last_error_code > ErrorCode.ENDPOINT_RESET.value:
        raise ValueError("last_error_code must be zero or a known ErrorCode")
    return context + bytes((state.value,)) + last_error_code.to_bytes(2, "big")


def unpack_attempt_status(payload: bytes) -> AttemptStatusPayload:
    """Decode one exact ATTEMPT_STATUS payload.

    Processing flow:
        Eleven bytes -> context/state/error checks -> typed payload

    Direct call tree (static source order):
        unpack_attempt_status
        +-- _require_payload_length
        +-- _unpack_context
        +-- _decode_enum
        +-- int.from_bytes
        +-- ProtocolError
        `-- AttemptStatusPayload
    """
    _require_payload_length(payload, 11, "ATTEMPT_STATUS")
    run_token, attempt_index = _unpack_context(payload[:8], "ATTEMPT_STATUS context")
    state = _decode_enum("attempt state", payload[8], AttemptState, ErrorCode.BAD_STATE)
    last_error_code = int.from_bytes(payload[9:11], "big")
    if last_error_code > ErrorCode.ENDPOINT_RESET.value:
        raise ProtocolError(ErrorCode.BAD_LENGTH, "unknown last error code")
    return AttemptStatusPayload(run_token, attempt_index, state, last_error_code)


def pack_endpoint_error(
    run_token: int,
    attempt_index: int,
    related_type: MessageType | int,
    error_code: ErrorCode,
    detail: int,
) -> bytes:
    """Pack one classified endpoint error and its machine-readable detail.

    Processing flow:
        Context -> related type/error/detail checks -> exact thirteen-byte payload

    Direct call tree (static source order):
        pack_endpoint_error
        +-- _require_endpoint_context
        +-- _CONTEXT.pack
        +-- _require_uint
        +-- _require_enum
        +-- bytes
        +-- int
        `-- struct.pack
    """
    _require_endpoint_context(run_token, attempt_index)
    context = _CONTEXT.pack(run_token, attempt_index)
    _require_uint("related_type", related_type, 8)
    _require_enum("error_code", error_code, ErrorCode)
    _require_uint("detail", detail, 16)
    related_type_byte = bytes((int(related_type),))
    error_fields = struct.pack(">HH", error_code.value, detail)
    return context + related_type_byte + error_fields


def unpack_endpoint_error(payload: bytes) -> EndpointErrorPayload:
    """Decode one exact ENDPOINT_ERROR payload.

    Processing flow:
        Thirteen bytes -> context/type/error checks -> typed payload

    Direct call tree (static source order):
        unpack_endpoint_error
        +-- _require_payload_length
        +-- _unpack_context
        +-- MessageType
        +-- struct.unpack
        +-- _decode_enum
        `-- EndpointErrorPayload
    """
    _require_payload_length(payload, 13, "ENDPOINT_ERROR")
    run_token, attempt_index = _unpack_context(payload[:8], "ENDPOINT_ERROR context")
    raw_related_type = payload[8]
    related_type: MessageType | int = raw_related_type
    try:
        related_type = MessageType(raw_related_type)
    except ValueError:
        related_type = raw_related_type
    error_value, detail = struct.unpack(">HH", payload[9:13])
    error_code = _decode_enum("error code", error_value, ErrorCode, ErrorCode.BAD_LENGTH)
    return EndpointErrorPayload(
        run_token, attempt_index, related_type, error_code, detail
    )
