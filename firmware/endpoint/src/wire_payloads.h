#ifndef SX1278_WIRE_PAYLOADS_H
#define SX1278_WIRE_PAYLOADS_H

#include <stddef.h>
#include <stdint.h>

#include "byte_codec.h"
#include "protocol_types.h"

namespace sx1278 {

struct ApplyProfileCommand {
    uint8_t profile_code;
    uint8_t table_hash[32];
};

struct SetPaCommand {
    int8_t command_dbm;
    uint8_t reg_ocp;
};

struct LoadTxCommand {
    AttemptKey key;
    uint32_t reg_frf_word;
    uint8_t frame[64];
};

struct ArmRxCommand {
    AttemptKey key;
    uint16_t window_ms;
};

/** Validate one exact empty command payload.
 *
 */
inline bool parse_empty_payload(const MessageView& message) {
    bool type_is_empty_command = false;
    if (message.type == MessageType::Hello) {
        type_is_empty_command = true;
    }
    if (message.type == MessageType::ResetToStandby) {
        type_is_empty_command = true;
    }
    if (!type_is_empty_command) {
        return false;
    }
    return message.payload_length == 0U;
}

/** Read a nonzero-run attempt key without partially publishing on failure.
 *
 *
 * Processing flow:
 *   reader -> two uint32 fields -> nonzero RunToken check -> output key
 */
inline bool read_key(ByteReader* reader, AttemptKey* output) {
    if (reader == 0) {
        return false;
    }
    if (output == 0) {
        return false;
    }
    AttemptKey parsed = {};
    if (!reader->read_u32(parsed.run_token)) {
        return false;
    }
    if (!reader->read_u32(parsed.attempt_index)) {
        return false;
    }
    if (!is_valid_attempt_key(parsed)) {
        return false;
    }
    *output = parsed;
    return true;
}

/** Decode the exact APPLY_PROFILE payload and bounded profile code.
 *
 *
 * Processing flow:
 *   exact 33 bytes -> profile code/hash -> code/trailing checks -> command
 */
inline bool parse_apply_profile(
    const MessageView& message,
    ApplyProfileCommand* output
) {
    if (output == 0) {
        return false;
    }
    if (message.type != MessageType::ApplyProfile) {
        return false;
    }
    if (message.payload_length != 33U) {
        return false;
    }
    ApplyProfileCommand parsed = {};
    ByteReader reader(message.payload, message.payload_length);
    if (!reader.read_u8(parsed.profile_code)) {
        return false;
    }
    if (parsed.profile_code > generated::kProfileOok) {
        return false;
    }
    if (!reader.read_bytes(parsed.table_hash, sizeof(parsed.table_hash))) {
        return false;
    }
    if (!reader.finished()) {
        return false;
    }
    *output = parsed;
    return true;
}

/** Decode the exact SET_PA command bytes.
 *
 *
 * Processing flow:
 *   exact two bytes -> signed PA byte + RegOcp -> trailing check -> command
 */
inline bool parse_set_pa(const MessageView& message, SetPaCommand* output) {
    if (output == 0) {
        return false;
    }
    if (message.type != MessageType::SetPa) {
        return false;
    }
    if (message.payload_length != 2U) {
        return false;
    }
    SetPaCommand parsed = {};
    ByteReader reader(message.payload, message.payload_length);
    if (!reader.read_i8(parsed.command_dbm)) {
        return false;
    }
    if (!reader.read_u8(parsed.reg_ocp)) {
        return false;
    }
    if (!reader.finished()) {
        return false;
    }
    *output = parsed;
    return true;
}

/** Decode the exact 76-byte LOAD_TX payload and its 64-byte frame.
 *
 *
 * Processing flow:
 *   exact payload -> key/FRF/length -> require length 64 -> frame -> command
 */
inline bool parse_load_tx(const MessageView& message, LoadTxCommand* output) {
    if (output == 0) {
        return false;
    }
    if (message.type != MessageType::LoadTx) {
        return false;
    }
    if (message.payload_length != 76U) {
        return false;
    }
    LoadTxCommand parsed = {};
    ByteReader reader(message.payload, message.payload_length);
    if (!read_key(&reader, &parsed.key)) {
        return false;
    }
    if (!reader.read_u24(parsed.reg_frf_word)) {
        return false;
    }
    uint8_t frame_length = 0U;
    if (!reader.read_u8(frame_length)) {
        return false;
    }
    if (frame_length != kFrameLength) {
        return false;
    }
    if (!reader.read_bytes(parsed.frame, sizeof(parsed.frame))) {
        return false;
    }
    if (!reader.finished()) {
        return false;
    }
    *output = parsed;
    return true;
}

/** Decode an ARM_RX key and its unsigned 16-bit receive-window field.
 *
 *
 * Processing flow:
 *   exact ten bytes -> attempt key -> receive window -> trailing-byte check
 */
inline bool parse_arm_rx(const MessageView& message, ArmRxCommand* output) {
    if (output == 0) {
        return false;
    }
    if (message.type != MessageType::ArmRx) {
        return false;
    }
    if (message.payload_length != 10U) {
        return false;
    }
    ArmRxCommand parsed = {};
    ByteReader reader(message.payload, message.payload_length);
    if (!read_key(&reader, &parsed.key)) {
        return false;
    }
    if (!reader.read_u16(parsed.window_ms)) {
        return false;
    }
    if (parsed.window_ms == 0U) {
        return false;
    }
    if (!reader.finished()) {
        return false;
    }
    *output = parsed;
    return true;
}

/** Decode the shared eight-byte attempt-key command shape.
 *
 *
 * Processing flow:
 *   supported type -> exact eight bytes -> key -> trailing check -> output
 */
inline bool parse_attempt_key(const MessageView& message, AttemptKey* output) {
    if (output == 0) {
        return false;
    }
    bool type_is_supported = false;
    if (message.type == MessageType::StartTx) {
        type_is_supported = true;
    }
    if (message.type == MessageType::CancelAttempt) {
        type_is_supported = true;
    }
    if (message.type == MessageType::GetAttemptStatus) {
        type_is_supported = true;
    }
    if (!type_is_supported) {
        return false;
    }
    if (message.payload_length != 8U) {
        return false;
    }
    AttemptKey parsed = {};
    ByteReader reader(message.payload, message.payload_length);
    if (!read_key(&reader, &parsed)) {
        return false;
    }
    if (!reader.finished()) {
        return false;
    }
    *output = parsed;
    return true;
}

/** Initialize a fixed payload output contract before any byte is written.
 *
 * Processing flow:
 *   size pointer -> publish zero -> capacity/pointer checks -> ready state
 */
inline bool prepare_payload_output(
    uint8_t* output,
    size_t capacity,
    size_t required_size,
    size_t* output_size
) {
    if (output_size == 0) {
        return false;
    }
    *output_size = 0U;
    if (required_size > capacity) {
        return false;
    }
    if (required_size > 0U) {
        if (output == 0) {
            return false;
        }
    }
    return true;
}

/** Write one validated attempt key in big-endian field order.
 *
 *
 * Processing flow:
 *   writer/key checks -> RunToken -> AttemptIndex -> success
 */
inline bool write_key(ByteWriter* writer, const AttemptKey& key) {
    if (writer == 0) {
        return false;
    }
    if (!is_valid_attempt_key(key)) {
        return false;
    }
    if (!writer->put_u32(key.run_token)) {
        return false;
    }
    if (!writer->put_u32(key.attempt_index)) {
        return false;
    }
    return true;
}

/** Encode the ACK payload with the protocol-v1 zero status.
 *
 */
inline bool encode_ack(
    uint8_t related_type,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 2U, output_size)) {
        return false;
    }
    if (!is_command_type_code(related_type)) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!writer.put_u8(related_type)) {
        return false;
    }
    if (!writer.put_u8(0U)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode the shared TX/RX terminal attempt-key payload.
 *
 */
inline bool encode_attempt(
    const AttemptKey& key,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 8U, output_size)) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!write_key(&writer, key)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode TX_READY with the absolute 24-bit FRF readback.
 *
 *
 * Processing flow:
 *   fixed output -> attempt key -> uint24 FRF readback -> payload size
 */
