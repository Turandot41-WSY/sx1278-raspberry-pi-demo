"""Codec-backed byte-port fakes used before the full endpoint model exists."""

from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass, field
from enum import Enum

from host.radio.serial_protocol import (
    AckPayload,
    AttemptState,
    AttemptStatusPayload,
    ConfigReportPayload,
    EndpointErrorPayload,
    ErrorCode,
    HelloReportPayload,
    Message,
    MessageType,
    ProfileCode,
    RegisterValue,
    RxArmedPayload,
    RxPacketPayload,
    RxTimeoutPayload,
    TxDonePayload,
    TxReadyPayload,
    TxStartedPayload,
    decode_wire,
    encode_wire,
    pack_ack,
    pack_apply_profile,
    pack_arm_rx,
    pack_attempt_status,
    pack_config_report,
    pack_endpoint_error,
    pack_hello_report,
    pack_load_tx,
    pack_rx_packet,
    pack_rx_armed,
    pack_rx_timeout,
    pack_set_pa,
    pack_start_tx,
    pack_tx_done,
    pack_tx_ready,
    pack_tx_started,
    unpack_apply_profile,
    unpack_arm_rx,
    unpack_cancel_attempt,
    unpack_get_attempt_status,
    unpack_hello,
    unpack_load_tx,
    unpack_reset_to_standby,
    unpack_set_pa,
    unpack_start_tx,
)


@dataclass(frozen=True)
class WireObservation:
    """Record the direction and exact bytes accepted by an evidence sink."""

    monotonic_ns: int
    utc_ns: int
    endpoint_id: int
    direction: int
    wire_bytes: bytes


class EvidenceSpy:
    """Collect append_wire calls in memory without touching a filesystem."""

    def __init__(self) -> None:
        """Initialize EvidenceSpy with the supplied dependencies and state.

        Inputs: no explicit arguments; instance or module state where referenced.
        Returns: None.

        Direct call tree (static source order):
            __init__
            `-- [no direct function calls; local state/return only]
        """
        self.wires: list[WireObservation] = []

    def append_wire(
        self,
        monotonic_ns: int,
        utc_ns: int,
        endpoint_id: int,
        direction: int,
        wire_bytes: bytes,
    ) -> int:
        """Store one exact wire observation and return its zero-based index.

        Direct call tree (static source order):
            append_wire
            +-- WireObservation
            +-- self.wires.append
            `-- len
        """
        observation = WireObservation(
            monotonic_ns,
            utc_ns,
            endpoint_id,
            direction,
            wire_bytes,
        )
        self.wires.append(observation)
        return len(self.wires) - 1


