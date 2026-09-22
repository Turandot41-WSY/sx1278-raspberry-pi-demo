#ifndef SX1278_RADIO_RX_STATE_MACHINE_H
#define SX1278_RADIO_RX_STATE_MACHINE_H

#include <stdint.h>

#include "protocol_types.h"
#include "radio_device.h"

namespace sx1278 {

class RadioRxStateMachine {
public:
    /** Bind one receive state machine to one caller-owned radio. */
    explicit RadioRxStateMachine(RadioDevice& radio);

    /** Arm one keyed finite RX window at the fixed nominal frequency.
     *
     *
     * Processing flow:
     *   key/window checks -> fixed-frequency radio preparation -> FRF check -> publish state
     */
    bool arm(const AttemptKey& key, uint32_t now_ms, uint16_t window_ms);

    /** Advance RX using DIO0 packet evidence and a wrap-safe MCU deadline.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Table 18, p. 46, and Table
     *   30, p. 69.
     *
     * Inputs: Current MCU time in milliseconds and the bound radio IRQ state.
     * Output: A pending RX packet, timeout or procedural error after cleanup.
     * Project choice: an observed length above 64 preserves IRQ metadata without
     * reading the FIFO. The report carries no packet bytes in this case.
     *
     * Processing flow:
     *   active check -> IRQ or deadline -> copy bounded body or keep metadata -> cleanup
     */
    void tick(uint32_t now_ms);

    /** Cancel active RX only after verified radio cleanup.
     *
     *
     * Processing flow:
     *   cleanup lock check -> optional hardware cleanup -> reusable or error state
     */
    bool cancel();

    /** Return the currently published attempt state. */
    AttemptState state() const;

    /** Return the current keyed attempt. */
    AttemptKey key() const;

    /** Return the fixed nominal FRF value verified while arming RX. */
    uint32_t frf_readback() const;

    /** Return the finite MCU-owned receive window in milliseconds. */
    uint16_t window_ms() const;

    /** Return the most recent machine-level error. */
    ErrorCode error() const;

    /** Return whether exactly one unsent asynchronous terminal is pending. */
    bool has_terminal() const;

    /** Return the pending terminal state without consuming it. */
    AttemptState terminal() const;

    /** Mark the current asynchronous terminal as delivered. */
    void consume_terminal();

    /** Return the terminal IRQ and metrics snapshot. */
    const IrqSnapshot& irq() const;

    /** Return the receive buffer, valid only for an IRQ length of at most 64 bytes. */
    const uint8_t* payload() const;

    /** Return whether the radio is verified clean enough for another attempt. */
    bool cleanup_ok() const;

private:
    bool can_arm() const;
    void fail_immediately(ErrorCode error);
    void finish_as_terminal(AttemptState terminal, ErrorCode error);

    RadioDevice& radio_;
    AttemptKey key_;
    AttemptState state_;
    ErrorCode error_;
    uint32_t armed_ms_;
    uint32_t frf_readback_;
    uint16_t window_ms_;
    bool terminal_pending_;
    bool cleanup_ok_;
    IrqSnapshot irq_;
    uint8_t payload_[64];
};

}  // namespace sx1278

#endif
