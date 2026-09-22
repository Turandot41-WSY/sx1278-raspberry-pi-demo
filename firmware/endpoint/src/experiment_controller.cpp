#include "experiment_controller.h"

#include "wire_payloads.h"

namespace sx1278 {

ExperimentController::ExperimentController(
    ProfileControl& profiles,
    RadioTxStateMachine& tx,
    RadioRxStateMachine& rx,
    EventPort& events,
    EndpointIdentity& identity
) : profiles_(profiles),
    tx_(tx),
    rx_(rx),
    events_(events),
    identity_(identity) {
    cache_ = ReplayCache();
    key_ = no_context_key();
    have_key_ = false;
    direction_ = AttemptDirection::None;
    state_ = AttemptState::Standby;
    error_ = ErrorCode::None;
    tx_sequence_ = 0U;
    rx_sequence_ = 0U;
    for (uint8_t index = 0U; index < kMaxPayload; ++index) {
        scratch_[index] = 0U;
    }
}

/** Identify commands whose responses participate in duplicate suppression.
 *
 * The input message type returns true for commands that reset, configure, load,
 * arm, start or cancel endpoint state, and false for the remaining types.
 *
 * Processing flow:
 *     Command type -> state-changing command cases -> duplicate-cache eligibility
 */
bool ExperimentController::is_stateful(MessageType type) const {
    switch (type) {
        case MessageType::ResetToStandby:
        case MessageType::ApplyProfile:
        case MessageType::SetPa:
        case MessageType::LoadTx:
        case MessageType::ArmRx:
        case MessageType::StartTx:
        case MessageType::CancelAttempt:
            return true;
        default:
            return false;
    }
}

/** Report whether the controller still owns a loaded or active RF attempt.
 *
 * The result is true for TxLoaded, TxStarted or RxArmed and is used to reject
 * configuration changes and replacement attempts while those states persist.
 *
 * Processing flow:
 *     Controller state -> loaded TX / active TX / armed RX checks -> busy result
 */
bool ExperimentController::attempt_in_progress() const {
    if (state_ == AttemptState::TxLoaded) {
        return true;
    }
    if (state_ == AttemptState::TxStarted) {
        return true;
    }
    if (state_ == AttemptState::RxArmed) {
        return true;
    }
    return false;
}

/** Report whether either radio machine retains an undelivered terminal event.
 *
 * A true result prevents a new configuration or attempt from replacing evidence
 * that the controller has not yet sent successfully.
 *
 * Processing flow:
 *     Pending TX terminal -> immediate busy result / pending RX terminal check
 */
bool ExperimentController::output_pending() const {
    if (tx_.has_terminal()) {
        return true;
    }
    return rx_.has_terminal();
}

/** Return the generated placeholder pair for an unavailable RF attempt.
 *
 * The returned RunToken and AttemptIndex identify missing context in endpoint
 * errors; they do not allocate an experiment attempt.
 */
AttemptKey ExperimentController::no_context_key() const {
    AttemptKey key = {};
    key.run_token = generated::kNoAttemptRunToken;
    key.attempt_index = generated::kNoAttemptIndex;
    return key;
}

/** Select the current attempt key or the generated unavailable-context pair.
 *
 * The returned value supplies context for an endpoint error without creating a
 * new attempt.
 *
 * Processing flow:
 *     Existing attempt flag -> remembered key / unavailable-context key
 */
AttemptKey ExperimentController::error_key() const {
    if (have_key_) {
        return key_;
    }
    return no_context_key();
}

/** Remember a bounded response and the command identity that may replay it.
 *
 * The message supplies sequence, type and decoded CRC; payload_size bytes are
 * copied from payload into owned storage. False rejects an invalid span before
 * changing the cache. True confirms storage and does not imply UART delivery.
 *
 * Processing flow:
 *     Payload size and pointer -> command identity -> response metadata -> copy
 *     payload bytes -> publish reusable response
 */
bool ExperimentController::cache_response(
    const MessageView& message,
    MessageType response,
    const uint8_t* payload,
    size_t payload_size
) {
    if (payload_size > kMaxPayload) {
        return false;
    }
    if (payload_size > 0U) {
        if (payload == 0) {
            return false;
        }
    }
    cache_.valid = true;
    cache_.sequence = message.sequence;
    cache_.crc = message.decoded_crc;
    cache_.command = message.type;
    cache_.response = response;
    cache_.payload_size = static_cast<uint16_t>(payload_size);
    for (size_t index = 0U; index < payload_size; ++index) {
        uint8_t value = payload[index];
        cache_.payload[index] = value;
    }
    return true;
}

/** Release the terminal event represented by a successfully sent cached reply.
 *
 * The cached command selects the TX or RX machine. Only an existing terminal
 * for START_TX or ARM_RX is consumed; unrelated cached commands consume neither.
 *
 * Processing flow:
 *     Cached command -> matching radio machine -> pending terminal -> consume
 */
void ExperimentController::consume_cached_terminal() {
    if (cache_.command == MessageType::StartTx) {
        if (tx_.has_terminal()) {
            tx_.consume_terminal();
        }
    }
    if (cache_.command == MessageType::ArmRx) {
        if (rx_.has_terminal()) {
            rx_.consume_terminal();
        }
    }
}

/** Send the remembered response and consume its terminal only after delivery.
 *
 * The return value reports whether EventPort accepted the complete response.
 * A missing cache or failed send returns false, preserving any pending terminal
 * for a later delivery attempt.
 *
 * Processing flow:
 *     Cache validity -> encoded event send -> successful delivery -> terminal
 *     consumption
 */
bool ExperimentController::send_cached() {
    if (!cache_.valid) {
        return false;
    }
    bool sent = events_.send(
        cache_.response,
        cache_.sequence,
        cache_.payload,
        cache_.payload_size
    );
    if (sent) {
        consume_cached_terminal();
    }
    return sent;
}

/** Resolve reuse of the cached sequence before a stateful command executes.
 *
 * The handled output is true when a matching sequence was replayed or rejected
 * for conflicting type or CRC. A true return with handled false allows normal
 * command dispatch; false reports rejection or a failed response send.
 *
 * Processing flow:
 *     Handled output -> cache and sequence match -> type/CRC conflict error or
 *     cached reply -> dispatch disposition
 */
bool ExperimentController::replay_or_conflict(
    const MessageView& message,
    bool* handled
) {
    if (handled == 0) {
        return false;
    }
    *handled = false;
    if (!cache_.valid) {
        return true;
    }
    if (message.sequence != cache_.sequence) {
        return true;
    }
    *handled = true;
    if (message.type != cache_.command) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            false
        );
    }
    if (message.decoded_crc != cache_.crc) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            false
        );
    }
    return send_cached();
}

