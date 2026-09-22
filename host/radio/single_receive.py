"""Receive independent radio windows through the existing production protocol.

The receiver's window index identifies a local listening opportunity. It is not
the sender's frame index. This capture supports link bring-up, with gaps between
windows; it supplies no denominator for campaign PER or confidence calculations.
"""

from host.radio import serial_protocol as protocol
from host.radio.serial_transport import EndpointReportedError, EndpointTransport


def receive_window(transport: EndpointTransport, run_token: int, window_index: int,
                   window_ms: int, timeout_ms: int, evidence, *, on_armed=None) -> dict:
    """Arm one receive window and return its correlated packet or radio timeout.

    An optional on_armed callback sends the paired diagnostic frame only after
    RX_ARMED has passed all context, frequency, and window checks.

    The current firmware enforces the project's nominal FRF word 0x6D6000.
    A firmware RX_TIMEOUT is an observed empty window; a missing UART terminal
    is a transport failure and propagates to stop the session.

    Processing flow:
        ARM_RX -> verify identity/frequency/window in RX_ARMED -> announce ready
        -> wait for matching RX_PACKET or RX_TIMEOUT -> preserve observation.

    Direct call tree (static source order):
        receive_window
        +-- protocol.pack_arm_rx
        +-- transport.command
        +-- protocol.unpack_rx_armed
        +-- ValueError
        +-- evidence.record
        +-- print
        +-- on_armed
        +-- transport.wait_event_receipt
        +-- EndpointReportedError
        +-- protocol.unpack_rx_timeout
        +-- protocol.unpack_rx_packet
        `-- terminal.packet.hex
    """
    payload = protocol.pack_arm_rx(run_token, window_index, window_ms)
    reply = transport.command(protocol.MessageType.ARM_RX, payload,
                              {protocol.MessageType.RX_ARMED}, timeout_ms)
    armed = protocol.unpack_rx_armed(reply.payload)
    if (armed.run_token, armed.attempt_index) != (run_token, window_index):
        raise ValueError("RX_ARMED context differs")
    if armed.reg_frf_readback != 0x6D6000 or armed.rx_window_ms != window_ms:
        raise ValueError("RX_ARMED frequency or window differs")
    evidence.record("rx_armed", window_index=window_index,
                    reg_frf_readback=armed.reg_frf_readback, rx_window_ms=window_ms)
    print(f"Window {window_index}: RX_ARMED; listening at 437.5 MHz", flush=True)
    if on_armed is not None:
        on_armed()
    receipt = transport.wait_event_receipt(window_ms + timeout_ms)
    message = receipt.message
    if message.message_type == protocol.MessageType.ENDPOINT_ERROR:
        # The transport already checked the terminal's command and attempt key.
        # Preserve raw detail: diagnostic firmware may assign different meanings.
        raise EndpointReportedError(message)
    if message.message_type == protocol.MessageType.RX_TIMEOUT:
        terminal = protocol.unpack_rx_timeout(message.payload)
        observation: dict = {"event": "rx_timeout"}
    elif message.message_type == protocol.MessageType.RX_PACKET:
        terminal = protocol.unpack_rx_packet(message.payload)
        observation = {
            "event": "rx_packet", "packet_hex": terminal.packet.hex(),
            "received_length": terminal.received_length,
            "phy_crc_ok": terminal.phy_crc_ok, "metrics_flags": terminal.metrics_flags,
            "rssi_raw": terminal.rssi_raw, "snr_raw": terminal.snr_raw,
        }
    else:
        raise ValueError("firmware did not report RX_PACKET or RX_TIMEOUT")
    if (terminal.run_token, terminal.attempt_index) != (run_token, window_index):
        raise ValueError("receive terminal context differs")
    observation["window_index"] = window_index
    return observation
