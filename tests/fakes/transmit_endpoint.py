"""Supply synthetic serial replies to the real main_transmit control flow.

This fixture uses production codecs and configuration tables. It does not execute
Nano firmware, model RF propagation, or establish physical transmission results.
"""

from host.radio import serial_protocol as p
from host.radio.single_transmit import TransmitEvidence
from tests.fakes.fake_endpoints import ScriptedBytePort


class TransmitterReplies:
    """Provide bytes at the hardware boundary using the production wire codec."""

    def __init__(self, truth, fault=None):
        """Bind real parameter tables to a synthetic endpoint identity and optional fault.

        Direct call tree (static source order):
            __init__
            `-- [no direct function calls; local state/return only]
        """
        self.truth = truth
        self.fault = fault
        self.manifest = {"endpoint_id": 1, "firmware_sha256": "11" * 32, "board_sha256": "22" * 32}
        self.loaded = []
        self.types = []
        self.profile_code = p.ProfileCode.LORA
        self.pa = truth.pa_settings[0]

    def __call__(self, wire):
        """Decode one real host command and encode its scripted synthetic response.

        Direct call tree (static source order):
            __call__
            +-- p.decode_wire
            +-- self.types.append
            +-- bytes.fromhex
            +-- bytes
            +-- p.pack_hello_report
            +-- p.pack_ack
            +-- p.unpack_apply_profile
            +-- registers.append
            +-- p.unpack_set_pa
            +-- p.pack_config_report
            +-- tuple
            +-- p.unpack_load_tx
            +-- self.loaded.append
            +-- p.pack_tx_ready
            +-- p.unpack_start_tx
            +-- p.encode_wire
            +-- p.Message
            +-- p.pack_tx_started
            +-- p.pack_tx_done
            `-- AssertionError
        """
        command = p.decode_wire(wire)
        kind = command.message_type
        self.types.append(kind)
        if kind == p.MessageType.HELLO:
            firmware_hash = bytes.fromhex(self.manifest["firmware_sha256"])
            if self.fault == "identity":
                firmware_hash = bytes(32)
            payload = p.pack_hello_report(1, 1, 0x12, p.AttemptState.STANDBY, firmware_hash,
                                          bytes.fromhex(self.truth.profile_registers_sha256),
                                          bytes.fromhex(self.manifest["board_sha256"]))
            response = p.MessageType.HELLO_REPORT
        elif kind == p.MessageType.RESET_TO_STANDBY:
            payload = p.pack_ack(kind)
            response = p.MessageType.ACK
        elif kind in (p.MessageType.APPLY_PROFILE, p.MessageType.SET_PA):
            if kind == p.MessageType.APPLY_PROFILE:
                selected = p.unpack_apply_profile(command.payload)
                self.profile_code = selected.profile_code
                for item in self.truth.profiles:
                    if item.profile_code == self.profile_code:
                        profile_id = item.profile_id
                        break
                else:
                    raise StopIteration
                registers = []
                for row in self.truth.register_rows:
                    if row.profile_id == profile_id:
                        registers.append((row.address, row.expected_readback))
            else:
                selected = p.unpack_set_pa(command.payload)
                for item in self.truth.pa_settings:
                    if item.pa_command_dbm == selected.pa_command_dbm:
                        self.pa = item
                        break
                else:
                    raise StopIteration
                registers = [(9, self.pa.reg_pa_config), (0x4D, self.pa.reg_pa_dac),
                             (11, self.pa.reg_ocp)]
            if self.fault == "readback":
                registers = []
            payload = p.pack_config_report(kind, self.profile_code,
                                          self.pa.pa_command_dbm, self.pa.reg_pa_config,
                                          self.pa.reg_pa_dac, self.pa.reg_ocp, tuple(registers))
            response = p.MessageType.CONFIG_REPORT
        elif kind == p.MessageType.LOAD_TX:
            loaded = p.unpack_load_tx(command.payload)
            self.loaded.append(loaded)
            frf = loaded.reg_frf_word
            if self.fault == "frf":
                frf += 1
            payload = p.pack_tx_ready(loaded.run_token, loaded.attempt_index, frf)
            response = p.MessageType.TX_READY
        elif kind == p.MessageType.START_TX:
            started = p.unpack_start_tx(command.payload)
            if self.fault == "start_timeout":
                return b""
            wire = p.encode_wire(p.Message(p.MessageType.TX_STARTED, command.msg_seq,
                                p.pack_tx_started(started.run_token, started.attempt_index)))
            if self.fault == "done_timeout":
                return wire
            index = started.attempt_index
            if self.fault == "wrong_done":
                index += 1
            return wire + p.encode_wire(p.Message(p.MessageType.TX_DONE, command.msg_seq,
                                        p.pack_tx_done(started.run_token, index)))
        else:
            raise AssertionError(f"Unexpected command: {kind}")
        return p.encode_wire(p.Message(response, command.msg_seq, payload))


class TeachingBytePort(ScriptedBytePort):
    """Expose the serial lifecycle used by main while keeping all bytes in memory."""

    def __init__(self, responder):
        """Start a fragmented in-memory port and record resets and closure.

        Direct call tree (static source order):
            __init__
            +-- super
            `-- super(...).__init__
        """
        super().__init__(responder, chunks=[1, 3, 17])
        self.reset_count = 0
        self.closed = False

    def reset_input_buffer(self):
        """Discard staged input as the real host does after Nano boot settling.

        Direct call tree (static source order):
            reset_input_buffer
            `-- self._pending.clear
        """
        self._pending.clear()
        self.reset_count += 1

    def close(self):
        """Mark the synthetic port closed for the production finally-path check.

        Direct call tree (static source order):
            close
            `-- [no direct function calls; local state/return only]
        """
        self.closed = True


class SimulatedTransmitEvidence(TransmitEvidence):
    """Use the production log writer while labelling every event as simulated."""

    def record(self, event, **fields):
        """Override physical-origin wording before the production writer persists it.

        Direct call tree (static source order):
            record
            +-- super
            `-- super(...).record
        """
        fields["data_origin"] = "simulated_serial"
        return super().record(event, **fields)
