#include "radio_tx_state_machine.h"

namespace sx1278 {

static const uint32_t kTxWatchdogMs = 5000UL;

RadioTxStateMachine::RadioTxStateMachine(RadioDevice& radio) : radio_(radio) {
    key_.run_token = 0UL;
    key_.attempt_index = 0UL;
    state_ = AttemptState::Standby;
    error_ = ErrorCode::None;
    started_ms_ = 0UL;
    frf_readback_ = 0UL;
    terminal_pending_ = false;
    cleanup_ok_ = true;
}

/** Check whether a new TX frame can replace the current radio state.
 *
 * The result requires successful cleanup, no pending terminal, and neither a
 * loaded frame nor a started transmission.
 *
 * Processing flow:
 *     Cleanup gate -> pending terminal gate -> TxLoaded / TxStarted gates ->
 *     permission to load
 */
bool RadioTxStateMachine::can_load() const {
    if (!cleanup_ok_) {
        return false;
    }
    if (terminal_pending_) {
        return false;
    }
    if (state_ == AttemptState::TxLoaded) {
        return false;
    }
    if (state_ == AttemptState::TxStarted) {
        return false;
    }
    return true;
}

/** Record a TX-command failure after attempting to clean up the radio.
 *
 * The input error describes load or start failure. Failed cleanup replaces it
 * with RegisterReadback. The command handler reports the rejection directly,
 * so this path clears the asynchronous terminal flag.
 *
 * Processing flow:
 *     Radio cleanup -> Error state and supplied error -> clear terminal flag ->
 *     override error if cleanup failed
 */
void RadioTxStateMachine::fail_immediately(ErrorCode error) {
    bool cleaned = radio_.finish_terminal();
    cleanup_ok_ = cleaned;
    state_ = AttemptState::Error;
    error_ = error;
    terminal_pending_ = false;
    if (!cleaned) {
        error_ = ErrorCode::RegisterReadback;
    }
}

/** Queue a TX terminal after cleanup and retain a failed cleanup as an error.
 *
 * The requested terminal and error are stored when cleanup succeeds. Otherwise
 * the queued result becomes Error with RegisterReadback. It remains pending
 * until the controller confirms terminal delivery.
 *
 * Processing flow:
 *     Radio cleanup -> requested terminal state/error -> mark pending -> replace
 *     outcome when cleanup failed
 */
void RadioTxStateMachine::finish_as_terminal(
    AttemptState terminal,
    ErrorCode error
) {
    bool cleaned = radio_.finish_terminal();
    cleanup_ok_ = cleaned;
    state_ = terminal;
    error_ = error;
    terminal_pending_ = true;
    if (!cleaned) {
        state_ = AttemptState::Error;
        error_ = ErrorCode::RegisterReadback;
    }
}

bool RadioTxStateMachine::load(
    const AttemptKey& key,
    uint32_t frf_word,
    const uint8_t frame[64]
) {
    if (!can_load()) {
        error_ = ErrorCode::BadState;
        return false;
    }
    if (!is_valid_attempt_key(key)) {
        error_ = ErrorCode::BadState;
        return false;
    }
    if (frf_word > 0x00FFFFFFUL) {
        error_ = ErrorCode::FrfReadback;
        return false;
    }
    if (frame == 0) {
        error_ = ErrorCode::FrameLength;
        return false;
    }

    key_ = key;
    error_ = ErrorCode::None;
    uint32_t readback = 0UL;
    bool prepared = radio_.prepare_tx(frf_word, frame, &readback);
    frf_readback_ = readback;
    if (!prepared) {
        fail_immediately(ErrorCode::RegisterReadback);
        return false;
    }
    if (readback != frf_word) {
        fail_immediately(ErrorCode::FrfReadback);
        return false;
    }
    state_ = AttemptState::TxLoaded;
    cleanup_ok_ = true;
    return true;
}

bool RadioTxStateMachine::start(uint32_t now_ms) {
    if (state_ != AttemptState::TxLoaded) {
        error_ = ErrorCode::BadState;
        return false;
    }
    bool request_issued = radio_.start_transmit();
    if (!request_issued) {
        fail_immediately(ErrorCode::RegisterReadback);
        return false;
    }
    started_ms_ = now_ms;
    state_ = AttemptState::TxStarted;
    error_ = ErrorCode::None;
    return true;
}

void RadioTxStateMachine::tick(uint32_t now_ms) {
    if (state_ != AttemptState::TxStarted) {
        return;
    }

    if (radio_.terminal_irq_asserted()) {
        IrqSnapshot irq = {};
        bool poll_ok = radio_.poll_irq(&irq);
        if (!poll_ok) {
            finish_as_terminal(AttemptState::Error, ErrorCode::DeviceRadioTimeout);
            return;
        }
        if (irq.tx_done) {
            finish_as_terminal(AttemptState::TxDone, ErrorCode::None);
            return;
        }
    }

    uint32_t elapsed = now_ms - started_ms_;
    if (elapsed >= kTxWatchdogMs) {
        finish_as_terminal(AttemptState::Error, ErrorCode::DeviceRadioTimeout);
    }
}

bool RadioTxStateMachine::cancel() {
    if (!cleanup_ok_) {
        return false;
    }
    bool needs_cleanup = state_ == AttemptState::TxLoaded;
    if (state_ == AttemptState::TxStarted) {
        needs_cleanup = true;
    }
    if (needs_cleanup) {
        bool cleaned = radio_.finish_terminal();
        cleanup_ok_ = cleaned;
        if (!cleaned) {
            state_ = AttemptState::Error;
            error_ = ErrorCode::RegisterReadback;
            terminal_pending_ = false;
            return false;
        }
    }
    state_ = AttemptState::Standby;
    error_ = ErrorCode::None;
    terminal_pending_ = false;
    return true;
}

AttemptState RadioTxStateMachine::state() const {
    return state_;
}

AttemptKey RadioTxStateMachine::key() const {
    return key_;
}

uint32_t RadioTxStateMachine::frf_readback() const {
    return frf_readback_;
}

ErrorCode RadioTxStateMachine::error() const {
    return error_;
}

bool RadioTxStateMachine::has_terminal() const {
    return terminal_pending_;
}

AttemptState RadioTxStateMachine::terminal() const {
    return state_;
}

void RadioTxStateMachine::consume_terminal() {
    terminal_pending_ = false;
}

bool RadioTxStateMachine::cleanup_ok() const {
    return cleanup_ok_;
}

}  // namespace sx1278
