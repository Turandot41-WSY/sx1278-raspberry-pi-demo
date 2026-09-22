#ifndef SX1278_EVENT_REPORTER_H
#define SX1278_EVENT_REPORTER_H

#include <stddef.h>
#include <stdint.h>

#include "protocol_types.h"

namespace sx1278 {

class ByteSink {
public:
    /** Destroy a byte sink through its interface safely.
     *
     */
    virtual ~ByteSink() {}

    /** Write one complete wire message without text framing.
     *
     */
    virtual bool write_bytes(const uint8_t* bytes, size_t size) = 0;
};

class EventPort {
public:
    /** Release one event output through its interface safely. */
    virtual ~EventPort() {}

    /** Send one already encoded protocol payload as an endpoint event. */
    virtual bool send(
        MessageType type,
        uint16_t sequence,
        const uint8_t* payload,
        uint16_t payload_size
    ) = 0;
};

class EventReporter : public EventPort {
public:
    /** Bind one reporter to a caller-owned binary byte sink.
     *
     */
    explicit EventReporter(ByteSink& sink);

    /** Frame and send one validated endpoint event payload.
     *
     *
     * Processing flow:
     *   event fields -> decoded envelope -> CRC -> COBS + delimiter -> sink
     */
    bool send(
        MessageType type,
        uint16_t sequence,
        const uint8_t* payload,
        uint16_t payload_size
    ) override;

private:
    ByteSink& sink_;
    uint8_t decoded_[kMaxDecoded];
    uint8_t wire_[kMaxWire];
};

}  // namespace sx1278

#endif
