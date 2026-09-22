#ifndef SX1278_RADIO_DEVICE_H
#define SX1278_RADIO_DEVICE_H

#include <stdint.h>

namespace sx1278 {

struct IrqSnapshot {
    bool tx_done;
    bool rx_done;
    bool phy_crc_ok;
    uint8_t received_length;
    uint8_t metrics_flags;
    uint8_t rssi_raw;
    int8_t snr_raw;
};

// RadioDevice is the small radio surface consumed by later attempt state machines.
class RadioDevice {
public:
    /** Release one concrete radio device through its base class. */
    virtual ~RadioDevice() {}

    /** Load one absolute FRF word and one exact 64-byte transmit frame. */
    virtual bool prepare_tx(
        uint32_t frf_word,
        const uint8_t frame[64],
        uint32_t* frf_readback
    ) = 0;

    /** Issue a prepared TX request; completion requires a later terminal IRQ. */
    virtual bool start_transmit() = 0;

    /** Return START_TX failure detail; zero means no register sample is available.
     * Project encoding: high byte = register address, low byte = actual readback.
     * Keep the captured value across cleanup so ENDPOINT_ERROR reports the cause.
     */
    virtual uint16_t tx_start_detail() const { return 0U; }

    /** Restore the fixed receive frequency and enter receive state. */
    virtual bool prepare_rx(uint32_t* frf_readback) = 0;

    /** Return whether the configured DIO0 terminal-interrupt line is high.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Table 18, p. 46, and Table
     *   30, p. 69.
     */
    virtual bool terminal_irq_asserted() const = 0;

    /** Capture terminal IRQ flags and available raw packet metrics. */
    virtual bool poll_irq(IrqSnapshot* output) = 0;

    /** Copy at most 64 received bytes from the radio FIFO. */
    virtual bool read_rx_fifo(uint8_t* frame, uint8_t count) = 0;

    /** Clear bank-specific terminal state and return the radio to standby. */
    virtual bool finish_terminal() = 0;
};

}  // namespace sx1278

#endif