class ScriptedBytePort:
    """Turn complete command wires into deterministic response byte chunks."""

    def __init__(
        self,
        responder: Callable[[bytes], bytes],
        chunks: list[int] | None = None,
        write_limit: int | None = None,
    ) -> None:
        """Initialize ScriptedBytePort with the supplied dependencies and state.

        Inputs: responder, chunks, write_limit.
        Returns: None.

        Direct call tree (static source order):
            __init__
            +-- list
            `-- bytearray
        """
        self._responder = responder
        if chunks is None:
            self._chunks = [130]
        else:
            self._chunks = list(chunks)
        self._pending = bytearray()
        self._chunk_index = 0
        self._write_limit = write_limit
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        """Accept one host wire and stage the responder's returned bytes.

        Direct call tree (static source order):
            write
            +-- self.writes.append
            +-- len
            +-- self._responder
            +-- isinstance
            +-- TypeError
            `-- self._pending.extend
        """
        self.writes.append(data)
        if self._write_limit is not None:
            if self._write_limit < len(data):
                return self._write_limit
        response = self._responder(data)
        if not isinstance(response, bytes):
            raise TypeError("scripted response must be bytes")
        self._pending.extend(response)
        return len(data)

    def read(self, size: int) -> bytes:
        """Return at most one configured fragment of the pending bytes.

        Direct call tree (static source order):
            read
            +-- len
            `-- bytes
        """
        if len(self._pending) == 0:
            return b""
        chunk_position = self._chunk_index
        if chunk_position >= len(self._chunks):
            chunk_position = len(self._chunks) - 1
        limit = self._chunks[chunk_position]
        self._chunk_index += 1
        count = size
        if limit < count:
            count = limit
        if len(self._pending) < count:
            count = len(self._pending)
        value = bytes(self._pending[:count])
        del self._pending[:count]
        return value

    def queue_incoming(self, data: bytes) -> None:
        """Stage endpoint bytes that arrive after a command response.

        Direct call tree (static source order):
            queue_incoming
            +-- isinstance
            +-- TypeError
            `-- self._pending.extend
        """
        if not isinstance(data, bytes):
            raise TypeError("queued incoming data must be bytes")
        self._pending.extend(data)

    @property
    def in_waiting(self) -> int:
        """Report how many response bytes can be read immediately.

        Direct call tree (static source order):
            in_waiting
            `-- len
        """
        return len(self._pending)

    @classmethod
    def acking(cls) -> "ScriptedBytePort":
        """Create a port that returns the normal typed response per command.

        Direct call tree (static source order):
            acking
            `-- cls
        """
        return cls(cls._default_response)

    @classmethod
    def acking_for(cls, endpoint_id: int) -> "ScriptedBytePort":
        """Create normal responses with the requested HELLO endpoint identity.

        Direct call tree (static source order):
            acking_for
            `-- cls
        """
        def responder(wire: bytes) -> bytes:
            """Reply to HELLO with the selected simulated endpoint identity and reuse normal replies otherwise.

            Inputs: wire.
            Returns: bytes.

            Direct call tree (static source order):
                responder
                +-- decode_wire
                +-- cls._default_response
                +-- bytes
                +-- pack_hello_report
                +-- Message
                `-- encode_wire
            """
            command = decode_wire(wire)
            if command.message_type is not MessageType.HELLO:
                return cls._default_response(wire)
            zero_hash = bytes(32)
            payload = pack_hello_report(
                endpoint_id,
                1,
                0x12,
                AttemptState.STANDBY,
                zero_hash,
                zero_hash,
                zero_hash,
            )
            response = Message(MessageType.HELLO_REPORT, command.msg_seq, payload)
            return encode_wire(response)

        return cls(responder)

    @classmethod
    def fragment_responses(cls, chunks: list[int]) -> "ScriptedBytePort":
        """Create a normal port with caller-selected read boundaries.

        Direct call tree (static source order):
            fragment_responses
            `-- cls
        """
        return cls(cls._default_response, chunks)

    @classmethod
    def drop_all(cls) -> "ScriptedBytePort":
        """Create a port that accepts commands but returns no response.

        Direct call tree (static source order):
            drop_all
            `-- cls
        """
        return cls(cls._empty_response)

    @classmethod
    def with_responder(cls, responder: Callable[[bytes], bytes]) -> "ScriptedBytePort":
        """Create a port backed by one explicit wire responder.

        Direct call tree (static source order):
            with_responder
            `-- cls
        """
        return cls(responder)

    @staticmethod
    def _empty_response(wire: bytes) -> bytes:
        """Return no bytes for a deliberately dropped command response.

        Direct call tree (static source order):
            _empty_response
            `-- [no direct function calls; local state/return only]
        """
        del wire
        return b""

    @staticmethod
    def _default_response(wire: bytes) -> bytes:
        """Build one protocol-valid normal response with the echoed sequence.

        Direct call tree (static source order):
            _default_response
            +-- decode_wire
            +-- pack_ack
            +-- bytes
            +-- pack_hello_report
            +-- unpack_load_tx
            +-- pack_tx_ready
            +-- unpack_arm_rx
            +-- pack_rx_armed
            +-- unpack_start_tx
            +-- pack_tx_started
            +-- unpack_get_attempt_status
            +-- pack_attempt_status
            +-- Message
            `-- encode_wire
        """
        command = decode_wire(wire)
        response_type = MessageType.ACK
        payload = pack_ack(command.message_type)
        if command.message_type is MessageType.HELLO:
            response_type = MessageType.HELLO_REPORT
            zero_hash = bytes(32)
            payload = pack_hello_report(
                1,
                1,
                0x12,
                AttemptState.STANDBY,
                zero_hash,
                zero_hash,
                zero_hash,
            )
        if command.message_type is MessageType.LOAD_TX:
            loaded = unpack_load_tx(command.payload)
            response_type = MessageType.TX_READY
            payload = pack_tx_ready(
                loaded.run_token,
                loaded.attempt_index,
                loaded.reg_frf_word,
            )
        if command.message_type is MessageType.ARM_RX:
            armed = unpack_arm_rx(command.payload)
            response_type = MessageType.RX_ARMED
            payload = pack_rx_armed(
                armed.run_token,
                armed.attempt_index,
                0x6D6000,
                armed.rx_window_ms,
            )
        if command.message_type is MessageType.START_TX:
            started = unpack_start_tx(command.payload)
            response_type = MessageType.TX_STARTED
            payload = pack_tx_started(started.run_token, started.attempt_index)
        if command.message_type is MessageType.GET_ATTEMPT_STATUS:
            query = unpack_get_attempt_status(command.payload)
            response_type = MessageType.ATTEMPT_STATUS
            payload = pack_attempt_status(
                query.run_token,
                query.attempt_index,
                AttemptState.TX_STARTED,
                0,
            )
        response = Message(response_type, command.msg_seq, payload)
        return encode_wire(response)


class EndpointState(Enum):
    """Name the visible state of one fake Nano and SX1278 radio."""

    STANDBY = "standby"
    RUN_CONFIGURED = "run_configured"
    TX_LOADED = "tx_loaded"
    RX_ARMED = "rx_armed"
    TX_STARTED = "tx_started"
    TX_DONE = "tx_done"
    RX_TERMINAL = "rx_terminal"
    ERROR = "error"


@dataclass(frozen=True)
class FaultScript:
    """Select deterministic endpoint faults by run token and attempt index."""

    drop_tx_started: frozenset[tuple[int, int]] = frozenset()
    reset_on_attempt: frozenset[tuple[int, int]] = frozenset()
    frf_readback_delta: int = 0
    profile_readback_delta: int = 0
    pa_readback_delta: int = 0
    register_readback_delta: int = 0
    pa_register_readback_delta: int = 0
    rx_terminal_by_attempt: dict[tuple[int, int], str] = field(
        default_factory=dict
    )
    received_payload_by_attempt: dict[tuple[int, int], bytes] = field(
        default_factory=dict
    )
    corrupt_response_by_attempt: frozenset[tuple[int, int]] = frozenset()
    drop_response_by_attempt: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class AttemptExecution:
    """Summarize one coupled fake-radio action and its single RX terminal."""

    tx_endpoint_id: int
    rx_endpoint_id: int
    run_token: int
    attempt_index: int
    reg_frf_word: int
    tx_started_visible: bool
    terminal_name: str
    phy_crc_ok: bool | None
    received_payload: bytes
    terminal_payload: object


