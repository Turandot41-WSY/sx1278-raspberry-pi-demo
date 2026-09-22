#ifndef SX1278_RADIO_IO_H
#define SX1278_RADIO_IO_H

#include <stdint.h>

namespace sx1278 {

// RadioIo isolates the driver from Arduino SPI, GPIO, and delay functions.
class RadioIo {
public:
    /** Release one concrete radio-I/O implementation through its base class. */
    virtual ~RadioIo() {}

    /** Pull NSS low and begin one SPI mode-0 transaction.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 2.2, "SPI
     *   Interface", p. 80.
     */
    virtual void begin_transaction() = 0;

    /** Exchange one SPI byte, most-significant bit first.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 2.2, "SPI
     *   Interface", p. 80.
     */
    virtual uint8_t exchange(uint8_t value) = 0;

    /** Pull NSS high and finish the current SPI transaction.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 2.2, "SPI
     *   Interface", p. 80.
     */
    virtual void end_transaction() = 0;

    /** Assert the active-low reset when false; release it to high impedance when true.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 5.2.2, "Manual
     *   Reset", Figure 43, p. 117. The legacy high parameter means release,
     *   not an actively driven high voltage.
     */
    virtual void set_reset_high(bool high) = 0;

    /** Read the physically selected DIO0 terminal-interrupt input.
     *
     * References:
     * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 4.1, Table 18, p.
     *   46, and section 2.1.11, Table 30, p. 69.
     */
    virtual bool dio0_high() const = 0;

    /** Wait a whole number of milliseconds without changing radio state. */
    virtual void delay_ms(uint16_t value) = 0;
};

}  // namespace sx1278

#endif
