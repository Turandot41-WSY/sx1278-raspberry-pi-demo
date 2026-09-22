"""Test the two-port transport without opening real serial hardware."""

from __future__ import annotations

import builtins

import pytest

from host.radio.serial_protocol import (
    AttemptState,
    ErrorCode,
    Message,
    MessageType,
    decode_wire,
    encode_wire,
    pack_attempt_status,
    pack_endpoint_error,
    pack_get_attempt_status,
    pack_hello_report,
    pack_start_tx,
)
from host.radio.serial_transport import (
    CommandTimeout,
    EndpointReportedError,
    EndpointTransport,
    ProceduralFault,
    ResponseMismatch,
    SerialProtocolFailure,
    UnsafeRetry,
    open_nano_port,
    query_attempt_after_lost_start,
)
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_endpoints import EvidenceSpy, ScriptedBytePort


def hello_report_wire(command: Message, boot_count: int = 1) -> bytes:
    """Build one endpoint-1 HELLO_REPORT for transport recovery tests.

    Direct call tree (static source order):
        hello_report_wire
        +-- bytes
        +-- pack_hello_report
        +-- Message
        `-- encode_wire
    """
    zero_hash = bytes(32)
    payload = pack_hello_report(
        1,
        boot_count,
        0x12,
        AttemptState.STANDBY,
        zero_hash,
        zero_hash,
        zero_hash,
    )
    response = Message(MessageType.HELLO_REPORT, command.msg_seq, payload)
    return encode_wire(response)


def test_transport_logs_complete_wire_bytes_on_both_directions(
    evidence_spy: EvidenceSpy,
) -> None:
    """Preserve each full outgoing and fragmented incoming wire exactly once.

    Direct call tree (static source order):
        test_transport_logs_complete_wire_bytes_on_both_directions
        +-- ScriptedBytePort.acking_for
        +-- EndpointTransport
        +-- FakeClock
        +-- transport.command
        +-- len
        `-- report.wire_bytes.endswith
    """
    port = ScriptedBytePort.acking_for(11)
    port._chunks = [1, 2, 5]
    transport = EndpointTransport(port, 11, evidence_spy, FakeClock())
    report = transport.command(
        MessageType.HELLO,
        b"",
        {MessageType.HELLO_REPORT},
        500,
    )
    assert report.message_type is MessageType.HELLO_REPORT
    assert transport.observed_boot_count == 1
    assert len(evidence_spy.wires) == 2
    assert evidence_spy.wires[0].direction == 0
    assert evidence_spy.wires[1].direction == 1
    assert evidence_spy.wires[0].wire_bytes == port.writes[0]
    assert evidence_spy.wires[1].wire_bytes == report.wire_bytes
    assert report.wire_bytes.endswith(b"\x00")


def test_sequences_are_independent_and_wrap_per_endpoint(
    evidence_spy: EvidenceSpy,
) -> None:
    """Allocate sequence values locally to each endpoint including uint16 wrap.

    Direct call tree (static source order):
        test_sequences_are_independent_and_wrap_per_endpoint
        +-- EndpointTransport
        +-- ScriptedBytePort.acking_for
        +-- FakeClock
        +-- first.command
        `-- second.command
    """
    first = EndpointTransport(
        ScriptedBytePort.acking_for(1),
        1,
        evidence_spy,
        FakeClock(),
    )
    second = EndpointTransport(
        ScriptedBytePort.acking_for(2),
        2,
        evidence_spy,
        FakeClock(),
    )
    first.next_msg_seq = 65535
    assert first.command(
        MessageType.HELLO,
        b"",
        {MessageType.HELLO_REPORT},
        500,
    ).msg_seq == 65535
    assert first.next_msg_seq == 0
    assert second.command(
        MessageType.HELLO,
        b"",
        {MessageType.HELLO_REPORT},
        500,
    ).msg_seq == 0


