"""Deterministic one-command-at-a-time transport for two Nano serial links."""

from __future__ import annotations

from typing import Generic, NoReturn, Protocol, TYPE_CHECKING, TypeVar


import time
from dataclasses import dataclass
from host.common.runtime_config import load_settings

if TYPE_CHECKING:
    # Editors need the concrete port API; importing this module must not load
    # the optional hardware backend before open_nano_port() is called.
    from serial import Serial

from host.radio.serial_protocol import (
    BAUD_RATE,
    INTER_BYTE_TIMEOUT_MS,
    MAX_COBS_FRAGMENT_LENGTH,
    MAX_WIRE_LENGTH,
    AttemptState,
    ErrorCode,
    Message,
    MessageType,
    ProtocolError,
    StreamDecoder,
    encode_wire,
    pack_get_attempt_status,
    unpack_arm_rx,
    unpack_attempt_status,
    unpack_endpoint_error,
    unpack_hello_report,
    unpack_rx_packet,
    unpack_rx_timeout,
    unpack_start_tx,
    unpack_tx_done,
)

PortT = TypeVar("PortT", bound="BytePort")


_TRANSPORT_SETTINGS = load_settings("serial_runtime")["transport"]
SERIAL_READ_POLL_MS = int(_TRANSPORT_SETTINGS["read_poll_ms"])

ASYNC_EVENT_TYPES = (
    MessageType.TX_DONE,
    MessageType.RX_PACKET,
    MessageType.RX_TIMEOUT,
    MessageType.ENDPOINT_ERROR,
)


class BytePort(Protocol):
    """Describe the small byte-oriented API required from a serial port."""

    def write(self, data: bytes, /) -> int | None:
        """Write bytes and return the accepted count, or None if unavailable.

        Direct call tree (static source order):
            write
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError

    def read(self, size: int) -> bytes:
        """Read up to size currently available bytes without blocking.

        Direct call tree (static source order):
            read
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError

    @property
    def in_waiting(self) -> int:
        """Return the number of bytes available for a nonblocking read.

        Direct call tree (static source order):
            in_waiting
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError


class NanoPort(BytePort, Protocol):
    """Describe an owned local or remote Nano link that can be closed."""

    def reset_input_buffer(self) -> None:
        """Discard pending startup bytes before the first protocol command.

        Direct call tree (static source order):
            reset_input_buffer
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError

    def close(self) -> None:
        """Release the underlying control connection and its local resources.

        Direct call tree (static source order):
            close
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError


class Clock(Protocol):
    """Describe the monotonic, UTC, and short-sleep clock operations."""

    def monotonic_ns(self) -> int:
        """Return monotonic nanoseconds for deadlines and evidence.

        Direct call tree (static source order):
            monotonic_ns
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError

    def utc_ns(self) -> int:
        """Return signed UTC nanoseconds for evidence correlation.

        Direct call tree (static source order):
            utc_ns
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError

    def sleep_ms(self, milliseconds: int) -> None:
        """Wait or advance by a small whole-millisecond duration.

        Direct call tree (static source order):
            sleep_ms
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError


class WireEvidence(Protocol):
    """Describe the append-only raw serial evidence operation."""

    def append_wire(
        self,
        monotonic_ns: int,
        utc_ns: int,
        endpoint_id: int,
        direction: int,
        wire_bytes: bytes,
        /,
    ) -> int:
        """Append one complete wire message and return its event index.

        Direct call tree (static source order):
            append_wire
            `-- [no direct function calls; local state/return only]
        """
        raise NotImplementedError


class CommandTimeout(TimeoutError):
    """Report that a host command deadline expired without a response."""


class UnsafeRetry(RuntimeError):
    """Report an action that could start an RF transmission twice."""


class ProceduralFault(RuntimeError):
    """Report evidence that invalidates the laboratory procedure."""


class ResponseMismatch(ProceduralFault):
    """Report a response that cannot belong to the outstanding command."""


class SerialProtocolFailure(ProceduralFault):
    """Preserve a classified serial parser failure as a procedural fault."""

    def __init__(self, error: ProtocolError) -> None:
        """Copy the stable protocol code and detail from the parser error.

        Processing flow:
            Parser failure -> preserve its stable code and detail
            -> describe the timeout duration when the detail is interbyte_timeout
            -> initialize the transport exception with the selected explanation.

        Direct call tree (static source order):
            __init__
            +-- str
            +-- super
            `-- super(...).__init__
        """
        self.code = error.code
        self.detail = error.detail
        message = "serial protocol failure: " + str(error)
        if error.detail == "interbyte_timeout":
            message = "serial inter-byte timeout after 250 ms"
        super().__init__(message)


