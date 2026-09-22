#include "command_parser.h"

#include "byte_codec.h"
#include "cobs.h"
#include "crc16_ccitt.h"

namespace sx1278 {

static_assert(
    generated::kErrorContextHeaderBytesRequired == kHeaderSize,
    "parser error context width must match the protocol header"
);

/** Return an initialized parser event that reports no complete message.
 *
 * The result clears error and context validity and uses the generated unavailable
 * sequence and related-type placeholders. No parser buffer is changed.
 */
static ParseEvent no_parse_event() {
    ParseEvent event = {};
    event.kind = ParseKind::None;
    event.error = ErrorCode::None;
    event.detail = 0U;
    event.context_valid = false;
    event.sequence = generated::kUnavailableMsgSeqPlaceholder;
    event.related_type = generated::kUnavailableRelatedTypePlaceholder;
    return event;
}

/** Build a parser error with context only when the decoded header permits it.
 *
 * The supplied error and detail are preserved. Sequence and related_type enter
 * the returned event only when context_valid is true; otherwise the generated
 * unavailable placeholders identify the missing header context.
 *
 * Processing flow:
 *     Error fields -> unavailable context defaults -> optional decoded context
 *     -> complete error event
 */
static ParseEvent parse_failure(
    ErrorCode error,
    uint16_t detail,
    bool context_valid,
    uint16_t sequence,
    uint8_t related_type
) {
    ParseEvent event = {};
    event.kind = ParseKind::Error;
    event.error = error;
    event.detail = detail;
    event.context_valid = context_valid;
    event.sequence = generated::kUnavailableMsgSeqPlaceholder;
    event.related_type = generated::kUnavailableRelatedTypePlaceholder;
    if (context_valid) {
        event.sequence = sequence;
        event.related_type = related_type;
    }
    return event;
}

/** Return a parser error whose sequence and command type are unavailable.
 *
 * The input error and detail describe the framing failure; the returned event
 * explicitly marks command context invalid.
 */
static ParseEvent context_free_failure(ErrorCode error, uint16_t detail) {
    return parse_failure(
        error,
        detail,
        false,
        generated::kUnavailableMsgSeqPlaceholder,
        generated::kUnavailableRelatedTypePlaceholder
    );
}

CommandParser::CommandParser() {
    encoded_size_ = 0U;
    last_byte_ms_ = 0UL;
    have_time_ = false;
    discarding_ = false;
    message_ = MessageView();
}

/** Forget the accumulated fragment length and its last-byte timestamp.
 *
 * The encoded bytes need not be erased because encoded_size_ becomes zero.
 * Discard mode and the previously decoded message remain under their owners'
 * control.
 */
void CommandParser::clear_fragment() {
    encoded_size_ = 0U;
    last_byte_ms_ = 0UL;
    have_time_ = false;
}

ParseEvent CommandParser::poll_timeout(uint32_t now_ms) {
    if (discarding_) {
        return no_parse_event();
    }
    if (encoded_size_ == 0U) {
        return no_parse_event();
    }
    if (!have_time_) {
        return no_parse_event();
    }
    uint32_t elapsed_ms = now_ms - last_byte_ms_;
    if (elapsed_ms < kInterbyteTimeoutMs) {
        return no_parse_event();
    }
    clear_fragment();
    discarding_ = true;
    return context_free_failure(ErrorCode::SerialOverflow, 2U);
}

ParseEvent CommandParser::push(uint8_t byte, uint32_t now_ms) {
    if (discarding_) {
        if (byte == 0U) {
            discarding_ = false;
            clear_fragment();
        }
        return no_parse_event();
    }

    ParseEvent timeout = poll_timeout(now_ms);
    if (timeout.kind == ParseKind::Error) {
        if (byte == 0U) {
            discarding_ = false;
        }
        return timeout;
    }

    if (byte == 0U) {
        if (encoded_size_ == 0U) {
            clear_fragment();
            return no_parse_event();
        }
        return finish_fragment();
    }

    if (encoded_size_ >= kMaxCobsFragment) {
        clear_fragment();
        discarding_ = true;
        return context_free_failure(ErrorCode::SerialOverflow, 1U);
    }
    encoded_[encoded_size_] = byte;
    encoded_size_ += 1U;
    last_byte_ms_ = now_ms;
    have_time_ = true;
    return no_parse_event();
}

/** Validate a delimited command and publish its view into the decoded buffer.
 *
 * The input is the parser's accumulated encoded fragment. The result is either
 * MessageReady or a classified error; context is available only after decoding
 * a complete header. A successful message view remains valid until the decoded
 * buffer is reused by a later fragment.
 *
 * Processing flow:
 *     COBS decode -> release fragment state -> header availability -> magic,
 *     version and command type -> exact payload bounds -> CRC comparison ->
 *     publish message view and matching parser event
 */
ParseEvent CommandParser::finish_fragment() {
    size_t decoded_size = 0U;
    bool decode_ok = cobs_decode(
        encoded_,
        encoded_size_,
        decoded_,
        sizeof(decoded_),
        &decoded_size
    );
    clear_fragment();
    if (!decode_ok) {
        return context_free_failure(ErrorCode::BadCobs, 0U);
    }
    if (decoded_size < generated::kErrorContextHeaderBytesRequired) {
        uint16_t detail = static_cast<uint16_t>(decoded_size);
        return context_free_failure(ErrorCode::BadLength, detail);
    }

    ByteReader header(decoded_, decoded_size);
    uint16_t magic = 0U;
    uint8_t version = 0U;
    uint8_t type_code = 0U;
    uint16_t sequence = 0U;
    uint16_t payload_length = 0U;
    if (!header.read_u16(magic)) {
        return context_free_failure(ErrorCode::BadLength, 0U);
    }
    if (!header.read_u8(version)) {
        return context_free_failure(ErrorCode::BadLength, 0U);
    }
    if (!header.read_u8(type_code)) {
        return context_free_failure(ErrorCode::BadLength, 0U);
    }
    if (!header.read_u16(sequence)) {
        return context_free_failure(ErrorCode::BadLength, 0U);
    }
    if (!header.read_u16(payload_length)) {
        return context_free_failure(ErrorCode::BadLength, 0U);
    }
    size_t minimum_size = kHeaderSize + kCrcSize;
    if (decoded_size < minimum_size) {
        uint16_t detail = static_cast<uint16_t>(decoded_size);
        return parse_failure(
            ErrorCode::BadLength,
            detail,
            true,
            sequence,
            type_code
        );
    }
    if (magic != kMagic) {
        return parse_failure(ErrorCode::BadMagic, magic, true, sequence, type_code);
    }
    if (version != kVersion) {
        return parse_failure(
            ErrorCode::BadVersion,
            version,
            true,
            sequence,
            type_code
        );
    }
    if (!is_command_type_code(type_code)) {
        return parse_failure(
            ErrorCode::UnknownType,
            type_code,
            true,
            sequence,
            type_code
        );
    }
    if (payload_length > kMaxPayload) {
        return parse_failure(
            ErrorCode::BadLength,
            payload_length,
            true,
            sequence,
            type_code
        );
    }
    size_t payload_size = static_cast<size_t>(payload_length);
    size_t expected_size = kHeaderSize + payload_size;
    expected_size += kCrcSize;
    if (decoded_size != expected_size) {
        return parse_failure(
            ErrorCode::BadLength,
            payload_length,
            true,
            sequence,
            type_code
        );
    }

    size_t crc_offset = decoded_size - kCrcSize;
    ByteReader crc_reader(decoded_ + crc_offset, kCrcSize);
    uint16_t received_crc = 0U;
    if (!crc_reader.read_u16(received_crc)) {
        return parse_failure(ErrorCode::BadLength, 0U, true, sequence, type_code);
    }
    uint16_t calculated_crc = 0U;
    bool crc_ok = crc16_ccitt_false(decoded_, crc_offset, &calculated_crc);
    if (!crc_ok) {
        return parse_failure(ErrorCode::BadLength, 0U, true, sequence, type_code);
    }
    if (received_crc != calculated_crc) {
        return parse_failure(
            ErrorCode::BadCrc,
            received_crc,
            true,
            sequence,
            type_code
        );
    }

    message_.type = static_cast<MessageType>(type_code);
    message_.sequence = sequence;
    message_.payload_length = payload_length;
    message_.decoded_crc = received_crc;
    message_.payload = decoded_ + kHeaderSize;
    ParseEvent event = no_parse_event();
    event.kind = ParseKind::MessageReady;
    event.context_valid = true;
    event.sequence = sequence;
    event.related_type = type_code;
    return event;
}

const MessageView& CommandParser::message() const {
    return message_;
}

}  // namespace sx1278