def test_one_outstanding_command_and_partial_write_fail_closed(
    evidence_spy: EvidenceSpy,
) -> None:
    """Reject a second command slot and any write that accepts only a prefix.

    Direct call tree (static source order):
        test_one_outstanding_command_and_partial_write_fail_closed
        +-- ScriptedBytePort
        +-- EndpointTransport
        +-- FakeClock
        +-- pytest.raises
        `-- transport.send_once
    """
    port = ScriptedBytePort(ScriptedBytePort._default_response, write_limit=2)
    transport = EndpointTransport(port, 1, evidence_spy, FakeClock())
    with pytest.raises(OSError, match="partial serial write"):
        transport.send_once(MessageType.HELLO, b"")
    assert evidence_spy.wires == []


def test_concatenated_async_event_is_queued_after_expected_response(
    evidence_spy: EvidenceSpy,
) -> None:
    """Keep a declared asynchronous event even when it shares one read chunk.

    Direct call tree (static source order):
        test_concatenated_async_event_is_queued_after_expected_response
        +-- ScriptedBytePort.with_responder
        +-- EndpointTransport
        +-- FakeClock
        +-- transport.command
        +-- pack_start_tx
        `-- transport.pop_event
    """
    def responder(wire: bytes) -> bytes:
        """Return matching TX_STARTED and TX_DONE frames in one response chunk.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- Message
            +-- pack_start_tx
            `-- encode_wire
        """
        command = decode_wire(wire)
        started = Message(
            MessageType.TX_STARTED,
            command.msg_seq,
            pack_start_tx(7, 3),
        )
        done = Message(
            MessageType.TX_DONE,
            command.msg_seq,
            pack_start_tx(7, 3),
        )
        return encode_wire(started) + encode_wire(done)

    port = ScriptedBytePort.with_responder(responder)
    transport = EndpointTransport(port, 1, evidence_spy, FakeClock())
    response = transport.command(
        MessageType.START_TX,
        pack_start_tx(7, 3),
        {MessageType.TX_STARTED},
        500,
    )
    assert response.message_type is MessageType.TX_STARTED
    queued = transport.pop_event()
    assert queued is not None
    assert queued.message_type is MessageType.TX_DONE
    assert transport.pop_event() is None


def test_delayed_async_event_can_be_read_with_exact_wire_evidence(
    evidence_spy: EvidenceSpy,
) -> None:
    """Return a later terminal event with its raw-ledger index and timestamps.

    Direct call tree (static source order):
        test_delayed_async_event_can_be_read_with_exact_wire_evidence
        +-- ScriptedBytePort.acking
        +-- FakeClock
        +-- EndpointTransport
        +-- transport.command_receipt
        +-- pack_start_tx
        +-- Message
        +-- port.queue_incoming
        +-- encode_wire
        `-- transport.wait_event_receipt
    """
    port = ScriptedBytePort.acking()
    clock = FakeClock(100, 200)
    transport = EndpointTransport(port, 1, evidence_spy, clock)
    response = transport.command_receipt(
        MessageType.START_TX,
        pack_start_tx(7, 3),
        {MessageType.TX_STARTED},
        500,
    )
    done = Message(
        MessageType.TX_DONE,
        response.message.msg_seq,
        pack_start_tx(7, 3),
    )
    port.queue_incoming(encode_wire(done))
    terminal = transport.wait_event_receipt(500)
    assert terminal.message.message_type is MessageType.TX_DONE
    assert terminal.serial_event_index == 2
    assert terminal.monotonic_ns == evidence_spy.wires[2].monotonic_ns
    assert terminal.utc_ns == evidence_spy.wires[2].utc_ns
    assert terminal.message.wire_bytes == evidence_spy.wires[2].wire_bytes