class EndpointReportedError(ProceduralFault):
    """Preserve one typed ENDPOINT_ERROR returned by a Nano endpoint."""

    def __init__(self, message: Message) -> None:
        """Decode the endpoint's context, related command, code, and detail.

        Processing flow:
            ENDPOINT_ERROR payload -> decode attempt context, related command, code and detail
            -> for a START_TX register readback error, expose the register and actual value
            -> retain decoded fields and initialize the exception text for the operator.

        Direct call tree (static source order):
            __init__
            +-- unpack_endpoint_error
            +-- int
            +-- super
            `-- super(...).__init__
        """
        decoded = unpack_endpoint_error(message.payload)
        self.message = message
        self.run_token = decoded.run_token
        self.attempt_index = decoded.attempt_index
        self.related_type = decoded.related_type
        self.error_code = decoded.error_code
        self.detail = decoded.detail
        text = "endpoint reported " + decoded.error_code.name
        text += f"; command=0x{int(decoded.related_type):02X}"
        if decoded.related_type == MessageType.START_TX:
            text += " (START_TX)"
            # Project START_TX diagnostics pack register address and readback into
            # the existing detail field. Older firmware reports zero (unknown).
            if decoded.error_code == ErrorCode.REGISTER_READBACK and decoded.detail != 0:
                register_address = decoded.detail >> 8
                actual_value = decoded.detail & 0xFF
                text += f"; register=0x{register_address:02X}; actual=0x{actual_value:02X}"
        text += f"; detail=0x{decoded.detail:04X}"
        super().__init__(text)


@dataclass(frozen=True)
class OutstandingCommand:
    """Remember the exact command occupying one endpoint command slot."""

    msg_seq: int
    message_type: MessageType
    payload: bytes
    wire_bytes: bytes
    sent_monotonic_ns: int


@dataclass(frozen=True)
class MessageReceipt:
    """Join one decoded message to its exact raw serial evidence record."""

    message: Message
    serial_event_index: int
    monotonic_ns: int
    utc_ns: int


@dataclass(frozen=True)
class OutgoingWireReceipt:
    """Join one sent command to its exact raw serial evidence record."""

    wire_bytes: bytes
    serial_event_index: int
    monotonic_ns: int
    utc_ns: int


@dataclass(frozen=True)
class IncomingWireReceipt:
    """Remember raw RX evidence until the decoder identifies its message."""

    wire_bytes: bytes
    serial_event_index: int
    monotonic_ns: int
    utc_ns: int


@dataclass(frozen=True)
class EventTrigger:
    """Remember the accepted command identity behind one later RF event."""

    msg_seq: int
    run_token: int
    attempt_index: int


class SystemClock:
    """Adapt Python's system clocks to the transport clock seam."""

    def monotonic_ns(self) -> int:
        """Return the operating system's monotonic nanosecond clock.

        Direct call tree (static source order):
            monotonic_ns
            `-- time.monotonic_ns
        """
        return time.monotonic_ns()

    def utc_ns(self) -> int:
        """Return the operating system's Unix-epoch nanosecond clock.

        Direct call tree (static source order):
            utc_ns
            `-- time.time_ns
        """
        return time.time_ns()

    def sleep_ms(self, milliseconds: int) -> None:
        """Sleep for a short whole-millisecond polling interval.

        Direct call tree (static source order):
            sleep_ms
            `-- time.sleep
        """
        time.sleep(milliseconds / 1000.0)


def _require_endpoint_id(endpoint_id: int) -> None:
    """Require one non-boolean uint32 endpoint identity.

    Processing flow:
        Endpoint identity -> reject Boolean values and values of any other type than integer
        -> enforce the range of an unsigned integer with 32 bits.

    Direct call tree (static source order):
        _require_endpoint_id
        +-- isinstance
        +-- TypeError
        `-- ValueError
    """
    if isinstance(endpoint_id, bool):
        raise TypeError("endpoint_id must be an integer")
    if not isinstance(endpoint_id, int):
        raise TypeError("endpoint_id must be an integer")
    if endpoint_id < 0:
        raise ValueError("endpoint_id must fit uint32")
    if endpoint_id > 4294967295:
        raise ValueError("endpoint_id must fit uint32")


def _require_timeout_ms(timeout_ms: int) -> None:
    """Require one positive non-boolean host command deadline.

    Processing flow:
        Host command deadline -> reject Boolean values and values of any other type than integer
        -> require a positive duration in milliseconds.

    Direct call tree (static source order):
        _require_timeout_ms
        +-- isinstance
        +-- TypeError
        `-- ValueError
    """
    if isinstance(timeout_ms, bool):
        raise TypeError("timeout_ms must be an integer")
    if not isinstance(timeout_ms, int):
        raise TypeError("timeout_ms must be an integer")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")


def _require_expect_types(expect: set[MessageType]) -> None:
    """Require a nonempty concrete set of typed expected responses.

    Processing flow:
        Expected responses -> require a nonempty concrete set
        -> require every accepted response label to be a typed MessageType.

    Direct call tree (static source order):
        _require_expect_types
        +-- isinstance
        +-- TypeError
        +-- len
        `-- ValueError
    """
    if not isinstance(expect, set):
        raise TypeError("expect must be a set")
    if len(expect) == 0:
        raise ValueError("expect must not be empty")
    for message_type in expect:
        if not isinstance(message_type, MessageType):
            raise TypeError("each expected response must be a MessageType")


def open_nano_port(device: str, *, token: str | None = None) -> Serial | NanoPort:
    """Open the local Nano UART for independent antenna operation.

    References:
        pySerial 3.5 API, serial.Serial constructor, timeout, write_timeout,
        and exclusive parameters:
        https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial

    Processing flow:
        Validate local device path -> reject remote URLs -> open exclusive nonblocking UART.

    Local UARTs use the frozen 115200 8N1 settings.

    Direct call tree (static source order):
        open_nano_port
        +-- isinstance
        +-- TypeError
        +-- ValueError
        +-- device.startswith
        +-- float
        +-- RuntimeError
        `-- serial.Serial
    """
    if not isinstance(device, str):
        raise TypeError("device must be text")
    if device == "":
        raise ValueError("device must not be empty")
    if device.startswith("tcp://"):
        raise ValueError("The antenna demo requires a local USB serial port")
    try:
        import serial
    except ImportError as error:
        raise RuntimeError(
            "pyserial is required only when a real Nano port is opened"
        ) from error
    return serial.Serial(
        port=device,
        baudrate=BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
        write_timeout=float(_TRANSPORT_SETTINGS["write_timeout_seconds"]),
        exclusive=True,
    )


