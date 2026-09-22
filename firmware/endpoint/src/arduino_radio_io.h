#ifndef SX1278_ARDUINO_RADIO_IO_H
#define SX1278_ARDUINO_RADIO_IO_H

#include <stdint.h>

#include "eeprom_io.h"
#include "radio_io.h"

namespace sx1278 {

class ArduinoRadioIo : public RadioIo {
public:
    /** Initialize an unconfigured adapter that cannot touch external pins. */
    ArduinoRadioIo();

    /** Accept one reviewed Nano pin map before hardware initialization.
     *
     * References:
     * - Arduino Nano hardware SPI mapping: D11 MOSI, D12 MISO, D13 SCK; ATmega328P
     *   external interrupts INT0/INT1 on D2/D3.
     *
     * Processing flow:
     *   ranges -> SPI-pin exclusions -> distinct pins -> publish configuration
     */
    bool configure(uint8_t nss_pin, uint8_t reset_pin, uint8_t dio0_pin);

    /** Configure GPIO and hardware SPI only after a reviewed pin map. */
    bool begin();

    /** Pull reviewed NSS low after starting one configured SPI mode-0 transaction. */
    void begin_transaction() override;

    /** Exchange one byte over Arduino hardware SPI. */
    uint8_t exchange(uint8_t value) override;

    /** Release reviewed NSS before ending the active SPI transaction. */
    void end_transaction() override;

    /** Assert RESET low when false; release as an input without pull-up when true. */
    void set_reset_high(bool high) override;

    /** Read the reviewed DIO0 terminal-interrupt connection. */
    bool dio0_high() const override;

    /** Wait the requested whole milliseconds during manual reset only. */
    void delay_ms(uint16_t value) override;

private:
    bool configured_;
    uint8_t nss_pin_;
    uint8_t reset_pin_;
    uint8_t dio0_pin_;
};

class ArduinoEeprom : public EepromIo {
public:
    /** Read one byte from the Nano ATmega328P EEPROM. */
    uint8_t read(uint16_t address) override;

    /** Update one Nano EEPROM cell only when its value changes. */
    void update(uint16_t address, uint8_t value) override;
};

}  // namespace sx1278

#endif