def test_delayed_endpoint_error_is_an_async_attempt_event(
    evidence_spy: EvidenceSpy,
) -> None:
    """Do not misclassify an accepted START_TX's later error as a response.

    Direct call tree (static source order):
        test_delayed_endpoint_error_is_an_async_attempt_event
        +-- ScriptedBytePort.acking
        +-- EndpointTransport
        +-- FakeClock
        +-- transport.command
        +-- pack_start_tx
        +-- pack_endpoint_error
        +-- Message
        +-- port.queue_incoming
        +-- encode_wire
        `-- transport.wait_event_receipt
    """
    port = ScriptedBytePort.acking()
    transport = EndpointTransport(port, 1, evidence_spy, FakeClock())
    started = transport.command(
        MessageType.START_TX,
        pack_start_tx(7, 3),
        {MessageType.TX_STARTED},
        500,
    )
    payload = pack_endpoint_error(
        7,
        3,
        MessageType.START_TX,
        ErrorCode.DEVICE_RADIO_TIMEOUT,
        0,
    )
    error_event = Message(MessageType.ENDPOINT_ERROR, started.msg_seq, payload)
    port.queue_incoming(encode_wire(error_event))
    terminal = transport.wait_event_receipt(500)
    assert terminal.message.message_type is MessageType.ENDPOINT_ERROR


def test_asynchronous_event_must_echo_its_triggering_command_sequence(
    evidence_spy: EvidenceSpy,
) -> None:
    """Reject an event sequence that cannot identify its RF trigger.

    Direct call tree (static source order):
        test_asynchronous_event_must_echo_its_triggering_command_sequence
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- pytest.raises
        +-- transport.command
        `-- pack_start_tx
    """
    def responder(wire: bytes) -> bytes:
        """Return TX_DONE with a deliberately incorrect triggering sequence.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- Message
            +-- pack_start_tx
            `-- encode_wire
        """
        command = decode_wire(wire)
        started = Message(
            MessageType.TX_STARTED,
            command.msg_seq,
            pack_start_tx(7, 3),
        )
        done = Message(
            MessageType.TX_DONE,
            command.msg_seq + 1,
            pack_start_tx(7, 3),
        )
        return encode_wire(started) + encode_wire(done)

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    with pytest.raises(ResponseMismatch, match="event sequence"):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(7, 3),
            {MessageType.TX_STARTED},
            500,
        )


def test_response_sequence_mismatch_is_a_procedural_fault(
    evidence_spy: EvidenceSpy,
) -> None:
    """Never attach a response carrying another sequence to this command.

    Direct call tree (static source order):
        test_response_sequence_mismatch_is_a_procedural_fault
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- pytest.raises
        +-- transport.command
        `-- issubclass
    """
    def responder(wire: bytes) -> bytes:
        """Return HELLO_REPORT with a sequence that cannot match the outstanding command.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- Message
            +-- bytes
            `-- encode_wire
        """
        command = decode_wire(wire)
        response = Message(MessageType.HELLO_REPORT, command.msg_seq + 1, bytes(106))
        return encode_wire(response)

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    with pytest.raises(ResponseMismatch, match="sequence"):
        transport.command(
            MessageType.HELLO,
            b"",
            {MessageType.HELLO_REPORT},
            500,
        )
    assert issubclass(ResponseMismatch, ProceduralFault)


def test_complete_bad_wire_is_logged_before_protocol_failure(
    evidence_spy: EvidenceSpy,
) -> None:
    """Retain corrupt input evidence instead of silently dropping the frame.

    Direct call tree (static source order):
        test_complete_bad_wire_is_logged_before_protocol_failure
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- pytest.raises
        `-- transport.command
    """
    def responder(wire: bytes) -> bytes:
        """Return a malformed protocol fragment to exercise parser-failure handling.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            `-- [no direct function calls; local state/return only]
        """
        del wire
        return b"\x02\x01\x00"

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    with pytest.raises(SerialProtocolFailure):
        transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    assert evidence_spy.wires[-1].direction == 1
    assert evidence_spy.wires[-1].wire_bytes == b"\x02\x01\x00"


