#ifndef SX1278_EXPERIMENT_CONTROLLER_H
#define SX1278_EXPERIMENT_CONTROLLER_H

#include <stddef.h>
#include <stdint.h>

#include "command_parser.h"
#include "event_reporter.h"
#include "profile_control.h"
#include "radio_rx_state_machine.h"
#include "radio_tx_state_machine.h"

namespace sx1278 {

struct EndpointIdentity {
    uint32_t endpoint_id;
    uint32_t boot_count;
    uint8_t reg_version;
    bool radio_ready;
    const uint8_t* firmware_hash;
    const uint8_t* board_hash;
};

struct ReplayCache {
    bool valid;
    uint16_t sequence;
    uint16_t crc;
    MessageType command;
    MessageType response;
    uint16_t payload_size;
    uint8_t payload[kMaxPayload];
};

enum class AttemptDirection : uint8_t {
    None = 0U,
    Tx = 1U,
    Rx = 2U
};

class ExperimentController {
public:
    /** Bind run configuration, radio machines, event output, and identity.
     *
     */
    ExperimentController(
        ProfileControl& profiles,
        RadioTxStateMachine& tx,
        RadioRxStateMachine& rx,
        EventPort& events,
        EndpointIdentity& identity
    );

    /** Execute or replay one validated host command without duplicate hardware work.
     *
     *
     * Processing flow:
     *   command -> radio-health/replay gates -> typed branch -> cached response
     */
    bool handle(const MessageView& message, uint32_t now_ms);

    /** Advance the active radio machine and emit at most one terminal event.
     *
     *
     * Processing flow:
     *   active direction -> machine tick -> terminal encoding/cache -> event delivery
     */
    void tick(uint32_t now_ms);

    /** Convert one structured parser failure into a contextual endpoint error.
     *
     * References:
     * - conformance/serial_protocol_v1.json, error_context and context objects.
     *
     * Processing flow:
     *   parser context -> current/no attempt key -> error payload -> event
     */
    bool report_parse_error(const ParseEvent& event);

    /** Return the latest logical attempt state retained for status queries. */
    AttemptState state() const;

private:
    bool is_stateful(MessageType type) const;
    bool attempt_in_progress() const;
    bool output_pending() const;
    AttemptKey no_context_key() const;
    AttemptKey error_key() const;
    bool replay_or_conflict(const MessageView& message, bool* handled);
    bool cache_response(
        const MessageView& message,
        MessageType response,
        const uint8_t* payload,
        size_t payload_size
    );
    bool send_cached();
    void consume_cached_terminal();
    bool send_command_error(
        const MessageView& message,
        const AttemptKey& key,
        ErrorCode error,
        uint16_t detail,
        bool cache
    );
    bool handle_hello(const MessageView& message);
    bool handle_reset(const MessageView& message);
    bool handle_apply_profile(const MessageView& message);
    bool handle_set_pa(const MessageView& message);
    bool handle_load_tx(const MessageView& message);
    bool handle_arm_rx(const MessageView& message, uint32_t now_ms);
    bool handle_start_tx(const MessageView& message, uint32_t now_ms);
    bool handle_cancel(const MessageView& message);
    bool handle_status(const MessageView& message);
    void tick_tx(uint32_t now_ms);
    void tick_rx(uint32_t now_ms);

    ProfileControl& profiles_;
    RadioTxStateMachine& tx_;
    RadioRxStateMachine& rx_;
    EventPort& events_;
    EndpointIdentity& identity_;
    ReplayCache cache_;
    AttemptKey key_;
    bool have_key_;
    AttemptDirection direction_;
    AttemptState state_;
    ErrorCode error_;
    uint16_t tx_sequence_;
    uint16_t rx_sequence_;
    uint8_t scratch_[kMaxPayload];
};

}  // namespace sx1278

#endif
