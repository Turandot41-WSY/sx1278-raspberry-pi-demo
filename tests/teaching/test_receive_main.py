"""Run the production receive entry with labelled synthetic UART observations."""

import json
from unittest.mock import patch

import pytest

import main_receive
from host.radio import serial_protocol as p
from host.radio.profile_truth import load_profile_truth
from host.common.runtime_config import PROJECT_ROOT
from tests.fakes.fake_clock import FakeClock
from tests.fakes.transmit_endpoint import (
    TransmitterReplies, TeachingBytePort, SimulatedTransmitEvidence,
)


class ReceiverReplies(TransmitterReplies):
    """Supply receive terminals after the real configuration command sequence."""

    def __call__(self, wire):
        """Return one RX_ARMED and a terminal, or reuse the configuration fixture.

        Direct call tree (static source order):
            __call__
            +-- p.decode_wire
            +-- super
            +-- super(...).__call__
            +-- self.types.append
            +-- p.unpack_arm_rx
            +-- p.pack_rx_armed
            +-- p.encode_wire
            +-- p.Message
            +-- p.pack_rx_timeout
            +-- bytes
            +-- range
            `-- p.pack_rx_packet
        """
        command = p.decode_wire(wire)
        if command.message_type != p.MessageType.ARM_RX:
            return super().__call__(wire)
        self.types.append(command.message_type)
        request = p.unpack_arm_rx(command.payload)
        index = request.attempt_index
        frf = 7168000
        if self.fault == "rx_frf":
            frf += 1
        ready = p.pack_rx_armed(request.run_token, index, frf, request.rx_window_ms)
        ready_wire = p.encode_wire(p.Message(p.MessageType.RX_ARMED, command.msg_seq, ready))
        if self.fault == "silence":
            return ready_wire
        if self.fault == "interrupt":
            raise KeyboardInterrupt
        if self.fault == "wrong_rx":
            index += 1
        if request.attempt_index == 0 and self.fault != "wrong_rx":
            kind = p.MessageType.RX_TIMEOUT
            payload = p.pack_rx_timeout(request.run_token, index)
        else:
            kind = p.MessageType.RX_PACKET
            packet = bytes(range(64))
            crc = 1
            length = 64
            if self.fault == "crc":
                crc = 0
            if self.fault == "oversize":
                packet = b""
                length = 65
            payload = p.pack_rx_packet(request.run_token, index, crc, 3, 90, -4,
                                       packet, received_length=length)
        terminal = p.Message(kind, command.msg_seq, payload)
        return ready_wire + p.encode_wire(terminal)


def run_receiver(tmp_path, fault=None, overrides=None):
    """Call main with only the hardware boundary, clock and evidence origin replaced.

    Direct call tree (static source order):
        run_receiver
        +-- load_profile_truth
        +-- ReceiverReplies
        +-- TeachingBytePort
        +-- manifest.write_text
        +-- json.dumps
        +-- dict
        +-- str
        +-- values.update
        +-- values.items
        +-- lines.append
        +-- settings.write_text
        +-- <str literal>.join
        +-- patch
        +-- AssertionError
        +-- patch.object
        +-- main_receive.main
        +-- next
        +-- <BinOp expression>.rglob
        +-- events_path.read_text
        +-- events_path.read_text(...).splitlines
        +-- events.append
        `-- json.loads
    """
    from host.cli import receive_saved
    truth = load_profile_truth(PROJECT_ROOT / "config")
    responder = ReceiverReplies(truth, fault)
    port = TeachingBytePort(responder)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(dict(responder.manifest, compiled=True)), encoding="utf-8")
    settings = tmp_path / "receive.toml"
    values = dict(device="SIMULATED", manifest=str(manifest), output=str(tmp_path / "runs"),
                  profile="LoRa", max_windows=2, rx_window_ms=10, timeout_ms=10,
                  boot_settle_ms=0)
    if overrides is not None:
        values.update(overrides)
    lines = ['action = "listen"', '[listen]']
    for key, value in values.items():
        lines.append(key + " = " + json.dumps(value))
    settings.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (
        patch("serial.Serial", side_effect=AssertionError("physical port opened")),
        patch.object(receive_saved, "open_nano_port", return_value=port),
        patch.object(receive_saved, "SystemClock", FakeClock),
        patch.object(receive_saved, "TransmitEvidence", SimulatedTransmitEvidence),
    ):
        result = main_receive.main(["--settings", str(settings)])
    events_path = next((tmp_path / "runs").rglob("events.jsonl"))
    events = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        events.append(json.loads(line))
    return result, responder, port, events


