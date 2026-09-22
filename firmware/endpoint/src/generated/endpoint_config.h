#ifndef SX1278_GENERATED_ENDPOINT_CONFIG_H
#define SX1278_GENERATED_ENDPOINT_CONFIG_H
#include <stdint.h>
#ifdef __AVR__
#include <avr/pgmspace.h>
#else
#define PROGMEM
#endif
namespace sx1278 {
namespace generated {
struct EndpointConfig {
  uint8_t role;
  uint32_t endpoint_id;
  uint8_t nss_pin;
  uint8_t reset_pin;
  uint8_t dio0_pin;
  uint8_t board_sha256[32];
  uint8_t pin_map_sha256[32];
};
static const uint8_t kEndpointReviewComplete = 0U;
static const uint8_t kEndpointConfigCount = 0U;
static const EndpointConfig kEndpointConfigs[2] PROGMEM = {
    {0U, 0UL, 0U, 0U, 0U, {0U}, {0U}},
    {1U, 0UL, 0U, 0U, 0U, {0U}, {0U}},
};
/** Read one endpoint only after the physical record is complete.
 * Processing flow: index -> review/count checks -> copy reviewed row.
 */
inline bool read_endpoint_config(uint8_t index, EndpointConfig* output) {
  if (output == 0) {
    return false;
  }
  if (kEndpointReviewComplete == 0U) {
    return false;
  }
  if (index >= 2U) {
    return false;
  }
#ifdef __AVR__
  memcpy_P(output, &kEndpointConfigs[index], sizeof(EndpointConfig));
#else
  *output = kEndpointConfigs[index];
#endif
  return true;
}
}
}
#endif