def test_overlong_rx_fragment_never_fabricates_bounded_wire_evidence(
    evidence_spy: EvidenceSpy,
) -> None:
    """Discard an overlong body through its delimiter, then log the next wire.

    Direct call tree (static source order):
        test_overlong_rx_fragment_never_fabricates_bounded_wire_evidence
        +-- EndpointTransport
        +-- ScriptedBytePort.drop_all
        +-- FakeClock
        +-- transport._append_incoming_wires
        +-- encode_wire
        +-- Message
        `-- len
    """
    transport = EndpointTransport(
        ScriptedBytePort.drop_all(),
        1,
        evidence_spy,
        FakeClock(),
    )
    transport._append_incoming_wires(b"\x01" * 130)
    valid = encode_wire(Message(MessageType.ACK, 0, b"\x01"))
    transport._append_incoming_wires(b"\x00" + valid)
    assert len(evidence_spy.wires) == 1
    assert evidence_spy.wires[0].direction == 1
    assert evidence_spy.wires[0].wire_bytes == valid


def test_start_timeout_forbids_new_start_and_requires_status_query(
    evidence_spy: EvidenceSpy,
) -> None:
    """Keep a lost START_TX unresolved and never create a second RF action.

    Direct call tree (static source order):
        test_start_timeout_forbids_new_start_and_requires_status_query
        +-- EndpointTransport
        +-- ScriptedBytePort.drop_all
        +-- FakeClock
        +-- pack_start_tx
        +-- pytest.raises
        +-- transport.command
        +-- transport.retry_last_with_new_sequence
        `-- len
    """
    transport = EndpointTransport(
        ScriptedBytePort.drop_all(),
        1,
        evidence_spy,
        FakeClock(),
    )
    payload = pack_start_tx(9, 2)
    with pytest.raises(CommandTimeout):
        transport.command(
            MessageType.START_TX,
            payload,
            {MessageType.TX_STARTED},
            10,
        )
    with pytest.raises(UnsafeRetry):
        transport.retry_last_with_new_sequence()
    with pytest.raises(UnsafeRetry):
        transport.command(
            MessageType.START_TX,
            payload,
            {MessageType.TX_STARTED},
            10,
        )
    with pytest.raises(UnsafeRetry):
        transport.command(
            MessageType.HELLO,
            b"",
            {MessageType.HELLO_REPORT},
            10,
        )
    assert len(transport.port.writes) == 1


def test_corrupt_start_response_forbids_a_second_start(
    evidence_spy: EvidenceSpy,
) -> None:
    """Treat a parser failure after START_TX write as an uncertain RF action.

    Direct call tree (static source order):
        test_corrupt_start_response_forbids_a_second_start
        +-- ScriptedBytePort.with_responder
        +-- EndpointTransport
        +-- FakeClock
        +-- pack_start_tx
        +-- pytest.raises
        +-- transport.command
        `-- len
    """
    def responder(wire: bytes) -> bytes:
        """Corrupt a byte in the encoded TX_STARTED response to force CRC rejection.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- Message
            +-- pack_start_tx
            +-- bytearray
            +-- encode_wire
            `-- bytes
        """
        command = decode_wire(wire)
        started = Message(
            MessageType.TX_STARTED,
            command.msg_seq,
            pack_start_tx(9, 2),
        )
        encoded = bytearray(encode_wire(started))
        encoded[-2] ^= 1
        return bytes(encoded)

    port = ScriptedBytePort.with_responder(responder)
    transport = EndpointTransport(port, 1, evidence_spy, FakeClock())
    payload = pack_start_tx(9, 2)
    with pytest.raises(SerialProtocolFailure):
        transport.command(
            MessageType.START_TX,
            payload,
            {MessageType.TX_STARTED},
            10,
        )
    assert transport.unresolved_start_context == (9, 2)
    with pytest.raises(UnsafeRetry):
        transport.command(
            MessageType.START_TX,
            payload,
            {MessageType.TX_STARTED},
            10,
        )
    assert len(port.writes) == 1


