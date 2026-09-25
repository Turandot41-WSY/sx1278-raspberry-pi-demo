"""Configure a local Nano and preserve serial evidence for either radio role."""

import json
import os
from pathlib import Path

from firmware.host.profile_truth import ProfileTruth
from firmware.host import serial_protocol as protocol
from firmware.host.serial_transport import EndpointTransport


class SerialEvidence:
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


def configure_endpoint(transport: EndpointTransport, truth: ProfileTruth,
                          manifest: dict, profile_id: str, pa_dbm: int,
                          timeout_ms: int = 2000) -> None:
    """Verify the flashed identity and configure the production radio driver.

    Processing flow:
        Select shared profile/PA -> verify HELLO hashes -> reset to standby
        -> apply profile and compare masked registers -> apply PA and readbacks.

    Direct call tree (static source order):
        configure_endpoint
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
        raise ValueError("flashed profile table differs from firmware/config/profile_registers.csv")
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