/** Record an error and attempt to send its command response with optional caching.
 *
 * The message supplies sequence and related type; key, error and detail supply
 * the error payload. The cache flag controls duplicate-response storage. This
 * method always returns false to report command rejection, even if delivery
 * succeeds.
 *
 * Processing flow:
 *     Store error state -> encode contextual error -> optional cache -> send
 *     response -> report rejected command
 */
bool ExperimentController::send_command_error(
    const MessageView& message,
    const AttemptKey& key,
    ErrorCode error,
    uint16_t detail,
    bool cache
) {
    error_ = error;
    size_t payload_size = 0U;
    uint8_t related_type = static_cast<uint8_t>(message.type);
    bool encoded = encode_error(
        key,
        related_type,
        error,
        detail,
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    if (cache) {
        bool cached = cache_response(
            message,
            MessageType::EndpointError,
            scratch_,
            payload_size
        );
        if (!cached) {
            return false;
        }
        send_cached();
        return false;
    }
    uint16_t wire_size = static_cast<uint16_t>(payload_size);
    events_.send(
        MessageType::EndpointError,
        message.sequence,
        scratch_,
        wire_size
    );
    return false;
}

/** Respond to an empty HELLO with endpoint identity and current state.
 *
 * The input message supplies the response sequence. The reply includes boot,
 * firmware, board and profile-table identity. The result reports complete reply
 * delivery; invalid input produces an error response and returns false.
 *
 * Processing flow:
 *     Empty payload check -> profile-table hash -> encode HELLO_REPORT from
 *     identity and state -> send with the requesting sequence
 */
bool ExperimentController::handle_hello(const MessageView& message) {
    if (!parse_empty_payload(message)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::BadLength,
            message.payload_length,
            false
        );
    }
    uint8_t table_hash[32] = {0U};
    profiles_.copy_table_hash(table_hash);
    size_t payload_size = 0U;
    bool encoded = encode_hello_report(
        identity_.endpoint_id,
        identity_.boot_count,
        identity_.reg_version,
        state_,
        identity_.firmware_hash,
        table_hash,
        identity_.board_hash,
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    uint16_t wire_size = static_cast<uint16_t>(payload_size);
    return events_.send(
        MessageType::HelloReport,
        message.sequence,
        scratch_,
        wire_size
    );
}

/** Cancel both radio machines and acknowledge a cleared attempt context.
 *
 * The input must have an empty payload. Successful cleanup publishes Standby and
 * caches its ACK. Cleanup failure sets Error and sends a cached error response;
 * the result is true only when the ACK was delivered.
 *
 * Processing flow:
 *     Empty payload -> cancel TX and RX -> verify cleanup -> clear attempt and
 *     error state -> encode and cache ACK -> send
 */
bool ExperimentController::handle_reset(const MessageView& message) {
    if (!parse_empty_payload(message)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::BadLength,
            message.payload_length,
            true
        );
    }
    bool tx_clean = tx_.cancel();
    bool rx_clean = rx_.cancel();
    if (!tx_clean) {
        state_ = AttemptState::Error;
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::RegisterReadback,
            0U,
            true
        );
    }
    if (!rx_clean) {
        state_ = AttemptState::Error;
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::RegisterReadback,
            0U,
            true
        );
    }
    key_ = no_context_key();
    have_key_ = false;
    direction_ = AttemptDirection::None;
    state_ = AttemptState::Standby;
    error_ = ErrorCode::None;
    size_t payload_size = 0U;
    uint8_t related_type = static_cast<uint8_t>(message.type);
    if (!encode_ack(related_type, scratch_, sizeof(scratch_), &payload_size)) {
        return false;
    }
    if (!cache_response(message, MessageType::Ack, scratch_, payload_size)) {
        return false;
    }
    return send_cached();
}