@pytest.mark.parametrize("profile", ["LoRa", "FSK", "GFSK", "MSK", "GMSK", "OOK"])
def test_listen_rearms_after_timeout_and_saves_exact_packet(tmp_path, capsys, profile):
    """Require actual RX commands and byte preservation without issuing any TX command.

    Direct call tree (static source order):
        test_listen_rearms_after_timeout_and_saves_exact_packet
        +-- run_receiver
        +-- dict
        +-- packets.append
        +-- bytes
        +-- bytes(...).hex
        +-- range
        `-- capsys.readouterr
    """
    result, responder, port, events = run_receiver(tmp_path, overrides=dict(profile=profile))
    assert result == 0
    assert port.closed
    assert responder.types == [p.MessageType.HELLO, p.MessageType.RESET_TO_STANDBY,
                               p.MessageType.APPLY_PROFILE, p.MessageType.SET_PA,
                               p.MessageType.ARM_RX, p.MessageType.ARM_RX]
    packets = []
    for row in events:
        if row["event"] == "rx_packet":
            packets.append(row)
    assert packets[0]["packet_hex"] == bytes(range(64)).hex()
    assert packets[0]["phy_crc_ok"] == 1
    assert packets[0]["rssi_raw"] == 90
    for row in events:
        assert row["data_origin"] == "simulated_serial"
    assert events[-1]["rx_packets"] == 1
    assert events[-1]["rx_timeouts"] == 1
    assert events[-1]["status"] == "COMPLETED"
    assert "RX_ARMED" in capsys.readouterr().out


@pytest.mark.parametrize("fault", ["identity", "readback", "rx_frf", "wrong_rx", "silence"])
def test_listen_stops_on_protocol_failure(tmp_path, fault):
    """Stop uncertain receive sessions and preserve incomplete evidence without retry.

    Direct call tree (static source order):
        test_listen_stops_on_protocol_failure
        +-- run_receiver
        `-- responder.types.count
    """
    result, responder, port, events = run_receiver(tmp_path, fault)
    assert result == 1
    assert port.closed
    assert responder.types.count(p.MessageType.ARM_RX) <= 1
    assert events[-1]["status"] == "INCOMPLETE"


@pytest.mark.parametrize("fault", ["crc", "oversize"])
def test_listen_preserves_bad_radio_observations(tmp_path, fault):
    """Keep bad CRC and oversized length evidence without reporting a good frame.

    Direct call tree (static source order):
        test_listen_preserves_bad_radio_observations
        +-- run_receiver
        `-- packets.append
    """
    result, _, _, events = run_receiver(tmp_path, fault)
    assert result == 0
    packets = []
    for row in events:
        if row["event"] == "rx_packet":
            packets.append(row)
    if fault == "crc":
        assert packets[0]["phy_crc_ok"] == 0
    else:
        assert packets[0]["received_length"] == 65
        assert packets[0]["packet_hex"] == ""


def test_listen_interrupt_closes_port_and_records_stop(tmp_path):
    """Keep an interrupted window distinct from an observed radio timeout.

    Direct call tree (static source order):
        test_listen_interrupt_closes_port_and_records_stop
        `-- run_receiver
    """
    result, _, port, events = run_receiver(tmp_path, "interrupt")
    assert result == 0
    assert port.closed
    assert events[-1]["status"] == "STOPPED_BY_USER"
    assert events[-1]["completed_windows"] == 0
    assert events[-1]["rx_timeouts"] == 0


@pytest.mark.parametrize("overrides", [dict(rx_window_ms=0), dict(rx_window_ms=65536),
                                     dict(max_windows=-1), dict(device="tcp://127.0.0.1:1234"),
                                     dict(profile="unknown"), dict(timeout_ms=0)])
def test_listen_rejects_bad_settings_before_opening_port(tmp_path, overrides):
    """Reject invalid operator choices before any radio session is opened.

    Direct call tree (static source order):
        test_listen_rejects_bad_settings_before_opening_port
        +-- pytest.raises
        +-- run_receiver
        `-- <BinOp expression>.exists
    """
    with pytest.raises(SystemExit) as error:
        run_receiver(tmp_path, overrides=overrides)
    assert error.value.code == 2
    assert not (tmp_path / "runs").exists()
