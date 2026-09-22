#ifndef SX1278_BOOT_COUNTER_H
#define SX1278_BOOT_COUNTER_H

#include <stdint.h>

#include "eeprom_io.h"

namespace sx1278 {

class BootCounter {
public:
    /** Bind a boot journal to one caller-owned EEPROM interface. */
    explicit BootCounter(EepromIo& eeprom);

    /** Recover and append one power-loss-safe boot count across sixteen slots.
     *
     *
     * Processing flow:
     *   sixteen slots -> valid CRC records -> next count/slot -> commit marker last
     */
    uint32_t increment();

private:
    bool read_valid_slot(uint8_t slot, uint32_t* value);
    void write_slot(uint8_t slot, uint32_t value);

    EepromIo& eeprom_;
};

}  // namespace sx1278

#endif
