#ifndef SX1278_COMMAND_PARSER_H
#define SX1278_COMMAND_PARSER_H

#include <stddef.h>
#include <stdint.h>

#include "protocol_types.h"

namespace sx1278 {

enum class ParseKind : uint8_t {
    None = 0U,
    MessageReady = 1U,
    Error = 2U
};

struct ParseEvent {
    ParseKind kind;
    ErrorCode error;
    uint16_t detail;
    bool context_valid;
    uint16_t sequence;
    uint8_t related_type;
};

class CommandParser {
public:
    /** Initialize an empty streaming command parser.
     *
     */
    CommandParser();

    /** Consume one UART byte and return at most one parser event.
     *
     *
     * Processing flow:
     *   byte/time -> discard or timeout -> append or delimiter -> message/error
     */
    ParseEvent push(uint8_t byte, uint32_t now_ms);

    /** Report and discard one partial fragment stale for at least 250 ms.
     *
     * References:
     * - conformance/serial_protocol_v1.json, limits.inter_byte_timeout_ms and
     *   error_codes.serial_overflow.
     *
     * Processing flow:
     *   current time -> partial-fragment age -> keep or enter discard mode
     */
    ParseEvent poll_timeout(uint32_t now_ms);

    /** Return the last message view until the next non-delimiter byte arrives.
     *
     */
    const MessageView& message() const;

private:
    ParseEvent finish_fragment();
    void clear_fragment();

    uint8_t encoded_[kMaxCobsFragment];
    uint8_t decoded_[kMaxDecoded];
    size_t encoded_size_;
    uint32_t last_byte_ms_;
    bool have_time_;
    bool discarding_;
    MessageView message_;
};

}  // namespace sx1278

#endif