class FakeNanoEndpoint:
    """Apply version-1 commands to one deterministic in-memory Nano state."""

    def __init__(
        self,
        endpoint_id: int,
        fault_script: FaultScript | None = None,
    ) -> None:
        """Create one stable endpoint identity in standby with an empty cache.

        Direct call tree (static source order):
            __init__
            `-- FaultScript
        """
        if fault_script is None:
            fault_script = FaultScript()
        self.endpoint_id = endpoint_id
        self.fault_script = fault_script
        self.boot_count = 1
        self.state = EndpointState.STANDBY
        self.radio_transmit_count = 0
        self.last_frf_word = 0x6D6000
        self.last_frame = b""
        self.active_context: tuple[int, int] | None = None
        self.profile_code = ProfileCode.LORA
        self.pa_command_dbm = 2
        self.reg_ocp = 0
        self._cached_command: tuple[
            int, MessageType, int, object | None
        ] | None = None

    def _error_context(self) -> tuple[int, int]:
        """Return active IDs or the paired all-ones no-attempt sentinel.

        Direct call tree (static source order):
            _error_context
            `-- [no direct function calls; local state/return only]
        """
        if self.active_context is None:
            return (0xFFFFFFFF, 0xFFFFFFFF)
        return self.active_context

    def _make_error(
        self,
        related_type: MessageType,
        error_code: ErrorCode,
        detail: int,
    ) -> EndpointErrorPayload:
        """Build one typed endpoint error with current context evidence.

        Direct call tree (static source order):
            _make_error
            +-- self._error_context
            `-- EndpointErrorPayload
        """
        context = self._error_context()
        return EndpointErrorPayload(
            context[0],
            context[1],
            related_type,
            error_code,
            detail,
        )

    def _command_crc(
        self,
        message_type: MessageType,
        msg_seq: int,
        payload: bytes,
    ) -> int:
        """Derive the exact message CRC through the production wire codec.

        Direct call tree (static source order):
            _command_crc
            +-- Message
            +-- encode_wire
            +-- decode_wire
            `-- int.from_bytes
        """
        message = Message(message_type, msg_seq, payload)
        wire = encode_wire(message)
        decoded = decode_wire(wire)
        crc_bytes = decoded.decoded_bytes[-2:]
        return int.from_bytes(crc_bytes, "big")

    def _cached_result(
        self,
        message_type: MessageType,
        msg_seq: int,
        payload: bytes,
    ) -> tuple[bool, object | None]:
        """Replay identical bytes or reject changed bytes at one sequence.

        Direct call tree (static source order):
            _cached_result
            +-- self._command_crc
            `-- self._make_error
        """
        if self._cached_command is None:
            return (False, None)
        cached = self._cached_command
        if cached[0] != msg_seq:
            return (False, None)
        command_crc = self._command_crc(message_type, msg_seq, payload)
        same_type = cached[1] is message_type
        same_crc = cached[2] == command_crc
        if same_type:
            if same_crc:
                return (True, cached[3])
        error = self._make_error(
            message_type,
            ErrorCode.CONTEXT_MISMATCH,
            msg_seq,
        )
        return (True, error)

    def _remember(
        self,
        message_type: MessageType,
        msg_seq: int,
        payload: bytes,
        result: object | None,
    ) -> object | None:
        """Cache the exact command identity and its first returned result.

        Direct call tree (static source order):
            _remember
            `-- self._command_crc
        """
        command_crc = self._command_crc(message_type, msg_seq, payload)
        self._cached_command = (msg_seq, message_type, command_crc, result)
        return result

    def _reset_endpoint(self) -> None:
        """Model a reboot that clears radio state but retains physical identity.

        Direct call tree (static source order):
            _reset_endpoint
            `-- [no direct function calls; local state/return only]
        """
        self.boot_count += 1
        self.state = EndpointState.STANDBY
        self.active_context = None
        self.last_frame = b""
        self._cached_command = None

    def _hello_report(self) -> HelloReportPayload:
        """Return stable identity and build hashes for a HELLO command.

        Direct call tree (static source order):
            _hello_report
            +-- self._attempt_state
            +-- bytes
            `-- HelloReportPayload
        """
        state = self._attempt_state()
        zero_hash = bytes(32)
        return HelloReportPayload(
            self.endpoint_id,
            self.boot_count,
            0x12,
            state,
            zero_hash,
            zero_hash,
            zero_hash,
        )

    def _attempt_state(self) -> AttemptState:
        """Map the readable fake state onto the frozen wire status enum.

        Direct call tree (static source order):
            _attempt_state
            `-- [no direct function calls; local state/return only]
        """
        if self.state is EndpointState.TX_LOADED:
            return AttemptState.TX_LOADED
        if self.state is EndpointState.RX_ARMED:
            return AttemptState.RX_ARMED
        if self.state is EndpointState.TX_STARTED:
            return AttemptState.TX_STARTED
        if self.state is EndpointState.TX_DONE:
            return AttemptState.TX_DONE
        if self.state is EndpointState.RX_TERMINAL:
            return AttemptState.RX_PACKET
        if self.state is EndpointState.ERROR:
            return AttemptState.ERROR
        return AttemptState.STANDBY

    def _config_report(self, related_type: MessageType) -> ConfigReportPayload:
        """Return deterministic profile, PA, OCP, and register read-backs.

        Direct call tree (static source order):
            _config_report
            +-- ProfileCode
            +-- RegisterValue
            `-- ConfigReportPayload
        """
        profile_value = self.profile_code.value + self.fault_script.profile_readback_delta
        if profile_value < 0:
            profile_value = 0
        if profile_value > 5:
            profile_value = 5
        profile_code = ProfileCode(profile_value)
        pa_value = self.pa_command_dbm + self.fault_script.pa_readback_delta
        if related_type is MessageType.APPLY_PROFILE:
            register_value = 0x12 + self.fault_script.register_readback_delta
            register_value = register_value & 0xFF
            registers = (RegisterValue(0x01, register_value),)
        else:
            pa_config = 0xFF + self.fault_script.pa_register_readback_delta
            pa_config = pa_config & 0xFF
            registers = (
                RegisterValue(0x09, pa_config),
                RegisterValue(0x4D, 0x87),
                RegisterValue(0x0B, self.reg_ocp),
            )
        return ConfigReportPayload(
            related_type,
            profile_code,
            pa_value,
            0xFF,
            0x87,
            self.reg_ocp,
            registers,
        )

    def attempt_status(
        self,
        run_token: int,
        attempt_index: int,
    ) -> AttemptStatusPayload:
        """Report current state only when the requested context still matches.

        Direct call tree (static source order):
            attempt_status
            +-- AttemptStatusPayload
            `-- self._attempt_state
        """
        requested = (run_token, attempt_index)
        if self.active_context != requested:
            return AttemptStatusPayload(
                run_token,
                attempt_index,
                AttemptState.ERROR,
                ErrorCode.CONTEXT_MISMATCH.value,
            )
        return AttemptStatusPayload(
            run_token,
            attempt_index,
            self._attempt_state(),
            0,
        )

    def accept(
        self,
        message_type: MessageType,
        msg_seq: int,
        payload: bytes,
    ) -> object | None:
        """Validate one typed command and apply its state change at most once.

        Project choice: validate command context and cache each result so
        replaying a serial command cannot apply the state change twice.

        Processing flow:
            Exact sequence cache -> typed payload validation -> state/context gate
                -> one state change -> cache response or injected dropped response

        Direct call tree (static source order):
            accept
            +-- self._cached_result
            +-- unpack_hello
            +-- self._hello_report
            +-- self._remember
            +-- unpack_reset_to_standby
            +-- AckPayload
            +-- self._make_error
            +-- unpack_apply_profile
            +-- self._config_report
            +-- unpack_set_pa
            +-- unpack_load_tx
            +-- self._reset_endpoint
            +-- TxReadyPayload
            +-- unpack_arm_rx
            +-- RxArmedPayload
            +-- unpack_start_tx
            +-- TxStartedPayload
            +-- unpack_get_attempt_status
            +-- self.attempt_status
            `-- unpack_cancel_attempt
        """
        cached, cached_result = self._cached_result(
            message_type,
            msg_seq,
            payload,
        )
        if cached:
            return cached_result

        result: object | None
        if message_type is MessageType.HELLO:
            unpack_hello(payload)
            result = self._hello_report()
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.RESET_TO_STANDBY:
            unpack_reset_to_standby(payload)
            self.state = EndpointState.STANDBY
            self.active_context = None
            self.last_frf_word = 0x6D6000
            result = AckPayload(message_type, 0)
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.APPLY_PROFILE:
            configuration_allowed = self.state is EndpointState.STANDBY
            if self.state is EndpointState.RUN_CONFIGURED:
                configuration_allowed = True
            if not configuration_allowed:
                result = self._make_error(message_type, ErrorCode.BAD_STATE, 0)
                return self._remember(message_type, msg_seq, payload, result)
            applied = unpack_apply_profile(payload)
            self.profile_code = applied.profile_code
            self.state = EndpointState.RUN_CONFIGURED
            result = self._config_report(message_type)
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.SET_PA:
            configuration_allowed = self.state is EndpointState.STANDBY
            if self.state is EndpointState.RUN_CONFIGURED:
                configuration_allowed = True
            if not configuration_allowed:
                result = self._make_error(message_type, ErrorCode.BAD_STATE, 0)
                return self._remember(message_type, msg_seq, payload, result)
            applied_pa = unpack_set_pa(payload)
            self.pa_command_dbm = applied_pa.pa_command_dbm
            self.reg_ocp = applied_pa.reg_ocp
            self.state = EndpointState.RUN_CONFIGURED
            result = self._config_report(message_type)
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.LOAD_TX:
            if self.state is not EndpointState.RUN_CONFIGURED:
                result = self._make_error(message_type, ErrorCode.BAD_STATE, 0)
                return self._remember(message_type, msg_seq, payload, result)
            loaded = unpack_load_tx(payload)
            context = (loaded.run_token, loaded.attempt_index)
            if context in self.fault_script.reset_on_attempt:
                self.active_context = context
                result = self._make_error(
                    message_type,
                    ErrorCode.ENDPOINT_RESET,
                    self.boot_count + 1,
                )
                self._reset_endpoint()
                return result
            self.active_context = context
            self.last_frf_word = loaded.reg_frf_word
            self.last_frame = loaded.frame
            self.state = EndpointState.TX_LOADED
            readback = loaded.reg_frf_word + self.fault_script.frf_readback_delta
            result = TxReadyPayload(
                loaded.run_token,
                loaded.attempt_index,
                readback,
            )
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.ARM_RX:
            if self.state is not EndpointState.RUN_CONFIGURED:
                result = self._make_error(message_type, ErrorCode.BAD_STATE, 0)
                return self._remember(message_type, msg_seq, payload, result)
            armed = unpack_arm_rx(payload)
            self.active_context = (armed.run_token, armed.attempt_index)
            self.last_frf_word = 0x6D6000
            self.state = EndpointState.RX_ARMED
            readback = self.last_frf_word + self.fault_script.frf_readback_delta
            result = RxArmedPayload(
                armed.run_token,
                armed.attempt_index,
                readback,
                armed.rx_window_ms,
            )
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.START_TX:
            started = unpack_start_tx(payload)
            context = (started.run_token, started.attempt_index)
            if self.state is not EndpointState.TX_LOADED:
                result = self._make_error(message_type, ErrorCode.BAD_STATE, 0)
                return self._remember(message_type, msg_seq, payload, result)
            if self.active_context != context:
                result = self._make_error(
                    message_type,
                    ErrorCode.CONTEXT_MISMATCH,
                    0,
                )
                return self._remember(message_type, msg_seq, payload, result)
            self.radio_transmit_count += 1
            self.state = EndpointState.TX_STARTED
            result = TxStartedPayload(started.run_token, started.attempt_index)
            if context in self.fault_script.drop_tx_started:
                result = None
            if context in self.fault_script.drop_response_by_attempt:
                result = None
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.GET_ATTEMPT_STATUS:
            query = unpack_get_attempt_status(payload)
            result = self.attempt_status(query.run_token, query.attempt_index)
            return self._remember(message_type, msg_seq, payload, result)
        if message_type is MessageType.CANCEL_ATTEMPT:
            cancelled = unpack_cancel_attempt(payload)
            context = (cancelled.run_token, cancelled.attempt_index)
            if self.active_context != context:
                result = self._make_error(
                    message_type,
                    ErrorCode.CONTEXT_MISMATCH,
                    0,
                )
                return self._remember(message_type, msg_seq, payload, result)
            self.state = EndpointState.STANDBY
            self.active_context = None
            result = AckPayload(message_type, 0)
            return self._remember(message_type, msg_seq, payload, result)
        result = self._make_error(message_type, ErrorCode.UNKNOWN_TYPE, 0)
        return self._remember(message_type, msg_seq, payload, result)

    def _encode_result(self, result: object) -> tuple[MessageType, bytes]:
        """Convert one typed fake result back to its exact version-1 payload.

        Direct call tree (static source order):
            _encode_result
            +-- isinstance
            +-- pack_ack
            +-- pack_hello_report
            +-- register_pairs.append
            +-- pack_config_report
            +-- tuple
            +-- pack_tx_ready
            +-- pack_rx_armed
            +-- pack_tx_started
            +-- pack_tx_done
            +-- pack_rx_packet
            +-- pack_rx_timeout
            +-- pack_attempt_status
            +-- pack_endpoint_error
            `-- TypeError
        """
        if isinstance(result, AckPayload):
            return (MessageType.ACK, pack_ack(result.related_type, result.status))
        if isinstance(result, HelloReportPayload):
            payload = pack_hello_report(
                result.endpoint_id,
                result.boot_count,
                result.reg_version,
                result.state,
                result.firmware_hash,
                result.profile_table_hash,
                result.board_profile_hash,
            )
            return (MessageType.HELLO_REPORT, payload)
        if isinstance(result, ConfigReportPayload):
            register_pairs: list[tuple[int, int]] = []
            for register in result.registers:
                register_pairs.append((register.address, register.value))
            payload = pack_config_report(
                result.related_type,
                result.profile_code,
                result.pa_command_dbm,
                result.reg_pa_config,
                result.reg_pa_dac,
                result.reg_ocp,
                tuple(register_pairs),
            )
            return (MessageType.CONFIG_REPORT, payload)
        if isinstance(result, TxReadyPayload):
            payload = pack_tx_ready(
                result.run_token,
                result.attempt_index,
                result.reg_frf_readback,
            )
            return (MessageType.TX_READY, payload)
        if isinstance(result, RxArmedPayload):
            payload = pack_rx_armed(
                result.run_token,
                result.attempt_index,
                result.reg_frf_readback,
                result.rx_window_ms,
            )
            return (MessageType.RX_ARMED, payload)
        if isinstance(result, TxStartedPayload):
            payload = pack_tx_started(result.run_token, result.attempt_index)
            return (MessageType.TX_STARTED, payload)
        if isinstance(result, TxDonePayload):
            payload = pack_tx_done(result.run_token, result.attempt_index)
            return (MessageType.TX_DONE, payload)
        if isinstance(result, RxPacketPayload):
            payload = pack_rx_packet(
                result.run_token,
                result.attempt_index,
                result.phy_crc_ok,
                result.metrics_flags,
                result.rssi_raw,
                result.snr_raw,
                result.packet,
            )
            return (MessageType.RX_PACKET, payload)
        if isinstance(result, RxTimeoutPayload):
            payload = pack_rx_timeout(result.run_token, result.attempt_index)
            return (MessageType.RX_TIMEOUT, payload)
        if isinstance(result, AttemptStatusPayload):
            payload = pack_attempt_status(
                result.run_token,
                result.attempt_index,
                result.state,
                result.last_error_code,
            )
            return (MessageType.ATTEMPT_STATUS, payload)
        if isinstance(result, EndpointErrorPayload):
            payload = pack_endpoint_error(
                result.run_token,
                result.attempt_index,
                result.related_type,
                result.error_code,
                result.detail,
            )
            return (MessageType.ENDPOINT_ERROR, payload)
        raise TypeError("fake endpoint result has no protocol encoding")

    def respond_wire(self, wire: bytes) -> bytes:
        """Decode one command wire and encode its cached typed response.

        Direct call tree (static source order):
            respond_wire
            +-- decode_wire
            +-- self.accept
            +-- self._encode_result
            +-- Message
            +-- encode_wire
            +-- bytearray
            `-- bytes
        """
        command = decode_wire(wire)
        result = self.accept(command.message_type, command.msg_seq, command.payload)
        if result is None:
            return b""
        response_type, response_payload = self._encode_result(result)
        response = Message(response_type, command.msg_seq, response_payload)
        encoded = encode_wire(response)
        if self.active_context is not None:
            if self.active_context in self.fault_script.corrupt_response_by_attempt:
                changed = bytearray(encoded)
                changed[-2] = changed[-2] ^ 1
                encoded = bytes(changed)
        return encoded