/** Apply the requested profile only after idle-state and table-identity checks.
 *
 * The command supplies a profile code and expected table hash. A mismatch
 * invalidates configuration. Successful application returns the register values
 * in a cached CONFIG_REPORT; the result reports delivery of that response.
 *
 * Processing flow:
 *     Active attempt and pending event gates -> parse profile -> compare all hash
 *     bytes -> apply profile -> encode register report -> cache and send
 */
bool ExperimentController::handle_apply_profile(const MessageView& message) {
    if (attempt_in_progress()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (output_pending()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    ApplyProfileCommand command = {};
    if (!parse_apply_profile(message, &command)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::Profile,
            message.payload_length,
            true
        );
    }
    uint8_t expected_hash[32] = {0U};
    profiles_.copy_table_hash(expected_hash);
    for (uint8_t index = 0U; index < 32U; ++index) {
        uint8_t requested_byte = command.table_hash[index];
        uint8_t expected_byte = expected_hash[index];
        if (requested_byte != expected_byte) {
            profiles_.invalidate_configuration();
            AttemptKey key = error_key();
            return send_command_error(
                message,
                key,
                ErrorCode::Profile,
                command.profile_code,
                true
            );
        }
    }
    if (!profiles_.apply_profile(command.profile_code)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            profiles_.last_error(),
            command.profile_code,
            true
        );
    }
    size_t payload_size = 0U;
    uint8_t related_type = static_cast<uint8_t>(message.type);
    bool encoded = encode_config_report(
        related_type,
        profiles_.active_profile(),
        profiles_.pa_command_dbm(),
        profiles_.reg_pa_config(),
        profiles_.reg_pa_dac(),
        profiles_.reg_ocp(),
        profiles_.readback_pairs(),
        profiles_.readback_count(),
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    if (!cache_response(
        message,
        MessageType::ConfigReport,
        scratch_,
        payload_size
    )) {
        return false;
    }
    return send_cached();
}

/** Apply a requested PA setting when a profile exists and no attempt is active.
 *
 * The message carries the PA command and RegOcp value. A successful cached
 * CONFIG_REPORT includes the three PA-related register readbacks. The return
 * value reports complete delivery, and rejected commands return false.
 *
 * Processing flow:
 *     Active attempt and pending event gates -> configured profile -> PA payload
 *     -> apply PA -> gather register readbacks -> encode, cache and send report
 */
bool ExperimentController::handle_set_pa(const MessageView& message) {
    if (attempt_in_progress()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (output_pending()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (!profiles_.profile_configured()) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::Profile,
            0U,
            true
        );
    }
    SetPaCommand command = {};
    if (!parse_set_pa(message, &command)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::Pa,
            message.payload_length,
            true
        );
    }
    if (!profiles_.apply_pa(command.command_dbm, command.reg_ocp)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            profiles_.last_error(),
            0U,
            true
        );
    }
    uint8_t pairs[6] = {
        0x09U,
        profiles_.reg_pa_config(),
        0x4DU,
        profiles_.reg_pa_dac(),
        0x0BU,
        profiles_.reg_ocp()
    };
    size_t payload_size = 0U;
    uint8_t related_type = static_cast<uint8_t>(message.type);
    bool encoded = encode_config_report(
        related_type,
        profiles_.active_profile(),
        profiles_.pa_command_dbm(),
        profiles_.reg_pa_config(),
        profiles_.reg_pa_dac(),
        profiles_.reg_ocp(),
        pairs,
        3U,
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    if (!cache_response(
        message,
        MessageType::ConfigReport,
        scratch_,
        payload_size
    )) {
        return false;
    }
    return send_cached();
}