def test_corrupt_stream_discards_ambiguous_queued_message_before_recovery(
    evidence_spy: EvidenceSpy,
) -> None:
    """Let status recovery start from a clean decoder after mixed bad/good input.

    Direct call tree (static source order):
        test_corrupt_stream_discards_ambiguous_queued_message_before_recovery
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- transport.command
        +-- pytest.raises
        +-- pack_start_tx
        `-- query_attempt_after_lost_start
    """
    call_count = 0

    def responder(wire: bytes) -> bytes:
        """Inject malformed input before TX_STARTED and then provide recovery status and identity.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- hello_report_wire
            +-- Message
            +-- pack_start_tx
            +-- encode_wire
            `-- pack_attempt_status
        """
        nonlocal call_count
        command = decode_wire(wire)
        call_count += 1
        if call_count == 1:
            return hello_report_wire(command)
        if call_count == 2:
            bad = b"\x02\x01\x00"
            started = Message(
                MessageType.TX_STARTED,
                command.msg_seq,
                pack_start_tx(9, 2),
            )
            return bad + encode_wire(started)
        if call_count == 3:
            status = pack_attempt_status(9, 2, AttemptState.TX_STARTED, 0)
            return encode_wire(
                Message(MessageType.ATTEMPT_STATUS, command.msg_seq, status)
            )
        return hello_report_wire(command)

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    with pytest.raises(SerialProtocolFailure):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(9, 2),
            {MessageType.TX_STARTED},
            10,
        )
    recovered = query_attempt_after_lost_start(transport, 9, 2)
    assert recovered.message_type is MessageType.ATTEMPT_STATUS


def test_status_query_recovers_only_matching_started_or_done_state(
    evidence_spy: EvidenceSpy,
) -> None:
    """Accept verifiable alternate TX-start evidence without retransmission.

    Direct call tree (static source order):
        test_status_query_recovers_only_matching_started_or_done_state
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- transport.command
        +-- pytest.raises
        +-- pack_start_tx
        +-- query_attempt_after_lost_start
        `-- len
    """
    calls = {"count": 0}

    def responder(wire: bytes) -> bytes:
        """Drop the start acknowledgement and report the completed attempt during recovery.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- hello_report_wire
            +-- pack_attempt_status
            +-- encode_wire
            `-- Message
        """
        calls["count"] += 1
        command = decode_wire(wire)
        if calls["count"] == 1:
            return hello_report_wire(command)
        if calls["count"] == 2:
            return b""
        if calls["count"] == 3:
            payload = pack_attempt_status(9, 2, AttemptState.TX_DONE, 0)
            return encode_wire(
                Message(MessageType.ATTEMPT_STATUS, command.msg_seq, payload)
            )
        return hello_report_wire(command)

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    with pytest.raises(CommandTimeout):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(9, 2),
            {MessageType.TX_STARTED},
            2,
        )
    recovered = query_attempt_after_lost_start(transport, 9, 2)
    assert recovered.message_type is MessageType.ATTEMPT_STATUS
    assert len(transport.port.writes) == 4