class FakeEndpointPair:
    """Couple two stable fake endpoints while allowing per-attempt role swap."""

    def __init__(
        self,
        endpoint_ids: tuple[int, int] = (101, 202),
        fault_script: FaultScript | None = None,
    ) -> None:
        """Create endpoint A and B with one shared deterministic fault script.

        Direct call tree (static source order):
            __init__
            +-- FaultScript
            `-- FakeNanoEndpoint
        """
        if fault_script is None:
            fault_script = FaultScript()
        self.fault_script = fault_script
        self._a = FakeNanoEndpoint(endpoint_ids[0], fault_script)
        self._b = FakeNanoEndpoint(endpoint_ids[1], fault_script)
        self.tx = self._a
        self.rx = self._b
        self._next_sequence_by_endpoint = {
            endpoint_ids[0]: 0,
            endpoint_ids[1]: 0,
        }
        self._terminal_counts: dict[tuple[int, int], int] = {}
        self.command_types: list[str] = []
        self.tx_history: list[tuple[bytes, int]] = []
        self._ports_by_endpoint: dict[int, CoupledEndpointPort] = {}
        self._deferred_start: tuple[int, int, int, int] | None = None

    def endpoint(self, endpoint_id: int) -> FakeNanoEndpoint:
        """Return one endpoint by its stable physical identity.

        Direct call tree (static source order):
            endpoint
            `-- KeyError
        """
        if self._a.endpoint_id == endpoint_id:
            return self._a
        if self._b.endpoint_id == endpoint_id:
            return self._b
        raise KeyError("unknown fake endpoint identity")

    def _next_sequence(self, endpoint: FakeNanoEndpoint) -> int:
        """Allocate and wrap one independent sequence for direct fake calls.

        Direct call tree (static source order):
            _next_sequence
            `-- [no direct function calls; local state/return only]
        """
        current = self._next_sequence_by_endpoint[endpoint.endpoint_id]
        self._next_sequence_by_endpoint[endpoint.endpoint_id] = (current + 1) & 0xFFFF
        return current

    def _select_roles(
        self,
        direction: str,
    ) -> tuple[FakeNanoEndpoint, FakeNanoEndpoint]:
        """Map a direction label to TX and RX without changing endpoint IDs.

        Direct call tree (static source order):
            _select_roles
            `-- ValueError
        """
        if direction == "A_to_B":
            return (self._a, self._b)
        if direction == "B_to_A":
            return (self._b, self._a)
        raise ValueError("direction must be A_to_B or B_to_A")

    def _make_terminal(
        self,
        receiver: FakeNanoEndpoint,
        run_token: int,
        attempt_index: int,
        frame: bytes,
    ) -> tuple[str, bool | None, bytes, object]:
        """Create exactly one scripted receive terminal for an RF start.

        Direct call tree (static source order):
            _make_terminal
            +-- self.fault_script.rx_terminal_by_attempt.get
            +-- RxTimeoutPayload
            +-- RxPacketPayload
            +-- len
            `-- self._terminal_counts.get
        """
        context = (run_token, attempt_index)
        terminal_name = self.fault_script.rx_terminal_by_attempt.get(
            context,
            "ok",
        )
        received_payload = frame
        if context in self.fault_script.received_payload_by_attempt:
            received_payload = self.fault_script.received_payload_by_attempt[context]
        phy_crc_ok: bool | None = True
        if terminal_name == "timeout":
            phy_crc_ok = None
            received_payload = b""
            terminal = RxTimeoutPayload(run_token, attempt_index)
        else:
            if terminal_name == "phy_crc":
                phy_crc_ok = False
            if terminal_name == "wrong_length":
                received_payload = received_payload[:-1]
            phy_crc_code = 1
            if phy_crc_ok is False:
                phy_crc_code = 0
            terminal = RxPacketPayload(
                run_token,
                attempt_index,
                phy_crc_code,
                len(received_payload),
                0x03,
                0xA1,
                -8,
                received_payload,
            )
        receiver.state = EndpointState.RX_TERMINAL
        receiver.active_context = context
        count = self._terminal_counts.get(context, 0)
        self._terminal_counts[context] = count + 1
        return (terminal_name, phy_crc_ok, received_payload, terminal)

    def execute_attempt(
        self,
        direction: str,
        run_token: int,
        attempt_index: int,
        reg_frf_word: int,
        frame: bytes,
    ) -> AttemptExecution:
        """Run LOAD_TX, ARM_RX, START_TX, and one coupled RX terminal.

        Project choice: pair transmitter and receiver state transitions so
        each scripted attempt has one start and one receiver outcome.

        Processing flow:
            Direction -> stable TX/RX roles -> load and arm -> one RF start
                -> one scripted RX terminal -> readable attempt summary

        Direct call tree (static source order):
            execute_attempt
            +-- self._select_roles
            +-- endpoint.accept
            +-- self._next_sequence
            +-- pack_apply_profile
            +-- bytes
            +-- pack_set_pa
            +-- pack_load_tx
            +-- transmitter.accept
            +-- pack_arm_rx
            +-- receiver.accept
            +-- pack_start_tx
            +-- isinstance
            +-- self._make_terminal
            `-- AttemptExecution
        """
        transmitter, receiver = self._select_roles(direction)
        self.tx = transmitter
        self.rx = receiver
        endpoints = (transmitter, receiver)
        for endpoint in endpoints:
            endpoint.accept(
                MessageType.RESET_TO_STANDBY,
                self._next_sequence(endpoint),
                b"",
            )
            endpoint.accept(
                MessageType.APPLY_PROFILE,
                self._next_sequence(endpoint),
                pack_apply_profile(ProfileCode.LORA, bytes(32)),
            )
            endpoint.accept(
                MessageType.SET_PA,
                self._next_sequence(endpoint),
                pack_set_pa(2, 0),
            )
        load_payload = pack_load_tx(
            run_token,
            attempt_index,
            reg_frf_word,
            frame,
        )
        transmitter.accept(
            MessageType.LOAD_TX,
            self._next_sequence(transmitter),
            load_payload,
        )
        arm_payload = pack_arm_rx(run_token, attempt_index, 5000)
        receiver.accept(
            MessageType.ARM_RX,
            self._next_sequence(receiver),
            arm_payload,
        )
        start_payload = pack_start_tx(run_token, attempt_index)
        started = transmitter.accept(
            MessageType.START_TX,
            self._next_sequence(transmitter),
            start_payload,
        )
        tx_started_visible = isinstance(started, TxStartedPayload)
        terminal_name, phy_crc_ok, received_payload, terminal = self._make_terminal(
            receiver,
            run_token,
            attempt_index,
            frame,
        )
        transmitter.state = EndpointState.STANDBY
        transmitter.active_context = None
        receiver.state = EndpointState.STANDBY
        receiver.active_context = None
        return AttemptExecution(
            transmitter.endpoint_id,
            receiver.endpoint_id,
            run_token,
            attempt_index,
            reg_frf_word,
            tx_started_visible,
            terminal_name,
            phy_crc_ok,
            received_payload,
            terminal,
        )

    def terminal_count(self, run_token: int, attempt_index: int) -> int:
        """Return how many receive terminals were created for one context.

        Direct call tree (static source order):
            terminal_count
            `-- self._terminal_counts.get
        """
        context = (run_token, attempt_index)
        return self._terminal_counts.get(context, 0)

    @property
    def total_radio_transmit_count(self) -> int:
        """Return the total physical TX actions across both stable endpoints.

        Direct call tree (static source order):
            total_radio_transmit_count
            `-- [no direct function calls; local state/return only]
        """
        return self._a.radio_transmit_count + self._b.radio_transmit_count

    def make_ports(self) -> tuple["CoupledEndpointPort", "CoupledEndpointPort"]:
        """Create two byte ports coupled through one simulated conducted link.

        Direct call tree (static source order):
            make_ports
            `-- CoupledEndpointPort
        """
        port_a = CoupledEndpointPort(self, self._a)
        port_b = CoupledEndpointPort(self, self._b)
        self._ports_by_endpoint = {
            self._a.endpoint_id: port_a,
            self._b.endpoint_id: port_b,
        }
        return (port_a, port_b)

    def _other_endpoint(self, endpoint: FakeNanoEndpoint) -> FakeNanoEndpoint:
        """Return the other physical endpoint without changing either identity.

        Direct call tree (static source order):
            _other_endpoint
            `-- [no direct function calls; local state/return only]
        """
        if endpoint is self._a:
            return self._b
        return self._a

    def _queue_terminal_events(
        self,
        transmitter: FakeNanoEndpoint,
        start_sequence: int,
        run_token: int,
        attempt_index: int,
    ) -> None:
        """Queue one TX_DONE and one RX terminal with their trigger sequences.

        Direct call tree (static source order):
            _queue_terminal_events
            +-- self._other_endpoint
            +-- receiver_port.arm_sequence_by_context.get
            +-- self._make_terminal
            +-- Message
            +-- pack_tx_done
            +-- receiver._encode_result
            +-- transmitter_port.queue_incoming
            +-- encode_wire
            +-- receiver_port.queue_incoming
            `-- self.tx_history.append
        """
        receiver = self._other_endpoint(transmitter)
        context = (run_token, attempt_index)
        if receiver.active_context != context:
            return None
        transmitter_port = self._ports_by_endpoint[transmitter.endpoint_id]
        receiver_port = self._ports_by_endpoint[receiver.endpoint_id]
        arm_sequence = receiver_port.arm_sequence_by_context.get(context)
        if arm_sequence is None:
            return None
        terminal_values = self._make_terminal(
            receiver,
            run_token,
            attempt_index,
            transmitter.last_frame,
        )
        terminal = terminal_values[3]
        tx_done = Message(
            MessageType.TX_DONE,
            start_sequence,
            pack_tx_done(run_token, attempt_index),
        )
        terminal_type, terminal_payload = receiver._encode_result(terminal)
        rx_message = Message(terminal_type, arm_sequence, terminal_payload)
        transmitter_port.queue_incoming(encode_wire(tx_done))
        receiver_port.queue_incoming(encode_wire(rx_message))
        self.tx_history.append((transmitter.last_frame, transmitter.last_frf_word))
        transmitter.state = EndpointState.RUN_CONFIGURED
        transmitter.active_context = None
        receiver.state = EndpointState.RUN_CONFIGURED
        receiver.active_context = None