/** Load one parsed frame and frequency word into the transmitter for later start.
 *
 * The message carries the attempt key, FRF word and 64 frame bytes. Profile and
 * PA configuration are required. Success enters TxLoaded and sends cached
 * TX_READY with the FRF readback; this method does not start the RF attempt.
 *
 * Processing flow:
 *     Parse frame -> idle and pending-event gates -> bind TX attempt key ->
 *     profile and PA gates -> load radio -> enter TxLoaded -> cache and send ready
 */
bool ExperimentController::handle_load_tx(const MessageView& message) {
    LoadTxCommand command = {};
    if (!parse_load_tx(message, &command)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::FrameLength,
            message.payload_length,
            true
        );
    }
    if (attempt_in_progress()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (output_pending()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    key_ = command.key;
    have_key_ = true;
    direction_ = AttemptDirection::Tx;
    if (!profiles_.profile_configured()) {
        return send_command_error(
            message,
            key_,
            ErrorCode::Profile,
            0U,
            true
        );
    }
    if (!profiles_.pa_configured()) {
        return send_command_error(
            message,
            key_,
            ErrorCode::Pa,
            0U,
            true
        );
    }
    if (!tx_.load(command.key, command.reg_frf_word, command.frame)) {
        state_ = AttemptState::Error;
        error_ = tx_.error();
        return send_command_error(message, key_, error_, 0U, true);
    }
    state_ = AttemptState::TxLoaded;
    error_ = ErrorCode::None;
    size_t payload_size = 0U;
    bool encoded = encode_tx_ready(
        key_,
        tx_.frf_readback(),
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    if (!cache_response(
        message,
        MessageType::TxReady,
        scratch_,
        payload_size
    )) {
        return false;
    }
    return send_cached();
}

/** Arm reception for the requested attempt and remember its response sequence.
 *
 * The message supplies the attempt key and receive window; now_ms starts the
 * radio machine's timing. Success enters RxArmed and sends cached RX_ARMED with
 * FRF and window readback. False reports a rejected command or failed delivery.
 *
 * Processing flow:
 *     Parse receive window -> idle and pending-event gates -> bind RX attempt ->
 *     profile and PA gates -> arm radio -> record state and sequence -> ready reply
 */
bool ExperimentController::handle_arm_rx(
    const MessageView& message,
    uint32_t now_ms
) {
    ArmRxCommand command = {};
    if (!parse_arm_rx(message, &command)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::BadLength,
            message.payload_length,
            true
        );
    }
    if (attempt_in_progress()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (output_pending()) {
        AttemptKey key = error_key();
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    key_ = command.key;
    have_key_ = true;
    direction_ = AttemptDirection::Rx;
    if (!profiles_.profile_configured()) {
        return send_command_error(
            message,
            key_,
            ErrorCode::Profile,
            0U,
            true
        );
    }
    if (!profiles_.pa_configured()) {
        return send_command_error(
            message,
            key_,
            ErrorCode::Pa,
            0U,
            true
        );
    }
    if (!rx_.arm(command.key, now_ms, command.window_ms)) {
        state_ = AttemptState::Error;
        error_ = rx_.error();
        return send_command_error(message, key_, error_, 0U, true);
    }
    state_ = AttemptState::RxArmed;
    error_ = ErrorCode::None;
    rx_sequence_ = message.sequence;
    size_t payload_size = 0U;
    bool encoded = encode_rx_armed(
        key_,
        rx_.frf_readback(),
        rx_.window_ms(),
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    if (!cache_response(
        message,
        MessageType::RxArmed,
        scratch_,
        payload_size
    )) {
        return false;
    }
    return send_cached();
}

/** Start the loaded TX attempt once its key, direction and state match.
 *
 * The message identifies the prepared attempt; now_ms starts the TX watchdog.
 * Success stores the triggering sequence and sends cached TX_STARTED. Command
 * replay is resolved by the dispatcher before this handler can start RF again.
 *
 * Processing flow:
 *     Parse key -> current-key equality -> TX direction and TxLoaded state ->
 *     radio start -> record TxStarted and sequence -> cache and send response
 */
bool ExperimentController::handle_start_tx(
    const MessageView& message,
    uint32_t now_ms
) {
    AttemptKey command_key = {};
    if (!parse_attempt_key(message, &command_key)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            true
        );
    }
    if (!have_key_) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            true
        );
    }
    if (!same_attempt(command_key, key_)) {
        return send_command_error(
            message,
            key_,
            ErrorCode::ContextMismatch,
            0U,
            true
        );
    }
    if (direction_ != AttemptDirection::Tx) {
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key_,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (state_ != AttemptState::TxLoaded) {
        uint16_t detail = static_cast<uint16_t>(state_);
        return send_command_error(
            message,
            key_,
            ErrorCode::BadState,
            detail,
            true
        );
    }
    if (!tx_.start(now_ms)) {
        state_ = AttemptState::Error;
        error_ = tx_.error();
        uint16_t detail = tx_.start_failure_detail();
        return send_command_error(message, key_, error_, detail, true);
    }
    state_ = AttemptState::TxStarted;
    error_ = ErrorCode::None;
    tx_sequence_ = message.sequence;
    size_t payload_size = 0U;
    if (!encode_attempt(
        key_,
        scratch_,
        sizeof(scratch_),
        &payload_size
    )) {
        return false;
    }
    if (!cache_response(
        message,
        MessageType::TxStarted,
        scratch_,
        payload_size
    )) {
        return false;
    }
    return send_cached();
}

/** Cancel the matching attempt and acknowledge radio cleanup in Standby.
 *
 * The command key must match the retained context. Cleanup targets its TX or RX
 * direction. Successful cancellation retains the key for status queries while
 * clearing direction and error; the result reports ACK delivery.
 *
 * Processing flow:
 *     Parse and match key -> cancel selected radio machine -> cleanup result ->
 *     Standby state -> encode, cache and send ACK
 */
bool ExperimentController::handle_cancel(const MessageView& message) {
    AttemptKey command_key = {};
    if (!parse_attempt_key(message, &command_key)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            true
        );
    }
    if (!have_key_) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            true
        );
    }
    if (!same_attempt(command_key, key_)) {
        return send_command_error(
            message,
            key_,
            ErrorCode::ContextMismatch,
            0U,
            true
        );
    }
    bool cleaned = true;
    if (direction_ == AttemptDirection::Tx) {
        cleaned = tx_.cancel();
    }
    if (direction_ == AttemptDirection::Rx) {
        cleaned = rx_.cancel();
    }
    if (!cleaned) {
        state_ = AttemptState::Error;
        error_ = ErrorCode::RegisterReadback;
        return send_command_error(message, key_, error_, 0U, true);
    }
    direction_ = AttemptDirection::None;
    state_ = AttemptState::Standby;
    error_ = ErrorCode::None;
    size_t payload_size = 0U;
    uint8_t related_type = static_cast<uint8_t>(message.type);
    if (!encode_ack(related_type, scratch_, sizeof(scratch_), &payload_size)) {
        return false;
    }
    if (!cache_response(message, MessageType::Ack, scratch_, payload_size)) {
        return false;
    }
    return send_cached();
}