inline bool encode_tx_ready(
    const AttemptKey& key,
    uint32_t reg_frf_readback,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 11U, output_size)) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!write_key(&writer, key)) {
        return false;
    }
    if (!writer.put_u24(reg_frf_readback)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode RX_ARMED with nominal FRF readback and receive window.
 *
 *
 * Processing flow:
 *   fixed output -> key -> FRF readback -> uint16 window -> payload size
 */
inline bool encode_rx_armed(
    const AttemptKey& key,
    uint32_t reg_frf_readback,
    uint16_t window_ms,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 13U, output_size)) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!write_key(&writer, key)) {
        return false;
    }
    if (!writer.put_u24(reg_frf_readback)) {
        return false;
    }
    if (!writer.put_u16(window_ms)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode ATTEMPT_STATUS with validated state and error codes.
 *
 *
 * Processing flow:
 *   state/error validation -> key -> state -> error -> payload size
 */
inline bool encode_attempt_status(
    const AttemptKey& key,
    AttemptState state,
    ErrorCode error,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 11U, output_size)) {
        return false;
    }
    if (!is_valid_attempt_state(state)) {
        return false;
    }
    if (!is_valid_error_code(error, true)) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!write_key(&writer, key)) {
        return false;
    }
    uint8_t encoded_state = static_cast<uint8_t>(state);
    if (!writer.put_u8(encoded_state)) {
        return false;
    }
    uint16_t encoded_error = static_cast<uint16_t>(error);
    if (!writer.put_u16(encoded_error)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode ENDPOINT_ERROR including the unique optional no-context pair.
 *
 *
 * Processing flow:
 *   related/error validation -> context -> codes/detail -> payload size
 */
inline bool encode_error(
    const AttemptKey& key,
    uint8_t related_type,
    ErrorCode error,
    uint16_t detail,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 13U, output_size)) {
        return false;
    }
    if (!is_valid_attempt_key(key)) {
        return false;
    }
    if (!is_valid_error_code(error, false)) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!write_key(&writer, key)) {
        return false;
    }
    if (!writer.put_u8(related_type)) {
        return false;
    }
    uint16_t encoded_error = static_cast<uint16_t>(error);
    if (!writer.put_u16(encoded_error)) {
        return false;
    }
    if (!writer.put_u16(detail)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode RX_PACKET with the actual radio length and any retained FIFO bytes.
 *
 * Inputs: Attempt context, IRQ CRC status, actual radio length, raw metrics,
 * optional FIFO buffer, output buffer capacity and output size pointer.
 * Output: A validated RX_PACKET payload and its size; false on invalid input.
 * Project choice: lengths above the receive buffer limit of 64 produce only
 * the metadata prefix of 13 bytes. No payload pointer is read for those reports. Lengths
 * from zero through 64 require exactly the observed number of FIFO bytes.
 *
 * Processing flow:
 *   radio length -> retained byte count -> metric checks -> metadata -> retained bytes
 */
inline bool encode_rx_packet(
    const AttemptKey& key,
    bool phy_crc_ok,
    uint8_t received_length,
    uint8_t metrics_flags,
    uint8_t rssi_raw,
    int8_t snr_raw,
    const uint8_t* payload,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    size_t received_size = static_cast<size_t>(received_length);
    if (received_length > kFrameLength) {
        received_size = 0U;
    }
    size_t required_size = 13U + received_size;
    if (!prepare_payload_output(output, capacity, required_size, output_size)) {
        return false;
    }
    if (metrics_flags > 0x03U) {
        return false;
    }
    uint8_t rssi_flag = metrics_flags & 0x01U;
    if (rssi_flag == 0U) {
        if (rssi_raw != 0U) {
            return false;
        }
    }
    uint8_t snr_flag = metrics_flags & 0x02U;
    if (snr_flag == 0U) {
        if (snr_raw != 0) {
            return false;
        }
    }
    if (received_size > 0U) {
        if (payload == 0) {
            return false;
        }
    }
    ByteWriter writer(output, capacity);
    if (!write_key(&writer, key)) {
        return false;
    }
    uint8_t crc_value = 0U;
    if (phy_crc_ok) {
        crc_value = 1U;
    }
    if (!writer.put_u8(crc_value)) {
        return false;
    }
    if (!writer.put_u8(received_length)) {
        return false;
    }
    if (!writer.put_u8(metrics_flags)) {
        return false;
    }
    if (!writer.put_u8(rssi_raw)) {
        return false;
    }
    if (!writer.put_i8(snr_raw)) {
        return false;
    }
    if (!writer.put_bytes(payload, received_size)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode the fixed 106-byte HELLO_REPORT identity payload.
 *
 *
 * Processing flow:
 *   identity validation -> scalar fields -> three 32-byte hashes -> payload size
 */
inline bool encode_hello_report(
    uint32_t endpoint_id,
    uint32_t boot_count,
    uint8_t reg_version,
    AttemptState state,
    const uint8_t firmware_hash[32],
    const uint8_t profile_table_hash[32],
    const uint8_t board_hash[32],
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (!prepare_payload_output(output, capacity, 106U, output_size)) {
        return false;
    }
    if (!is_valid_attempt_state(state)) {
        return false;
    }
    if (firmware_hash == 0) {
        return false;
    }
    if (profile_table_hash == 0) {
        return false;
    }
    if (board_hash == 0) {
        return false;
    }
    ByteWriter writer(output, capacity);
    if (!writer.put_u32(endpoint_id)) {
        return false;
    }
    if (!writer.put_u32(boot_count)) {
        return false;
    }
    if (!writer.put_u8(reg_version)) {
        return false;
    }
    uint8_t encoded_state = static_cast<uint8_t>(state);
    if (!writer.put_u8(encoded_state)) {
        return false;
    }
    if (!writer.put_bytes(firmware_hash, 32U)) {
        return false;
    }
    if (!writer.put_bytes(profile_table_hash, 32U)) {
        return false;
    }
    if (!writer.put_bytes(board_hash, 32U)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

/** Encode one bounded CONFIG_REPORT register-readback segment.
 *
 *
 * Processing flow:
 *   count/type/profile checks -> seven-byte prefix -> address/value pairs -> size
 */
inline bool encode_config_report(
    uint8_t related_type,
    uint8_t profile_code,
    int8_t pa_command_dbm,
    uint8_t reg_pa_config,
    uint8_t reg_pa_dac,
    uint8_t reg_ocp,
    const uint8_t* address_value_pairs,
    uint8_t register_count,
    uint8_t* output,
    size_t capacity,
    size_t* output_size
) {
    if (output_size == 0) {
        return false;
    }
    *output_size = 0U;
    if (register_count > 55U) {
        return false;
    }
    bool related_to_profile = related_type == generated::kMessageApplyProfile;
    bool related_to_pa = related_type == generated::kMessageSetPa;
    if (!related_to_profile) {
        if (!related_to_pa) {
            return false;
        }
    }
    if (profile_code > generated::kProfileOok) {
        return false;
    }
    size_t pair_size = static_cast<size_t>(register_count);
    pair_size *= 2U;
    size_t required_size = 7U + pair_size;
    if (!prepare_payload_output(output, capacity, required_size, output_size)) {
        return false;
    }
    if (pair_size > 0U) {
        if (address_value_pairs == 0) {
            return false;
        }
    }
    ByteWriter writer(output, capacity);
    if (!writer.put_u8(related_type)) {
        return false;
    }
    if (!writer.put_u8(profile_code)) {
        return false;
    }
    if (!writer.put_i8(pa_command_dbm)) {
        return false;
    }
    if (!writer.put_u8(reg_pa_config)) {
        return false;
    }
    if (!writer.put_u8(reg_pa_dac)) {
        return false;
    }
    if (!writer.put_u8(reg_ocp)) {
        return false;
    }
    if (!writer.put_u8(register_count)) {
        return false;
    }
    if (!writer.put_bytes(address_value_pairs, pair_size)) {
        return false;
    }
    *output_size = writer.size();
    return true;
}

}  // namespace sx1278

#endif
