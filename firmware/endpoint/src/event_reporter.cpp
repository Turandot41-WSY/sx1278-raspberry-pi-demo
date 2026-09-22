#include "event_reporter.h"

#include "byte_codec.h"
#include "cobs.h"
#include "crc16_ccitt.h"

namespace sx1278 {

EventReporter::EventReporter(ByteSink& sink) : sink_(sink) {}

bool EventReporter::send(
    MessageType type,
    uint16_t sequence,
    const uint8_t* payload,
    uint16_t payload_size
) {
    uint8_t type_code = static_cast<uint8_t>(type);
    if (!is_event_type_code(type_code)) {
        return false;
    }
    if (payload_size > kMaxPayload) {
        return false;
    }
    if (payload_size > 0U) {
        if (payload == 0) {
            return false;
        }
    }

    ByteWriter writer(decoded_, sizeof(decoded_));
    if (!writer.put_u16(kMagic)) {
        return false;
    }
    if (!writer.put_u8(kVersion)) {
        return false;
    }
    if (!writer.put_u8(type_code)) {
        return false;
    }
    if (!writer.put_u16(sequence)) {
        return false;
    }
    if (!writer.put_u16(payload_size)) {
        return false;
    }
    if (!writer.put_bytes(payload, payload_size)) {
        return false;
    }
    uint16_t crc = 0U;
    bool crc_ok = crc16_ccitt_false(decoded_, writer.size(), &crc);
    if (!crc_ok) {
        return false;
    }
    if (!writer.put_u16(crc)) {
        return false;
    }

    size_t encoded_size = 0U;
    bool encode_ok = cobs_encode(
        decoded_,
        writer.size(),
        wire_,
        kMaxCobsFragment,
        &encoded_size
    );
    if (!encode_ok) {
        return false;
    }
    if (encoded_size >= kMaxWire) {
        return false;
    }
    wire_[encoded_size] = 0U;
    size_t wire_size = encoded_size + 1U;
    return sink_.write_bytes(wire_, wire_size);
}

}  // namespace sx1278