/** Report the remembered state and error for one matching attempt key.
 *
 * The input key must match the retained attempt. The returned status uses the
 * query sequence and leaves the duplicate-response cache intact. The Boolean
 * result reports delivery of ATTEMPT_STATUS, with false for rejection or failure.
 *
 * Processing flow:
 *     Parse query key -> retained key and equality -> encode state/error report
 *     -> send response with query sequence
 */
bool ExperimentController::handle_status(const MessageView& message) {
    AttemptKey command_key = {};
    if (!parse_attempt_key(message, &command_key)) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            false
        );
    }
    if (!have_key_) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::ContextMismatch,
            0U,
            false
        );
    }
    if (!same_attempt(command_key, key_)) {
        return send_command_error(
            message,
            key_,
            ErrorCode::ContextMismatch,
            0U,
            false
        );
    }
    size_t payload_size = 0U;
    bool encoded = encode_attempt_status(
        key_,
        state_,
        error_,
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    uint16_t wire_size = static_cast<uint16_t>(payload_size);
    return events_.send(
        MessageType::AttemptStatus,
        message.sequence,
        scratch_,
        wire_size
    );
}

bool ExperimentController::handle(
    const MessageView& message,
    uint32_t now_ms
) {
    if (message.type == MessageType::Hello) {
        return handle_hello(message);
    }
    if (!identity_.radio_ready) {
        AttemptKey key = error_key();
        return send_command_error(
            message,
            key,
            ErrorCode::RegisterReadback,
            0x0042U,
            false
        );
    }
    if (is_stateful(message.type)) {
        bool handled = false;
        bool can_continue = replay_or_conflict(message, &handled);
        if (handled) {
            return can_continue;
        }
        if (!can_continue) {
            return false;
        }
    }
    if (state_ == AttemptState::Error) {
        bool recovery_command = false;
        if (message.type == MessageType::ResetToStandby) {
            recovery_command = true;
        }
        if (message.type == MessageType::GetAttemptStatus) {
            recovery_command = true;
        }
        if (!recovery_command) {
            ErrorCode locked_error = error_;
            if (locked_error == ErrorCode::None) {
                locked_error = ErrorCode::BadState;
            }
            AttemptKey key = error_key();
            uint16_t detail = static_cast<uint16_t>(state_);
            return send_command_error(
                message,
                key,
                locked_error,
                detail,
                is_stateful(message.type)
            );
        }
    }

    switch (message.type) {
        case MessageType::ResetToStandby:
            return handle_reset(message);
        case MessageType::ApplyProfile:
            return handle_apply_profile(message);
        case MessageType::SetPa:
            return handle_set_pa(message);
        case MessageType::LoadTx:
            return handle_load_tx(message);
        case MessageType::ArmRx:
            return handle_arm_rx(message, now_ms);
        case MessageType::StartTx:
            return handle_start_tx(message, now_ms);
        case MessageType::CancelAttempt:
            return handle_cancel(message);
        case MessageType::GetAttemptStatus:
            return handle_status(message);
        default:
            break;
    }
    AttemptKey key = error_key();
    uint16_t detail = static_cast<uint16_t>(message.type);
    return send_command_error(
        message,
        key,
        ErrorCode::UnknownType,
        detail,
        false
    );
}