def test_lost_start_recovery_preserves_original_terminal_trigger(
    evidence_spy: EvidenceSpy,
) -> None:
    """Accept TX_DONE only with the original uncertain START_TX sequence.

    Direct call tree (static source order):
        test_lost_start_recovery_preserves_original_terminal_trigger
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- transport.command
        +-- pytest.raises
        +-- pack_start_tx
        +-- query_attempt_after_lost_start
        `-- transport.pop_event_receipt
    """
    call_count = 0
    original_start_sequence = 0

    def responder(wire: bytes) -> bytes:
        """Return the original TX_DONE event alongside the later status-query response.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- hello_report_wire
            +-- pack_start_tx
            +-- Message
            +-- pack_attempt_status
            `-- encode_wire
        """
        nonlocal call_count
        nonlocal original_start_sequence
        command = decode_wire(wire)
        call_count += 1
        if call_count == 1:
            return hello_report_wire(command)
        if call_count == 2:
            original_start_sequence = command.msg_seq
            return b""
        if call_count == 3:
            done_payload = pack_start_tx(9, 2)
            done = Message(
                MessageType.TX_DONE,
                original_start_sequence,
                done_payload,
            )
            status_payload = pack_attempt_status(
                9,
                2,
                AttemptState.TX_DONE,
                0,
            )
            status = Message(
                MessageType.ATTEMPT_STATUS,
                command.msg_seq,
                status_payload,
            )
            return encode_wire(done) + encode_wire(status)
        return hello_report_wire(command)

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    with pytest.raises(CommandTimeout):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(9, 2),
            {MessageType.TX_STARTED},
            2,
        )
    query_attempt_after_lost_start(transport, 9, 2)
    terminal = transport.pop_event_receipt()
    assert terminal is not None
    assert terminal.message.message_type is MessageType.TX_DONE
    assert terminal.message.msg_seq == original_start_sequence


def test_transport_exposes_exact_last_outgoing_wire_receipt(
    evidence_spy: EvidenceSpy,
) -> None:
    """Join runner timing to the exact raw TX record, not a guessed index.

    Direct call tree (static source order):
        test_transport_exposes_exact_last_outgoing_wire_receipt
        +-- FakeClock
        +-- EndpointTransport
        +-- ScriptedBytePort.acking_for
        `-- transport.command
    """
    clock = FakeClock()
    transport = EndpointTransport(
        ScriptedBytePort.acking_for(1),
        1,
        evidence_spy,
        clock,
    )
    transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    receipt = transport.last_outgoing_receipt
    assert receipt is not None
    assert receipt.serial_event_index == 0
    assert receipt.monotonic_ns == evidence_spy.wires[0].monotonic_ns
    assert receipt.wire_bytes == evidence_spy.wires[0].wire_bytes


def test_status_recovery_rejects_endpoint_boot_count_change(
    evidence_spy: EvidenceSpy,
) -> None:
    """Never accept post-reset state as proof of the original RF action.

    Direct call tree (static source order):
        test_status_recovery_rejects_endpoint_boot_count_change
        +-- ScriptedBytePort.with_responder
        +-- EndpointTransport
        +-- FakeClock
        +-- transport.command
        +-- pytest.raises
        +-- pack_start_tx
        `-- query_attempt_after_lost_start
    """
    call_count = 0

    def hello_payload(boot_count: int) -> bytes:
        """Encode a HELLO identity report with the requested boot count.

        Inputs: boot_count.
        Returns: bytes.

        Direct call tree (static source order):
            hello_payload
            +-- bytes
            `-- pack_hello_report
        """
        zero_hash = bytes(32)
        return pack_hello_report(
            1,
            boot_count,
            0x12,
            AttemptState.STANDBY,
            zero_hash,
            zero_hash,
            zero_hash,
        )

    def responder(wire: bytes) -> bytes:
        """Change the reported boot count after a lost start to test reset detection.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- encode_wire
            +-- Message
            +-- hello_payload
            `-- pack_attempt_status
        """
        nonlocal call_count
        command = decode_wire(wire)
        call_count += 1
        if call_count == 1:
            return encode_wire(
                Message(MessageType.HELLO_REPORT, command.msg_seq, hello_payload(1))
            )
        if call_count == 2:
            return b""
        if call_count == 3:
            status = pack_attempt_status(9, 2, AttemptState.TX_STARTED, 0)
            return encode_wire(
                Message(MessageType.ATTEMPT_STATUS, command.msg_seq, status)
            )
        return encode_wire(
            Message(MessageType.HELLO_REPORT, command.msg_seq, hello_payload(2))
        )

    port = ScriptedBytePort.with_responder(responder)
    transport = EndpointTransport(port, 1, evidence_spy, FakeClock())
    transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    with pytest.raises(CommandTimeout):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(9, 2),
            {MessageType.TX_STARTED},
            2,
        )
    with pytest.raises(ProceduralFault, match="boot count"):
        query_attempt_after_lost_start(transport, 9, 2)
    with pytest.raises(UnsafeRetry):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(9, 2),
            {MessageType.TX_STARTED},
            2,
        )