class EndpointTransport(Generic[PortT]):
    """Control one endpoint with one sequence space and one command slot."""

    def __init__(
        self,
        port: PortT,
        endpoint_id: int,
        evidence: WireEvidence,
        clock: Clock,
    ) -> None:
        """Create an idle transport without reading or writing the port.

        Direct call tree (static source order):
            __init__
            +-- _require_endpoint_id
            +-- StreamDecoder
            `-- bytearray
        """
        _require_endpoint_id(endpoint_id)
        self.port = port
        self.endpoint_id = endpoint_id
        self.evidence = evidence
        self.clock = clock
        self.next_msg_seq = 0
        self._decoder = StreamDecoder()
        self._outstanding: OutstandingCommand | None = None
        self._unresolved_start: tuple[int, int] | None = None
        self._unresolved_start_boot_count: int | None = None
        self._observed_boot_count: int | None = None
        self._status_recovery_verified = False
        self._event_queue: list[MessageReceipt] = []
        self._event_triggers: dict[MessageType, EventTrigger] = {}
        self._error_triggers: dict[int, EventTrigger] = {}
        self._incoming_fragment = bytearray()
        self._incoming_fragment_discarding = False
        self._incoming_receipts: list[IncomingWireReceipt] = []
        self._last_outgoing_receipt: OutgoingWireReceipt | None = None

    @property
    def last_outgoing_receipt(self) -> OutgoingWireReceipt | None:
        """Return the most recent sent wire and its durable evidence identity.

        Direct call tree (static source order):
            last_outgoing_receipt
            `-- [no direct function calls; local state/return only]
        """
        return self._last_outgoing_receipt

    @property
    def unresolved_start_context(self) -> tuple[int, int] | None:
        """Return the lost START_TX context that still needs a status query.

        Direct call tree (static source order):
            unresolved_start_context
            `-- [no direct function calls; local state/return only]
        """
        return self._unresolved_start

    @property
    def unresolved_start_boot_count(self) -> int | None:
        """Return the endpoint boot count observed before the uncertain start.

        Direct call tree (static source order):
            unresolved_start_boot_count
            `-- [no direct function calls; local state/return only]
        """
        return self._unresolved_start_boot_count

    @property
    def observed_boot_count(self) -> int | None:
        """Return the stable boot count bound by the first HELLO report.

        Direct call tree (static source order):
            observed_boot_count
            `-- [no direct function calls; local state/return only]
        """
        return self._observed_boot_count

    def _require_command_is_safe(
        self,
        message_type: MessageType,
        payload: bytes,
    ) -> None:
        """Allow only the matching status query while START_TX is unresolved.

        Processing flow:
            Requested command -> allow ordinary operation when no START_TX is unresolved
            -> after verified recovery, permit an empty HELLO request
            -> otherwise require a status query with the exact unresolved attempt context.

        Direct call tree (static source order):
            _require_command_is_safe
            +-- UnsafeRetry
            `-- pack_get_attempt_status
        """
        if self._unresolved_start is None:
            return None
        if message_type is MessageType.HELLO:
            if self._status_recovery_verified:
                if payload == b"":
                    return None
        if message_type is not MessageType.GET_ATTEMPT_STATUS:
            raise UnsafeRetry(
                "lost START_TX permits only GET_ATTEMPT_STATUS; do not retransmit"
            )
        expected_payload = pack_get_attempt_status(
            self._unresolved_start[0],
            self._unresolved_start[1],
        )
        if payload != expected_payload:
            raise UnsafeRetry("status query context does not match lost START_TX")
        return None

    def _append_incoming_wires(self, chunk: bytes) -> None:
        """Append every delimiter-complete incoming wire before parsing it.

        Processing flow:
            Read chunk -> extend current fragment -> delimiter -> exact RX ledger row

        Direct call tree (static source order):
            _append_incoming_wires
            +-- self._incoming_fragment.append
            +-- bytes
            +-- self.clock.monotonic_ns
            +-- self.clock.utc_ns
            +-- self.evidence.append_wire
            +-- IncomingWireReceipt
            +-- self._incoming_receipts.append
            +-- self._incoming_fragment.clear
            `-- len
        """
        for octet in chunk:
            if self._incoming_fragment_discarding:
                if octet == 0:
                    self._incoming_fragment_discarding = False
                continue
            self._incoming_fragment.append(octet)
            if octet == 0:
                wire = bytes(self._incoming_fragment)
                monotonic_ns = self.clock.monotonic_ns()
                utc_ns = self.clock.utc_ns()
                event_index = self.evidence.append_wire(
                    monotonic_ns,
                    utc_ns,
                    self.endpoint_id,
                    1,
                    wire,
                )
                receipt = IncomingWireReceipt(
                    wire,
                    event_index,
                    monotonic_ns,
                    utc_ns,
                )
                self._incoming_receipts.append(receipt)
                self._incoming_fragment.clear()
                continue
            if len(self._incoming_fragment) > MAX_COBS_FRAGMENT_LENGTH:
                # The raw ledger accepts only exact bounded messages.  Once a
                # body is too long, no suffix is a truthful replacement for it.
                self._incoming_fragment.clear()
                self._incoming_fragment_discarding = True

    def _raise_protocol_failure(self, error: ProtocolError) -> NoReturn:
        """Convert one parser exception without losing its code or detail.

        Direct call tree (static source order):
            _raise_protocol_failure
            `-- SerialProtocolFailure
        """
        raise SerialProtocolFailure(error) from error

    def _mark_outstanding_receive_uncertain(self) -> None:
        """Close the command slot and retain a possibly executed START_TX.

        Processing flow:
            Outstanding command -> close the response slot
            -> if START_TX may have executed, retain its attempt and observed boot identity
            -> require fresh recovery proof and retain triggers for TX_DONE or a later error.

        Direct call tree (static source order):
            _mark_outstanding_receive_uncertain
            +-- unpack_start_tx
            `-- EventTrigger
        """
        uncertain = self._outstanding
        self._outstanding = None
        if uncertain is None:
            return None
        if uncertain.message_type is MessageType.START_TX:
            started = unpack_start_tx(uncertain.payload)
            self._unresolved_start = (started.run_token, started.attempt_index)
            self._unresolved_start_boot_count = self._observed_boot_count
            self._status_recovery_verified = False
            trigger = EventTrigger(
                uncertain.msg_seq,
                started.run_token,
                started.attempt_index,
            )
            self._event_triggers[MessageType.TX_DONE] = trigger
            self._error_triggers[MessageType.START_TX] = trigger
        return None

    def _take_message_receipt(self, message: Message) -> MessageReceipt:
        """Match a decoded message to the oldest identical raw RX wire.

        Processing flow:
            Decoded response -> locate the oldest raw RX receipt with identical wire bytes
            -> discard receipts through that match -> attach its evidence index and timestamps
            -> reject a decoded response without matching recorded wire evidence.

        Direct call tree (static source order):
            _take_message_receipt
            +-- len
            +-- ProceduralFault
            `-- MessageReceipt
        """
        match_position: int | None = None
        position = 0
        while position < len(self._incoming_receipts):
            candidate = self._incoming_receipts[position]
            if candidate.wire_bytes == message.wire_bytes:
                match_position = position
                break
            position += 1
        if match_position is None:
            raise ProceduralFault("decoded message has no matching raw RX evidence")
        matched = self._incoming_receipts[match_position]
        del self._incoming_receipts[: match_position + 1]
        return MessageReceipt(
            message,
            matched.serial_event_index,
            matched.monotonic_ns,
            matched.utc_ns,
        )

    def _discard_ambiguous_decoder_output(self, now_ms: int) -> None:
        """Clear queued messages and errors after one corrupt stream decision.

        Processing flow:
            Corrupt stream decision -> drain queued decoder errors until no error remains
            -> clear associations between raw receipts and the discarded messages.

        Direct call tree (static source order):
            _discard_ambiguous_decoder_output
            +-- self._decoder.feed
            `-- self._incoming_receipts.clear
        """
        errors_remain = True
        while errors_remain:
            try:
                self._decoder.feed(b"", now_ms)
                errors_remain = False
            except ProtocolError:
                continue
        self._incoming_receipts.clear()

    def _check_message_sequence(self, message: Message) -> None:
        """Require a direct response to echo the outstanding message sequence.

        Processing flow:
            Direct response -> require an outstanding command
            -> require the response sequence to echo that command sequence.

        Direct call tree (static source order):
            _check_message_sequence
            `-- ResponseMismatch
        """
        if self._outstanding is None:
            raise ResponseMismatch("response arrived without an outstanding command")
        if message.msg_seq != self._outstanding.msg_seq:
            raise ResponseMismatch("response sequence does not match command")

    def _record_hello_identity(self, message: Message) -> None:
        """Bind one endpoint ID and reject every later boot-count change.

        Processing flow:
            HELLO_REPORT -> require the configured endpoint identity
            -> bind the first observed boot count or compare with the existing count
            -> reject any later endpoint reset indicated by a changed boot count.

        Direct call tree (static source order):
            _record_hello_identity
            +-- unpack_hello_report
            `-- ResponseMismatch
        """
        report = unpack_hello_report(message.payload)
        if report.endpoint_id != self.endpoint_id:
            raise ResponseMismatch("HELLO_REPORT endpoint identity changed")
        if self._observed_boot_count is None:
            self._observed_boot_count = report.boot_count
            return None
        if report.boot_count != self._observed_boot_count:
            raise ResponseMismatch("endpoint boot count changed")
        return None

    def _remember_event_sequence(self) -> None:
        """Remember which accepted command and context may emit later events.

        Processing flow:
            Accepted command -> recover its sequence and attempt identity
            -> START_TX binds TX_DONE and error triggers
            -> ARM_RX binds packet, timeout and error triggers for the same attempt.

        Direct call tree (static source order):
            _remember_event_sequence
            +-- unpack_start_tx
            +-- EventTrigger
            `-- unpack_arm_rx
        """
        if self._outstanding is None:
            return None
        if self._outstanding.message_type is MessageType.START_TX:
            started = unpack_start_tx(self._outstanding.payload)
            trigger = EventTrigger(
                self._outstanding.msg_seq,
                started.run_token,
                started.attempt_index,
            )
            self._event_triggers[MessageType.TX_DONE] = trigger
            self._error_triggers[MessageType.START_TX] = trigger
        if self._outstanding.message_type is MessageType.ARM_RX:
            armed = unpack_arm_rx(self._outstanding.payload)
            trigger = EventTrigger(
                self._outstanding.msg_seq,
                armed.run_token,
                armed.attempt_index,
            )
            self._event_triggers[MessageType.RX_PACKET] = trigger
            self._event_triggers[MessageType.RX_TIMEOUT] = trigger
            self._error_triggers[MessageType.ARM_RX] = trigger

    def _event_context(self, message: Message) -> tuple[int, int]:
        """Decode the attempt identity carried by one normal terminal event.

        Processing flow:
            Terminal event type -> decode TX_DONE, RX_PACKET or RX_TIMEOUT payload
            -> return its run token and attempt index; reject other message types.

        Direct call tree (static source order):
            _event_context
            +-- unpack_tx_done
            +-- unpack_rx_packet
            +-- unpack_rx_timeout
            `-- ResponseMismatch
        """
        if message.message_type is MessageType.TX_DONE:
            decoded = unpack_tx_done(message.payload)
            return (decoded.run_token, decoded.attempt_index)
        if message.message_type is MessageType.RX_PACKET:
            decoded = unpack_rx_packet(message.payload)
            return (decoded.run_token, decoded.attempt_index)
        if message.message_type is MessageType.RX_TIMEOUT:
            decoded = unpack_rx_timeout(message.payload)
            return (decoded.run_token, decoded.attempt_index)
        raise ResponseMismatch("message is not a normal terminal event")

    def _clear_event_trigger(self, message_type: MessageType) -> None:
        """Consume the one-shot trigger behind a normal terminal event.

        Processing flow:
            Consumed terminal event -> identify the transmit or receive action
            -> remove its terminal event and error triggers so the action cannot be consumed twice.

        Direct call tree (static source order):
            _clear_event_trigger
            +-- self._event_triggers.pop
            `-- self._error_triggers.pop
        """
        if message_type is MessageType.TX_DONE:
            self._event_triggers.pop(MessageType.TX_DONE, None)
            self._error_triggers.pop(MessageType.START_TX, None)
            return None
        self._event_triggers.pop(MessageType.RX_PACKET, None)
        self._event_triggers.pop(MessageType.RX_TIMEOUT, None)
        self._error_triggers.pop(MessageType.ARM_RX, None)
        return None

    def _check_event_sequence(self, message: Message) -> None:
        """Require an event to echo its triggering sequence and attempt context.

        Processing flow:
            Terminal event -> require an accepted triggering command
            -> match the triggering sequence and decoded attempt identity
            -> consume the action triggers after successful correlation.

        Direct call tree (static source order):
            _check_event_sequence
            +-- self._event_triggers.get
            +-- ResponseMismatch
            +-- self._event_context
            `-- self._clear_event_trigger
        """
        trigger = self._event_triggers.get(message.message_type)
        if trigger is None:
            raise ResponseMismatch("event has no accepted triggering command")
        if message.msg_seq != trigger.msg_seq:
            raise ResponseMismatch("event sequence does not match its trigger")
        context = self._event_context(message)
        expected_context = (trigger.run_token, trigger.attempt_index)
        if context != expected_context:
            raise ResponseMismatch("event context does not match its trigger")
        self._clear_event_trigger(message.message_type)

    def _endpoint_error_is_direct(
        self,
        message: Message,
        response_exists: bool,
    ) -> bool:
        """Tell whether an ENDPOINT_ERROR rejects the outstanding command.

        Processing flow:
            ENDPOINT_ERROR -> rule out a direct rejection after another response exists
            -> require an outstanding command -> compare its type with the error related_type.

        Direct call tree (static source order):
            _endpoint_error_is_direct
            `-- unpack_endpoint_error
        """
        if response_exists:
            return False
        if self._outstanding is None:
            return False
        decoded = unpack_endpoint_error(message.payload)
        return decoded.related_type == self._outstanding.message_type

    def _check_error_event(self, message: Message) -> None:
        """Require an asynchronous error to match an accepted RF action.

        Processing flow:
            Asynchronous endpoint error -> locate the trigger for the accepted RF action
            -> match sequence and attempt identity -> consume transmit or receive triggers
            -> reject an error that cannot be bound to that accepted action.

        Direct call tree (static source order):
            _check_error_event
            +-- unpack_endpoint_error
            +-- self._error_triggers.get
            +-- ResponseMismatch
            `-- self._clear_event_trigger
        """
        decoded = unpack_endpoint_error(message.payload)
        trigger = self._error_triggers.get(decoded.related_type)
        if trigger is None:
            raise ResponseMismatch("error event has no accepted triggering command")
        if message.msg_seq != trigger.msg_seq:
            raise ResponseMismatch("error event sequence does not match its trigger")
        context = (decoded.run_token, decoded.attempt_index)
        expected_context = (trigger.run_token, trigger.attempt_index)
        if context != expected_context:
            raise ResponseMismatch("error event context does not match its trigger")
        if decoded.related_type == MessageType.START_TX:
            self._clear_event_trigger(MessageType.TX_DONE)
            return None
        self._clear_event_trigger(MessageType.RX_TIMEOUT)
        return None

    def _process_received_messages(
        self,
        messages: tuple[Message, ...],
        expect: set[MessageType],
    ) -> MessageReceipt | None:
        """Select one expected response and queue declared asynchronous events.

        Processing flow:
            Decoded messages -> expected response match / async queue / reject

        Direct call tree (static source order):
            _process_received_messages
            +-- self._take_message_receipt
            +-- self._check_message_sequence
            +-- self._record_hello_identity
            +-- self._remember_event_sequence
            +-- ResponseMismatch
            +-- self._endpoint_error_is_direct
            +-- EndpointReportedError
            +-- self._check_error_event
            +-- self._event_queue.append
            `-- self._check_event_sequence
        """
        response: MessageReceipt | None = None
        for message in messages:
            receipt = self._take_message_receipt(message)
            is_expected = message.message_type in expect
            if is_expected:
                self._check_message_sequence(message)
                if message.message_type is MessageType.HELLO_REPORT:
                    self._record_hello_identity(message)
                self._remember_event_sequence()
                if response is not None:
                    raise ResponseMismatch("more than one command response arrived")
                response = receipt
                continue
            if message.message_type is MessageType.ENDPOINT_ERROR:
                direct = self._endpoint_error_is_direct(
                    message,
                    response is not None,
                )
                if direct:
                    self._check_message_sequence(message)
                    raise EndpointReportedError(message)
                self._check_error_event(message)
                self._event_queue.append(receipt)
                continue
            is_async = message.message_type in ASYNC_EVENT_TYPES
            if is_async:
                self._check_event_sequence(message)
                self._event_queue.append(receipt)
                continue
            raise ResponseMismatch(
                "unexpected response type " + message.message_type.name
            )
        return response

    def send_once(self, message_type: MessageType, payload: bytes) -> int:
        """Write one command once and durably preserve its complete wire bytes.

        Processing flow:
            Safety/slot checks -> allocate sequence -> encode -> exact write
                -> append TX evidence -> occupy command slot -> advance sequence

        Direct call tree (static source order):
            send_once
            +-- isinstance
            +-- TypeError
            +-- self._require_command_is_safe
            +-- RuntimeError
            +-- Message
            +-- encode_wire
            +-- self.port.write
            +-- len
            +-- OSError
            +-- str
            +-- self.clock.monotonic_ns
            +-- self.clock.utc_ns
            +-- self.evidence.append_wire
            +-- OutgoingWireReceipt
            `-- OutstandingCommand
        """
        if not isinstance(message_type, MessageType):
            raise TypeError("message_type must be a MessageType")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        self._require_command_is_safe(message_type, payload)
        if self._outstanding is not None:
            raise RuntimeError("one outstanding command per endpoint is required")
        sequence = self.next_msg_seq
        message = Message(message_type, sequence, payload)
        wire = encode_wire(message)
        written = self.port.write(wire)
        if written != len(wire):
            raise OSError(
                "partial serial write: " + str(written) + "/" + str(len(wire))
            )
        timestamp = self.clock.monotonic_ns()
        utc_ns = self.clock.utc_ns()
        event_index = self.evidence.append_wire(
            timestamp,
            utc_ns,
            self.endpoint_id,
            0,
            wire,
        )
        self._last_outgoing_receipt = OutgoingWireReceipt(
            wire,
            event_index,
            timestamp,
            utc_ns,
        )
        self._outstanding = OutstandingCommand(
            sequence,
            message_type,
            payload,
            wire,
            timestamp,
        )
        self.next_msg_seq = (sequence + 1) & 0xFFFF
        return sequence

    def _read_messages_once(self) -> tuple[Message, ...]:
        """Poll parser time, preserve raw bytes, and decode one available chunk.

        Processing flow:
            Current host time -> check parser timeout and preserve any uncertain START_TX state
            -> wait when no bytes are available; otherwise read a bounded serial chunk
            -> preserve raw wire receipts before decoding the chunk
            -> return decoded messages or discard ambiguous output and raise the parser failure.

        Direct call tree (static source order):
            _read_messages_once
            +-- self.clock.monotonic_ns
            +-- self._decoder.poll_timeout
            +-- self._incoming_fragment.clear
            +-- self._mark_outstanding_receive_uncertain
            +-- self._discard_ambiguous_decoder_output
            +-- self._raise_protocol_failure
            +-- self.clock.sleep_ms
            +-- self.port.read
            +-- isinstance
            +-- TypeError
            +-- len
            +-- self._append_incoming_wires
            `-- self._decoder.feed
        """
        now_ms = self.clock.monotonic_ns() // 1_000_000
        try:
            self._decoder.poll_timeout(now_ms)
        except ProtocolError as error:
            if error.code is ErrorCode.SERIAL_OVERFLOW:
                if error.detail == "interbyte_timeout":
                    # Both ledgers abandon the same partial body and remain in
                    # discard mode until the sender's next zero delimiter.
                    self._incoming_fragment.clear()
                    self._incoming_fragment_discarding = True
            self._mark_outstanding_receive_uncertain()
            self._discard_ambiguous_decoder_output(now_ms)
            self._raise_protocol_failure(error)
        waiting = self.port.in_waiting
        if waiting <= 0:
            self.clock.sleep_ms(SERIAL_READ_POLL_MS)
            return ()
        read_size = waiting
        if read_size > MAX_WIRE_LENGTH:
            read_size = MAX_WIRE_LENGTH
        chunk = self.port.read(read_size)
        if not isinstance(chunk, bytes):
            self._mark_outstanding_receive_uncertain()
            raise TypeError("serial read must return bytes")
        if len(chunk) == 0:
            self.clock.sleep_ms(SERIAL_READ_POLL_MS)
            return ()
        self._append_incoming_wires(chunk)
        try:
            return self._decoder.feed(chunk, now_ms)
        except ProtocolError as error:
            self._mark_outstanding_receive_uncertain()
            self._discard_ambiguous_decoder_output(now_ms)
            self._raise_protocol_failure(error)

    def receive_until_receipt(
        self,
        expect: set[MessageType],
        timeout_ms: int,
    ) -> MessageReceipt:
        """Wait for a response joined to its exact raw-evidence record.

        Processing flow:
            Validate slot/deadline -> parser timeout poll -> nonblocking read
                -> raw evidence -> stream decode -> response or async event
                -> host deadline without synthesizing an RF terminal

        Direct call tree (static source order):
            receive_until_receipt
            +-- _require_expect_types
            +-- _require_timeout_ms
            +-- RuntimeError
            +-- self.clock.monotonic_ns
            +-- self._read_messages_once
            +-- self._process_received_messages
            +-- self._mark_outstanding_receive_uncertain
            `-- CommandTimeout
        """
        _require_expect_types(expect)
        _require_timeout_ms(timeout_ms)
        if self._outstanding is None:
            raise RuntimeError("no outstanding command")
        start_ns = self.clock.monotonic_ns()
        deadline_ns = start_ns + timeout_ms * 1_000_000
        while self.clock.monotonic_ns() < deadline_ns:
            messages = self._read_messages_once()
            try:
                response = self._process_received_messages(messages, expect)
            except ResponseMismatch:
                self._mark_outstanding_receive_uncertain()
                raise
            except EndpointReportedError:
                self._outstanding = None
                raise
            if response is not None:
                self._outstanding = None
                return response
        self._mark_outstanding_receive_uncertain()
        raise CommandTimeout("host command deadline expired without a response")

    def receive_until(
        self,
        expect: set[MessageType],
        timeout_ms: int,
    ) -> Message:
        """Wait for one response and return its decoded protocol message.

        Processing flow:
            Expected types and host deadline -> evidence-bound receive loop ->
            return only the decoded message from the accepted receipt.

        Direct call tree (static source order):
            receive_until
            `-- self.receive_until_receipt
        """
        receipt = self.receive_until_receipt(expect, timeout_ms)
        return receipt.message

    def command_receipt(
        self,
        message_type: MessageType,
        payload: bytes,
        expect: set[MessageType],
        timeout_ms: int,
    ) -> MessageReceipt:
        """Send once and return a response with exact raw-evidence identity.

        Processing flow:
            Send once -> occupy command slot -> receive matching response or fault

        Direct call tree (static source order):
            command_receipt
            +-- self.send_once
            `-- self.receive_until_receipt
        """
        self.send_once(message_type, payload)
        return self.receive_until_receipt(expect, timeout_ms)

    def command(
        self,
        message_type: MessageType,
        payload: bytes,
        expect: set[MessageType],
        timeout_ms: int,
    ) -> Message:
        """Send one command exactly once and return its decoded response.

        Processing flow:
            Typed command -> one durable send -> one matching receipt ->
            decoded response without discarding the underlying evidence.

        Direct call tree (static source order):
            command
            `-- self.command_receipt
        """
        receipt = self.command_receipt(message_type, payload, expect, timeout_ms)
        return receipt.message

    def wait_event_receipt(self, timeout_ms: int) -> MessageReceipt:
        """Wait for a terminal endpoint event without sending another command.

        Processing flow:
            Existing queue -> nonblocking reads -> validate trigger -> receipt

        Direct call tree (static source order):
            wait_event_receipt
            +-- _require_timeout_ms
            +-- RuntimeError
            +-- len
            +-- self._event_queue.pop
            +-- self.clock.monotonic_ns
            +-- self._read_messages_once
            +-- self._process_received_messages
            +-- set
            `-- CommandTimeout
        """
        _require_timeout_ms(timeout_ms)
        if self._outstanding is not None:
            raise RuntimeError("cannot wait for an event during a command")
        if len(self._event_queue) > 0:
            return self._event_queue.pop(0)
        start_ns = self.clock.monotonic_ns()
        deadline_ns = start_ns + timeout_ms * 1_000_000
        while self.clock.monotonic_ns() < deadline_ns:
            messages = self._read_messages_once()
            self._process_received_messages(messages, set())
            if len(self._event_queue) > 0:
                return self._event_queue.pop(0)
        raise CommandTimeout("host event deadline expired without an endpoint event")

    def pop_event_receipt(self) -> MessageReceipt | None:
        """Remove the oldest queued event with its raw-evidence identity.

        Processing flow:
            Queued event receipts -> empty queue returns None; otherwise remove oldest receipt -> preserve wire index and timestamps.

        Direct call tree (static source order):
            pop_event_receipt
            +-- len
            `-- self._event_queue.pop
        """
        if len(self._event_queue) == 0:
            return None
        return self._event_queue.pop(0)

    def pop_event(self) -> Message | None:
        """Remove and return the oldest declared asynchronous endpoint event.

        Processing flow:
            Queued asynchronous events -> retrieve oldest receipt -> return its decoded message or None.

        Direct call tree (static source order):
            pop_event
            `-- self.pop_event_receipt
        """
        receipt = self.pop_event_receipt()
        if receipt is None:
            return None
        return receipt.message

    def retry_last_with_new_sequence(self) -> None:
        """Reject retries that could duplicate an unresolved START_TX action.

        Processing flow:
            Pending command identity -> reject START_TX or unresolved transaction -> allocate fresh command sequence only for a permitted command.

        Direct call tree (static source order):
            retry_last_with_new_sequence
            +-- UnsafeRetry
            `-- RuntimeError
        """
        if self._unresolved_start is not None:
            raise UnsafeRetry(
                "START_TX cannot be retried with a new sequence; query status"
            )
        raise RuntimeError("there is no unresolved START_TX to recover")

    def confirm_status_recovery(self, run_token: int, attempt_index: int) -> None:
        """Clear the unresolved slot after a matching status proves TX start.

        Processing flow:
            Pending START_TX identity and recovered status -> require matching sequence/token/state -> clear unresolved command slot.

        Direct call tree (static source order):
            confirm_status_recovery
            `-- ProceduralFault
        """
        if self._unresolved_start is None:
            raise ProceduralFault("there is no lost START_TX to recover")
        context = (run_token, attempt_index)
        if context != self._unresolved_start:
            raise ProceduralFault("status context does not match lost START_TX")
        self._unresolved_start = None
        self._unresolved_start_boot_count = None
        self._status_recovery_verified = False

    def permit_recovery_boot_check(self, run_token: int, attempt_index: int) -> None:
        """Permit one HELLO only after matching status proves the lost action.

        Processing flow:
            Pending START_TX and recovered status -> validate matching action proof -> permit one subsequent HELLO boot-identity check.

        Direct call tree (static source order):
            permit_recovery_boot_check
            `-- ProceduralFault
        """
        context = (run_token, attempt_index)
        if context != self._unresolved_start:
            raise ProceduralFault("status context does not match lost START_TX")
        self._status_recovery_verified = True


