#include "arduino_radio_io.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wpedantic"
#pragma GCC diagnostic ignored "-Wshadow"
#pragma GCC diagnostic ignored "-Wsign-conversion"
#include <Arduino.h>
#include <EEPROM.h>
#include <SPI.h>
#pragma GCC diagnostic pop

// Project-selected SPI clock; the local carrier build supplies its recorded value.
#ifndef SX1278_SPI_HZ
#define SX1278_SPI_HZ 8000000UL
#endif
static_assert(SX1278_SPI_HZ > 0UL, "SPI clock must be positive");
static_assert(SX1278_SPI_HZ <= 8000000UL, "SPI clock exceeds supported range");

namespace sx1278 {

ArduinoRadioIo::ArduinoRadioIo() {
    configured_ = false;
    nss_pin_ = 0U;
    reset_pin_ = 0U;
    dio0_pin_ = 0U;
}

bool ArduinoRadioIo::configure(
    uint8_t nss_pin,
    uint8_t reset_pin,
    uint8_t dio0_pin
) {
    configured_ = false;
    if (nss_pin < 2U) {
        return false;
    }
    if (nss_pin > 19U) {
        return false;
    }
    if (reset_pin < 2U) {
        return false;
    }
    if (reset_pin > 19U) {
        return false;
    }
    if (dio0_pin < 2U) {
        return false;
    }
    if (dio0_pin > 3U) {
        return false;
    }
    if (nss_pin == 11U) {
        return false;
    }
    if (nss_pin == 12U) {
        return false;
    }
    if (nss_pin == 13U) {
        return false;
    }
    if (reset_pin == 11U) {
        return false;
    }
    if (reset_pin == 12U) {
        return false;
    }
    if (reset_pin == 13U) {
        return false;
    }
    if (nss_pin == reset_pin) {
        return false;
    }
    if (nss_pin == dio0_pin) {
        return false;
    }
    if (reset_pin == dio0_pin) {
        return false;
    }
    nss_pin_ = nss_pin;
    reset_pin_ = reset_pin;
    dio0_pin_ = dio0_pin;
    configured_ = true;
    return true;
}

bool ArduinoRadioIo::begin() {
    if (!configured_) {
        return false;
    }
    pinMode(nss_pin_, OUTPUT);
    digitalWrite(nss_pin_, HIGH);
    set_reset_high(true);
    pinMode(dio0_pin_, INPUT);
    SPI.begin();
    return true;
}

void ArduinoRadioIo::begin_transaction() {
    if (!configured_) {
        return;
    }
    SPI.beginTransaction(SPISettings(SX1278_SPI_HZ, MSBFIRST, SPI_MODE0));
    digitalWrite(nss_pin_, LOW);
}

uint8_t ArduinoRadioIo::exchange(uint8_t value) {
    if (!configured_) {
        return 0U;
    }
    return SPI.transfer(value);
}

void ArduinoRadioIo::end_transaction() {
    if (!configured_) {
        return;
    }
    digitalWrite(nss_pin_, HIGH);
    SPI.endTransaction();
}

/** Assert reset low or release it with no MCU pull-up.
 *
 * References:
 * - Semtech SX1276/77/78/79 Datasheet Rev. 7 (May 2020), section 5.2.2,
 *   Figure 43, p. 117: reset is High-Z before and after the low pulse.
 *
 * Processing flow:
 *   Configured reset pin -> release as input / assert as low output
 */
void ArduinoRadioIo::set_reset_high(bool high) {
    if (!configured_) {
        return;
    }
    if (high) {
        // INPUT releases the pin; LOW disables the AVR input pull-up.
        pinMode(reset_pin_, INPUT);
        digitalWrite(reset_pin_, LOW);
    } else {
        // Set the output latch before enabling the driver to avoid a high pulse.
        digitalWrite(reset_pin_, LOW);
        pinMode(reset_pin_, OUTPUT);
    }
}

bool ArduinoRadioIo::dio0_high() const {
    if (!configured_) {
        return false;
    }
    int level = digitalRead(dio0_pin_);
    return level == HIGH;
}

void ArduinoRadioIo::delay_ms(uint16_t value) {
    delay(value);
}

uint8_t ArduinoEeprom::read(uint16_t address) {
    if (address > 1023U) {
        return 0U;
    }
    int eeprom_address = static_cast<int>(address);
    return EEPROM.read(eeprom_address);
}

void ArduinoEeprom::update(uint16_t address, uint8_t value) {
    if (address > 1023U) {
        return;
    }
    int eeprom_address = static_cast<int>(address);
    EEPROM.update(eeprom_address, value);
}

}  // namespace sx1278