@pytest.mark.parametrize(
    "status_context,status_state",
    (
        ((9, 3), AttemptState.TX_DONE),
        ((9, 2), AttemptState.STANDBY),
        ((9, 2), AttemptState.ERROR),
    ),
)
def test_status_query_rejects_bad_context_or_unverifiable_state(
    evidence_spy: EvidenceSpy,
    status_context: tuple[int, int],
    status_state: AttemptState,
) -> None:
    """Fail closed when a status reply cannot prove the original RF start.

    Direct call tree (static source order):
        test_status_query_rejects_bad_context_or_unverifiable_state
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- transport.command
        +-- pytest.raises
        +-- pack_start_tx
        `-- query_attempt_after_lost_start
    """
    call_count = {"value": 0}

    def responder(wire: bytes) -> bytes:
        """Drop TX_STARTED and return the selected recovery context and state.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- hello_report_wire
            +-- pack_attempt_status
            +-- encode_wire
            `-- Message
        """
        call_count["value"] += 1
        command = decode_wire(wire)
        if call_count["value"] == 1:
            return hello_report_wire(command)
        if call_count["value"] == 2:
            return b""
        payload = pack_attempt_status(
            status_context[0],
            status_context[1],
            status_state,
            0,
        )
        return encode_wire(Message(MessageType.ATTEMPT_STATUS, command.msg_seq, payload))

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    with pytest.raises(CommandTimeout):
        transport.command(
            MessageType.START_TX,
            pack_start_tx(9, 2),
            {MessageType.TX_STARTED},
            2,
        )
    with pytest.raises(ProceduralFault):
        query_attempt_after_lost_start(transport, 9, 2)


def test_endpoint_error_is_typed_and_not_a_radio_terminal(
    evidence_spy: EvidenceSpy,
) -> None:
    """Raise endpoint errors as procedural evidence rather than packet results.

    Direct call tree (static source order):
        test_endpoint_error_is_typed_and_not_a_radio_terminal
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- FakeClock
        +-- pytest.raises
        `-- transport.command
    """
    def responder(wire: bytes) -> bytes:
        """Reject HELLO with a structured endpoint error carrying its command sequence.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            +-- decode_wire
            +-- pack_endpoint_error
            +-- encode_wire
            `-- Message
        """
        command = decode_wire(wire)
        payload = pack_endpoint_error(
            1,
            0,
            MessageType.HELLO,
            ErrorCode.BAD_STATE,
            4,
        )
        return encode_wire(Message(MessageType.ENDPOINT_ERROR, command.msg_seq, payload))

    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        FakeClock(),
    )
    with pytest.raises(EndpointReportedError) as captured:
        transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 500)
    assert captured.value.error_code is ErrorCode.BAD_STATE


def test_partial_fragment_uses_250_ms_serial_deadline_not_rf_timeout(
    evidence_spy: EvidenceSpy,
) -> None:
    """Classify parser inter-byte expiry separately from a command deadline.

    Direct call tree (static source order):
        test_partial_fragment_uses_250_ms_serial_deadline_not_rf_timeout
        +-- FakeClock
        +-- EndpointTransport
        +-- ScriptedBytePort.with_responder
        +-- pytest.raises
        `-- transport.command
    """
    def responder(wire: bytes) -> bytes:
        """Return an unfinished fragment to exercise the inter-byte timeout boundary.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            `-- [no direct function calls; local state/return only]
        """
        del wire
        return b"\x05\x53"

    clock = FakeClock()
    transport = EndpointTransport(
        ScriptedBytePort.with_responder(responder),
        1,
        evidence_spy,
        clock,
    )
    with pytest.raises(SerialProtocolFailure, match="inter-byte"):
        transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 300)


