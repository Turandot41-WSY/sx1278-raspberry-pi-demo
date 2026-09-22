#ifndef SX1278_EEPROM_IO_H
#define SX1278_EEPROM_IO_H

#include <stdint.h>

namespace sx1278 {

class EepromIo {
public:
    /** Release one EEPROM implementation through its interface safely. */
    virtual ~EepromIo() {}

    /** Read one byte from the ATmega328P EEPROM address space. */
    virtual uint8_t read(uint16_t address) = 0;

    /** Update one EEPROM byte while avoiding an unchanged-cell rewrite. */
    virtual void update(uint16_t address, uint8_t value) = 0;
};

}  // namespace sx1278

#endif