/** Advance TX timing and deliver a terminal report tied to the start command.
 *
 * The input now_ms drives the radio machine. A pending terminal updates controller
 * state and error, then replaces the cached START_TX reply with TX_DONE or
 * ENDPOINT_ERROR. Failed delivery retains the terminal for another tick.
 *
 * Processing flow:
 *     TX machine tick -> pending terminal -> state/error snapshot -> done or
 *     error payload -> original sequence and CRC -> cache and send
 */
void ExperimentController::tick_tx(uint32_t now_ms) {
    tx_.tick(now_ms);
    if (!tx_.has_terminal()) {
        return;
    }
    state_ = tx_.terminal();
    error_ = tx_.error();
    size_t payload_size = 0U;
    MessageType response = MessageType::EndpointError;
    bool encoded = false;
    if (state_ == AttemptState::TxDone) {
        encoded = encode_attempt(
            key_,
            scratch_,
            sizeof(scratch_),
            &payload_size
        );
        response = MessageType::TxDone;
    } else {
        uint8_t related_type = static_cast<uint8_t>(MessageType::StartTx);
        encoded = encode_error(
            key_,
            related_type,
            error_,
            0U,
            scratch_,
            sizeof(scratch_),
            &payload_size
        );
    }
    if (!encoded) {
        return;
    }
    MessageView command = {};
    command.type = MessageType::StartTx;
    command.sequence = tx_sequence_;
    command.decoded_crc = cache_.crc;
    if (!cache_response(command, response, scratch_, payload_size)) {
        return;
    }
    send_cached();
}