def query_attempt_after_lost_start(
    transport: EndpointTransport,
    run_token: int,
    attempt_index: int,
) -> Message:
    """Query existing endpoint state and return its decoded status message.

    Processing flow:
        Unresolved attempt identity -> evidence-bound recovery query -> return
        only the decoded status after boot-count and state validation.

    Direct call tree (static source order):
        query_attempt_after_lost_start
        `-- query_attempt_after_lost_start_receipt
    """
    receipt = query_attempt_after_lost_start_receipt(
        transport,
        run_token,
        attempt_index,
    )
    return receipt.message


def query_attempt_after_lost_start_receipt(
    transport: EndpointTransport,
    run_token: int,
    attempt_index: int,
) -> MessageReceipt:
    """Query lost START_TX state and retain the exact status-wire receipt.

    Processing flow:
        Match unresolved context -> GET_ATTEMPT_STATUS -> typed status/context
            -> accept TX_STARTED or TX_DONE -> clear unresolved slot

    Direct call tree (static source order):
        query_attempt_after_lost_start_receipt
        +-- isinstance
        +-- TypeError
        +-- ProceduralFault
        +-- pack_get_attempt_status
        +-- transport.command_receipt
        +-- unpack_attempt_status
        +-- transport.permit_recovery_boot_check
        +-- transport.command
        +-- unpack_hello_report
        `-- transport.confirm_status_recovery
    """
    if not isinstance(transport, EndpointTransport):
        raise TypeError("transport must be an EndpointTransport")
    expected_context = transport.unresolved_start_context
    if expected_context is None:
        raise ProceduralFault("there is no lost START_TX to query")
    expected_boot_count = transport.unresolved_start_boot_count
    if expected_boot_count is None:
        raise ProceduralFault(
            "lost START_TX has no pre-action endpoint boot count"
        )
    supplied_context = (run_token, attempt_index)
    if supplied_context != expected_context:
        raise ProceduralFault("query context does not match lost START_TX")
    payload = pack_get_attempt_status(run_token, attempt_index)
    response = transport.command_receipt(
        MessageType.GET_ATTEMPT_STATUS,
        payload,
        {MessageType.ATTEMPT_STATUS},
        500,
    )
    status = unpack_attempt_status(response.message.payload)
    returned_context = (status.run_token, status.attempt_index)
    if returned_context != expected_context:
        raise ProceduralFault("status response context does not match lost START_TX")
    acceptable_states = (AttemptState.TX_STARTED, AttemptState.TX_DONE)
    if status.state not in acceptable_states:
        raise ProceduralFault("status does not prove that TX started")
    if status.last_error_code != 0:
        raise ProceduralFault("status reports an endpoint error")
    transport.permit_recovery_boot_check(run_token, attempt_index)
    hello = transport.command(
        MessageType.HELLO,
        b"",
        {MessageType.HELLO_REPORT},
        500,
    )
    hello_report = unpack_hello_report(hello.payload)
    if hello_report.boot_count != expected_boot_count:
        raise ProceduralFault("endpoint boot count changed during START_TX recovery")
    transport.confirm_status_recovery(run_token, attempt_index)
    return response