def test_interbyte_timeout_discards_matching_raw_fragment_until_delimiter(
    evidence_spy: EvidenceSpy,
) -> None:
    """Do not later mislabel a timed-out partial body as a complete RX wire.

    Direct call tree (static source order):
        test_interbyte_timeout_discards_matching_raw_fragment_until_delimiter
        +-- FakeClock
        +-- ScriptedBytePort.with_responder
        +-- EndpointTransport
        +-- pytest.raises
        +-- transport.command
        `-- received_wires.append
    """
    response_number = 0

    def responder(wire: bytes) -> bytes:
        """Return a partial fragment first and delimit it before the next normal response.

        Inputs: wire.
        Returns: bytes.

        Direct call tree (static source order):
            responder
            `-- ScriptedBytePort._default_response
        """
        nonlocal response_number
        if response_number == 0:
            response_number += 1
            return b"\x05\x53"
        response_number += 1
        return b"\x00" + ScriptedBytePort._default_response(wire)

    clock = FakeClock()
    port = ScriptedBytePort.with_responder(responder)
    transport = EndpointTransport(port, 1, evidence_spy, clock)
    with pytest.raises(SerialProtocolFailure, match="inter-byte"):
        transport.command(MessageType.HELLO, b"", {MessageType.HELLO_REPORT}, 300)
    report = transport.command(
        MessageType.HELLO,
        b"",
        {MessageType.HELLO_REPORT},
        300,
    )
    received_wires = []
    for observation in evidence_spy.wires:
        if observation.direction == 1:
            received_wires.append(observation.wire_bytes)
    assert received_wires == [report.wire_bytes]


def test_real_adapter_imports_pyserial_lazily_and_fails_closed(monkeypatch) -> None:
    """Keep software-only tests importable when optional pyserial is absent.

    Direct call tree (static source order):
        test_real_adapter_imports_pyserial_lazily_and_fails_closed
        +-- monkeypatch.setattr
        +-- pytest.raises
        `-- open_nano_port
    """
    original_import = builtins.__import__

    def missing_serial(name, globals=None, locals=None, fromlist=(), level=0):
        """Simulate unavailable pyserial while delegating every other import normally.

        Inputs: name, globals, locals, fromlist, level.

        Direct call tree (static source order):
            missing_serial
            +-- ImportError
            `-- original_import
        """
        if name == "serial":
            raise ImportError("not installed")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_serial)
    with pytest.raises(RuntimeError, match="pyserial"):
        open_nano_port("/dev/never-opened")


def test_start_register_error_displays_register_and_actual_value():
    """Expose the failed START_TX register without mislabeling legacy zero detail.

    Direct call tree (static source order):
        test_start_register_error_displays_register_and_actual_value
        +-- pack_endpoint_error
        +-- EndpointReportedError
        +-- Message
        `-- str
    """
    payload = pack_endpoint_error(1, 0, MessageType.START_TX, ErrorCode.REGISTER_READBACK, 0x0189)
    error = EndpointReportedError(Message(MessageType.ENDPOINT_ERROR, 5, payload))
    assert "START_TX" in str(error)
    assert "register=0x01" in str(error)
    assert "actual=0x89" in str(error)
    legacy = pack_endpoint_error(1, 0, MessageType.START_TX, ErrorCode.REGISTER_READBACK, 0)
    assert "register=" not in str(EndpointReportedError(Message(MessageType.ENDPOINT_ERROR, 5, legacy)))
