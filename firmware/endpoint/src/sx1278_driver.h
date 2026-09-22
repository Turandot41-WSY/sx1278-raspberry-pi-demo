#ifndef SX1278_DRIVER_H
#define SX1278_DRIVER_H

#include <stdint.h>

#include "radio_device.h"
#include "radio_io.h"

namespace sx1278 {

enum class RadioBank : uint8_t {
    Unknown = 0U,
    LoRa = 1U,
    FskOok = 2U
};

class Sx1278Driver : public RadioDevice {
public:
    /** Bind the raw driver to one caller-owned hardware I/O implementation. */
    explicit Sx1278Driver(RadioIo& io);

    /** Manually reset the chip and require the Rev. 7 version value 0x12.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 5.2.2, p. 117, and
     *   section 4.2 RegVersion (0x42), p. 105.
     *
     * Processing flow:
     *   output check -> low reset pulse -> release/wait -> bounded version
     *   reads -> expected version / last observed failure
     *
     * Project choice: after the required 5 ms delay, allow up to 20 version
     * reads separated by 1 ms. Reset occurs once; failure retains the last byte.
     */
    bool reset_and_probe(uint8_t* version);

    /** Read one SX1278 register with a single SPI transaction.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 2.2, p. 80.
     */
    uint8_t read_register(uint8_t address);

    /** Write one SX1278 register with a single SPI transaction.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 2.2, p. 80.
     */
    void write_register(uint8_t address, uint8_t value);

    /** Write one register and compare its masked readback.
     *
     *
     * Processing flow:
     *   output check -> write/read -> two masked values -> comparison
     */
    bool write_checked(
        uint8_t address,
        uint8_t value,
        uint8_t mask,
        uint8_t expected,
        uint8_t* actual
    );

    /** Enter Sleep before selecting and verifying one modem register bank.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), sections 4.2 and 4.4
     *   RegOpMode (0x01), pp. 93 and 108.
     *
     * Processing flow:
     *   current mode -> verified Sleep -> desired bank bits -> masked readback
     */
    bool configure_profile_op_mode(
        uint8_t value,
        uint8_t mask,
        uint8_t expected
    );

    /** Move the selected modem bank to verified Standby mode. */
    bool standby();

    /** Return the last successfully selected modem register bank. */
    RadioBank bank() const;

    /** Write and verify one absolute unsigned 24-bit FRF word in Standby.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 3.3.3, p. 82, and
     *   RegFrfMsb/Mid/Lsb in sections 4.2/4.4.
     *
     * Processing flow:
     *   width/output checks -> Standby -> three bytes -> 24-bit readback
     */
    bool set_frf_word(uint32_t word, uint32_t* readback);

    /** Read the three FRF registers as one unsigned 24-bit word.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 3.3.3, p. 82, and
     *   RegFrfMsb/Mid/Lsb in sections 4.2/4.4.
     *
     * Processing flow:
     *   three register reads -> positioned bytes -> combined FRF word
     */
    uint32_t read_frf_word();

    /** Write and fully verify RegPaDac, RegOcp, and RegPaConfig in Standby.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), sections 3.4.2-3.4.4,
     *   Tables 33, 34, and 37, pp. 83-85, plus sections 4.2/4.4 register maps.
     *
     * Processing flow:
     *   Standby -> PaDac check -> OCP check -> PaConfig check
     */
    bool set_pa_registers(
        uint8_t pa_config,
        uint8_t pa_dac,
        uint8_t ocp
    );

    /** Write one exact 64-byte frame to the active bank FIFO in Standby.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), sections 4.1.2.3, 2.1.10,
     *   and 2.2.
     *
     * Processing flow:
     *   input/Standby -> optional LoRa pointer reset -> 64-byte FIFO burst
     */
    bool write_tx_fifo(const uint8_t frame[64]);

    /** Apply one attempt FRF word and then load its 64-byte frame. */
    bool prepare_tx(
        uint32_t frf_word,
        const uint8_t frame[64],
        uint32_t* frf_readback
    ) override;

    /** Validate idle hardware and issue one transmission request.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Table 18, p. 46, and Table
     *   30, p. 69; Figure 9, p. 38; RegIrqFlags (0x12), p. 111.
     *
     * LoRa success means the request was issued after preflight checks. It does
     * not prove RF start or completion. The state machine requires a fresh,
     * validated TxDone indication before publishing completion.
     *
     * Processing flow:
     *   bank/mapping checks -> valid idle registers -> clear stale IRQ -> one TX
     *   request -> asynchronous completion through poll_irq and the watchdog
     */
    bool start_transmit() override;

    /** Return the register address and byte captured by the last failed TX start. */
    uint16_t tx_start_detail() const override { return tx_start_detail_; }

    /** Restore the nominal FRF word and enter bank-specific receive mode.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Table 16, p. 36, the
     *   receive sequence on p. 39, and Table 22, p. 54.
     *
     * Processing flow:
     *   nominal FRF -> clear/reset FIFO -> IRQ mapping -> continuous RX
     */
    bool prepare_rx(uint32_t* frf_readback) override;

    /** Read DIO0 before checking bank-specific terminal IRQ flags.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Table 18, p. 46, and Table
     *   30, p. 69.
     */
    bool terminal_irq_asserted() const override;

    /** Read active-bank IRQ flags into one initialized snapshot.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 4.4 RegIrqFlags and
     *   section 4.2 RegIrqFlags2 (0x3F), p. 104.
     *
     * Processing flow:
     *   output/bank checks -> LoRa or FSK flags -> optional RX metrics
     */
    bool poll_irq(IrqSnapshot* output) override;

    /** Read a bounded received payload from the active bank FIFO.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), sections 4.1.2.3, 2.1.10,
     *   and 2.2.
     *
     * Processing flow:
     *   bounds/bank checks -> optional LoRa pointer -> FIFO burst read
     */
    bool read_rx_fifo(uint8_t* frame, uint8_t count) override;

    /** Clear only LoRa W1C flags and finish in verified Standby.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 4.4 RegIrqFlags and
     *   section 4.2 RegIrqFlags2.
     *
     * Processing flow:
     *   bank check -> bank-specific IRQ/FIFO cleanup -> Standby
     */
    bool finish_terminal() override;

private:
    uint8_t transfer(uint8_t address, uint8_t value);
    bool set_mode(uint8_t mode, uint8_t* readback = 0);
    bool request_lora_transmit();
    bool poll_lora_tx_done(IrqSnapshot* output);

    RadioIo& io_;
    RadioBank bank_;
    uint16_t tx_start_detail_;
    bool lora_tx_pending_;
    uint8_t lora_tx_standby_mode_;
};

}  // namespace sx1278

#endif
