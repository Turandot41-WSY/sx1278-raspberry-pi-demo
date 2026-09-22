#ifndef SX1278_GENERATED_BUILD_IDENTITY_H
#define SX1278_GENERATED_BUILD_IDENTITY_H
#include <stdint.h>
#ifdef __AVR__
#include <avr/pgmspace.h>
#else
#define PROGMEM
#endif
namespace sx1278 {
namespace generated {
static const uint8_t kFirmwareIdentitySha256[32] PROGMEM = {
    0x8BU, 0x5AU, 0x2AU, 0x26U, 0xACU, 0xACU, 0x5DU, 0x01U, 0x00U, 0x56U, 0xE8U, 0x8BU, 0xE0U, 0xC4U, 0x24U, 0x32U, 0xBFU, 0xCEU, 0x53U, 0x56U, 0xF0U, 0xC8U, 0x85U, 0x2BU, 0xD5U, 0x7BU, 0x30U, 0x5AU, 0xF5U, 0x9EU, 0xD3U, 0x98U
};
/** Read one firmware source-identity byte from native memory or AVR flash.
 * Processing flow: index/output checks -> platform read -> byte result.
 */
inline bool read_build_identity_byte(uint8_t index, uint8_t* output) {
  if (output == 0) {
    return false;
  }
  if (index >= 32U) {
    return false;
  }
#ifdef __AVR__
  *output = pgm_read_byte(&kFirmwareIdentitySha256[index]);
#else
  *output = kFirmwareIdentitySha256[index];
#endif
  return true;
}
}
}
#endif
