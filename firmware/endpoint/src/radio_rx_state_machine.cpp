#include "radio_rx_state_machine.h"

#include "sx1278_registers.h"

namespace sx1278 {

RadioRxStateMachine::RadioRxStateMachine(RadioDevice& radio) : radio_(radio) {
    key_.run_token = 0UL;
    key_.attempt_index = 0UL;
    state_ = AttemptState::Standby;
    error_ = ErrorCode::None;
    armed_ms_ = 0UL;
    frf_readback_ = 0UL;
    window_ms_ = 0U;
    terminal_pending_ = false;
    cleanup_ok_ = true;
    irq_ = IrqSnapshot();
    for (uint8_t index = 0U; index < 64U; ++index) {
        payload_[index] = 0U;
    }
}

/** Check whether another receive window can begin without losing pending state.
 *
 * The result requires successful prior cleanup, no undelivered terminal, and a
 * state other than RxArmed.
 *
 * Processing flow:
 *     Cleanup gate -> pending terminal gate -> active receive gate -> permission
 */
bool RadioRxStateMachine::can_arm() const {
    if (!cleanup_ok_) {
        return false;
    }
    if (terminal_pending_) {
        return false;
    }
    if (state_ == AttemptState::RxArmed) {
        return false;
    }
    return true;
}

/** Record a receive-command failure after attempting to return the radio to Standby.
 *
 * The input error describes preparation failure. Failed cleanup replaces it
 * with RegisterReadback. No asynchronous terminal is queued because the command
 * handler will report this immediate rejection.
 *
 * Processing flow:
 *     Radio cleanup -> Error state and supplied error -> clear terminal flag ->
 *     override error if cleanup failed
 */
void RadioRxStateMachine::fail_immediately(ErrorCode error) {
    bool cleaned = radio_.finish_terminal();
    cleanup_ok_ = cleaned;
    state_ = AttemptState::Error;
    error_ = error;
    terminal_pending_ = false;
    if (!cleaned) {
        error_ = ErrorCode::RegisterReadback;
    }
}

/** Queue a receive terminal after radio cleanup and preserve any cleanup failure.
 *
 * The inputs select the intended terminal state and error. Failed cleanup
 * replaces them with Error and RegisterReadback; terminal_pending_ remains true
 * until the controller delivers the resulting report.
 *
 * Processing flow:
 *     Radio cleanup -> requested terminal state/error -> mark pending -> replace
 *     outcome when cleanup failed
 */
void RadioRxStateMachine::finish_as_terminal(
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

bool RadioRxStateMachine::arm(
    const AttemptKey& key,
    uint32_t now_ms,
    uint16_t window_ms
) {
    if (!can_arm()) {
        error_ = ErrorCode::BadState;
        return false;
    }
    if (!is_valid_attempt_key(key)) {
        error_ = ErrorCode::BadState;
        return false;
    }
    if (window_ms == 0U) {
        error_ = ErrorCode::BadLength;
        return false;
    }

    key_ = key;
    error_ = ErrorCode::None;
    irq_ = IrqSnapshot();
    uint32_t readback = 0UL;
    bool prepared = radio_.prepare_rx(&readback);
    frf_readback_ = readback;
    if (!prepared) {
        fail_immediately(ErrorCode::RegisterReadback);
        return false;
    }
    if (readback != reg::NominalFrfWord) {
        fail_immediately(ErrorCode::FrfReadback);
        return false;
    }
    armed_ms_ = now_ms;
    window_ms_ = window_ms;
    state_ = AttemptState::RxArmed;
    cleanup_ok_ = true;
    return true;
}

void RadioRxStateMachine::tick(uint32_t now_ms) {
    if (state_ != AttemptState::RxArmed) {
        return;
    }

    if (radio_.terminal_irq_asserted()) {
        IrqSnapshot snapshot = {};
        bool poll_ok = radio_.poll_irq(&snapshot);
        if (!poll_ok) {
            finish_as_terminal(AttemptState::Error, ErrorCode::DeviceRadioTimeout);
            return;
        }
        if (snapshot.rx_done) {
            irq_ = snapshot;
            if (snapshot.received_length > 64U) {
                // Project choice: preserve IRQ metadata and skip the FIFO body
                // when it cannot fit the buffer of 64 bytes. The host classifies
                // PHY CRC before wireless length; cleanup errors stay procedural.
                finish_as_terminal(AttemptState::RxPacket, ErrorCode::None);
                return;
            }
            bool read_ok = radio_.read_rx_fifo(
                payload_,
                snapshot.received_length
            );
            if (!read_ok) {
                finish_as_terminal(AttemptState::Error, ErrorCode::RegisterReadback);
                return;
            }
            finish_as_terminal(AttemptState::RxPacket, ErrorCode::None);
            return;
        }
    }

    uint32_t elapsed = now_ms - armed_ms_;
    uint32_t window = static_cast<uint32_t>(window_ms_);
    if (elapsed >= window) {
        finish_as_terminal(AttemptState::RxTimeout, ErrorCode::None);
    }
}

bool RadioRxStateMachine::cancel() {
    if (!cleanup_ok_) {
        return false;
    }
    if (state_ == AttemptState::RxArmed) {
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

AttemptState RadioRxStateMachine::state() const {
    return state_;
}

AttemptKey RadioRxStateMachine::key() const {
    return key_;
}

uint32_t RadioRxStateMachine::frf_readback() const {
    return frf_readback_;
}

uint16_t RadioRxStateMachine::window_ms() const {
    return window_ms_;
}

ErrorCode RadioRxStateMachine::error() const {
    return error_;
}

bool RadioRxStateMachine::has_terminal() const {
    return terminal_pending_;
}

AttemptState RadioRxStateMachine::terminal() const {
    return state_;
}

void RadioRxStateMachine::consume_terminal() {
    terminal_pending_ = false;
}

const IrqSnapshot& RadioRxStateMachine::irq() const {
    return irq_;
}

const uint8_t* RadioRxStateMachine::payload() const {
    return payload_;
}

bool RadioRxStateMachine::cleanup_ok() const {
    return cleanup_ok_;
}

}  // namespace sx1278