/** Advance reception and deliver its packet, timeout or endpoint error report.
 *
 * The input now_ms drives the receive window. A pending terminal supplies state,
 * error and any received bytes with their metric-validity flags. The report uses
 * the ARM_RX sequence; a failed send preserves the terminal for a later tick.
 *
 * Processing flow:
 *     RX machine tick -> pending terminal -> packet / timeout / error payload ->
 *     original ARM_RX identity -> cache response -> send and consume on success
 */
void ExperimentController::tick_rx(uint32_t now_ms) {
    rx_.tick(now_ms);
    if (!rx_.has_terminal()) {
        return;
    }
    state_ = rx_.terminal();
    error_ = rx_.error();
    size_t payload_size = 0U;
    MessageType response = MessageType::EndpointError;
    bool encoded = false;
    if (state_ == AttemptState::RxPacket) {
        const IrqSnapshot& irq = rx_.irq();
        encoded = encode_rx_packet(
            key_,
            irq.phy_crc_ok,
            irq.received_length,
            irq.metrics_flags,
            irq.rssi_raw,
            irq.snr_raw,
            rx_.payload(),
            scratch_,
            sizeof(scratch_),
            &payload_size
        );
        response = MessageType::RxPacket;
    } else if (state_ == AttemptState::RxTimeout) {
        encoded = encode_attempt(
            key_,
            scratch_,
            sizeof(scratch_),
            &payload_size
        );
        response = MessageType::RxTimeout;
    } else {
        uint8_t related_type = static_cast<uint8_t>(MessageType::ArmRx);
        encoded = encode_error(
            key_,
            related_type,
            error_,
            0U,
            scratch_,
            sizeof(scratch_),
            &payload_size
        );
    }
    if (!encoded) {
        return;
    }
    MessageView command = {};
    command.type = MessageType::ArmRx;
    command.sequence = rx_sequence_;
    command.decoded_crc = cache_.crc;
    if (!cache_response(command, response, scratch_, payload_size)) {
        return;
    }
    send_cached();
}

void ExperimentController::tick(uint32_t now_ms) {
    if (direction_ == AttemptDirection::Tx) {
        tick_tx(now_ms);
        return;
    }
    if (direction_ == AttemptDirection::Rx) {
        tick_rx(now_ms);
    }
}

bool ExperimentController::report_parse_error(const ParseEvent& event) {
    if (event.kind != ParseKind::Error) {
        return false;
    }
    uint16_t sequence = generated::kUnavailableMsgSeqPlaceholder;
    uint8_t related_type = generated::kUnavailableRelatedTypePlaceholder;
    if (event.context_valid) {
        sequence = event.sequence;
        related_type = event.related_type;
    }
    AttemptKey key = error_key();
    size_t payload_size = 0U;
    bool encoded = encode_error(
        key,
        related_type,
        event.error,
        event.detail,
        scratch_,
        sizeof(scratch_),
        &payload_size
    );
    if (!encoded) {
        return false;
    }
    uint16_t wire_size = static_cast<uint16_t>(payload_size);
    return events_.send(
        MessageType::EndpointError,
        sequence,
        scratch_,
        wire_size
    );
}

AttemptState ExperimentController::state() const {
    return state_;
}

}  // namespace sx1278