class CoupledEndpointPort:
    """Expose one fake endpoint as a nonblocking codec-backed serial port."""

    def __init__(self, pair: FakeEndpointPair, endpoint: FakeNanoEndpoint) -> None:
        """Create one empty receive queue for a stable fake endpoint.

        Direct call tree (static source order):
            __init__
            `-- bytearray
        """
        self.pair = pair
        self.endpoint = endpoint
        self.pending = bytearray()
        self.writes: list[bytes] = []
        self.arm_sequence_by_context: dict[tuple[int, int], int] = {}
        self.closed = False

    def close(self) -> None:
        """Mark this simulated serial endpoint as closed.

        Direct call tree (static source order):
            close
            `-- [no direct function calls; local state/return only]
        """
        self.closed = True

    def write(self, data: bytes) -> int:
        """Apply one command and queue its direct and asynchronous responses.

        Direct call tree (static source order):
            write
            +-- self.writes.append
            +-- decode_wire
            +-- self.pair.command_types.append
            +-- unpack_arm_rx
            +-- self.endpoint.accept
            +-- self.endpoint._encode_result
            +-- Message
            +-- self.pending.extend
            +-- encode_wire
            +-- unpack_start_tx
            +-- self.pair._queue_terminal_events
            `-- len
        """
        self.writes.append(data)
        command = decode_wire(data)
        self.pair.command_types.append(command.message_type.name)
        if command.message_type is MessageType.ARM_RX:
            armed = unpack_arm_rx(command.payload)
            context = (armed.run_token, armed.attempt_index)
            self.arm_sequence_by_context[context] = command.msg_seq
        transmit_count_before = self.endpoint.radio_transmit_count
        result = self.endpoint.accept(
            command.message_type,
            command.msg_seq,
            command.payload,
        )
        if result is not None:
            response_type, response_payload = self.endpoint._encode_result(result)
            response = Message(response_type, command.msg_seq, response_payload)
            self.pending.extend(encode_wire(response))
        if command.message_type is MessageType.START_TX:
            started = unpack_start_tx(command.payload)
            action_happened = self.endpoint.radio_transmit_count > transmit_count_before
            if action_happened:
                if result is None:
                    self.pair._deferred_start = (
                        self.endpoint.endpoint_id,
                        command.msg_seq,
                        started.run_token,
                        started.attempt_index,
                    )
                else:
                    self.pair._queue_terminal_events(
                        self.endpoint,
                        command.msg_seq,
                        started.run_token,
                        started.attempt_index,
                    )
        if command.message_type is MessageType.GET_ATTEMPT_STATUS:
            deferred = self.pair._deferred_start
            if deferred is not None:
                endpoint_id, sequence, run_token, attempt_index = deferred
                if endpoint_id == self.endpoint.endpoint_id:
                    self.pair._queue_terminal_events(
                        self.endpoint,
                        sequence,
                        run_token,
                        attempt_index,
                    )
                    self.pair._deferred_start = None
        return len(data)

    def read(self, size: int) -> bytes:
        """Remove at most size bytes from the immediately available queue.

        Direct call tree (static source order):
            read
            +-- len
            `-- bytes
        """
        count = size
        if count > len(self.pending):
            count = len(self.pending)
        value = bytes(self.pending[:count])
        del self.pending[:count]
        return value

    def queue_incoming(self, data: bytes) -> None:
        """Append one already encoded endpoint event to the receive queue.

        Direct call tree (static source order):
            queue_incoming
            `-- self.pending.extend
        """
        self.pending.extend(data)

    @property
    def in_waiting(self) -> int:
        """Return the number of immediately readable response bytes.

        Direct call tree (static source order):
            in_waiting
            `-- len
        """
        return len(self.pending)
