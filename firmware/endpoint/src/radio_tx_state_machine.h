#ifndef SX1278_RADIO_TX_STATE_MACHINE_H
#define SX1278_RADIO_TX_STATE_MACHINE_H

#include <stdint.h>

#include "protocol_types.h"
#include "radio_device.h"

namespace sx1278 {

class RadioTxStateMachine {
public:
    /** Bind one transmit state machine to one caller-owned radio. */
    explicit RadioTxStateMachine(RadioDevice& radio);

    /** Load one keyed 64-byte frame and verify its absolute FRF readback.
     *
     *
     * Processing flow:
     *   request validation -> keyed radio preparation -> FRF check -> publish state
     */
    bool load(
        const AttemptKey& key,
        uint32_t frf_word,
        const uint8_t frame[64]
    );

    /** Issue one prepared TX request and arm its wrap-safe watchdog.
     * TxStarted means the request was issued, not a measured RF start time.
     *
     * Processing flow:
     *   state check -> radio start -> watchdog epoch -> publish state
     */
    bool start(uint32_t now_ms);

    /** Advance TX only when DIO0 or the finite watchdog supplies evidence.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Table 18, p. 46, and Table
     *   30, p. 69.
     *
     * Processing flow:
     *   active check -> DIO0/IRQ or watchdog -> verified cleanup -> one terminal
     */
    void tick(uint32_t now_ms);

    /** Cancel prepared or active TX only after verified radio cleanup.
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

    /** Return the absolute FRF value verified while loading this attempt. */
    uint32_t frf_readback() const;

    /** Return the most recent machine-level error. */
    ErrorCode error() const;

    /** Return the driver's TX-start register sample retained across cleanup. */
    uint16_t start_failure_detail() const { return radio_.tx_start_detail(); }

    /** Return whether exactly one unsent asynchronous terminal is pending. */
    bool has_terminal() const;

    /** Return the pending terminal state without consuming it. */
    AttemptState terminal() const;

    /** Mark the current asynchronous terminal as delivered. */
    void consume_terminal();

    /** Return whether the radio is verified clean enough for another attempt. */
    bool cleanup_ok() const;

private:
    bool can_load() const;
    void fail_immediately(ErrorCode error);
    void finish_as_terminal(AttemptState terminal, ErrorCode error);

    RadioDevice& radio_;
    AttemptKey key_;
    AttemptState state_;
    ErrorCode error_;
    uint32_t started_ms_;
    uint32_t frf_readback_;
    bool terminal_pending_;
    bool cleanup_ok_;
};

}  // namespace sx1278

#endif
