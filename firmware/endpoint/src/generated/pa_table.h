#ifndef SX1278_GENERATED_PA_TABLE_H
#define SX1278_GENERATED_PA_TABLE_H
#include <stdint.h>
#ifdef __AVR__
#include <avr/pgmspace.h>
#else
#define PROGMEM
#endif
namespace sx1278 {
namespace generated {
struct PaSetting {
  int8_t command_dbm;
  uint8_t reg_pa_config;
  uint8_t reg_pa_dac;
  uint8_t reg_ocp;
};
static const uint8_t kPaSettingCount = 6U;
static const uint8_t kRegOcpCandidateNeedsStage0 = 1U;
static const PaSetting kPaSettings[6] PROGMEM = {
    {2, 0x80U, 0x84U, 0x2BU},
    {5, 0x83U, 0x84U, 0x2BU},
    {8, 0x86U, 0x84U, 0x2BU},
    {11, 0x89U, 0x84U, 0x2BU},
    {14, 0x8CU, 0x84U, 0x2BU},
    {17, 0x8FU, 0x84U, 0x2BU},
};
/** Read one bounded PA setting from native memory or AVR flash.
 * Processing flow: index -> bounds check -> platform copy -> result.
 */
inline bool read_pa_setting(uint8_t index, PaSetting* output) {
  if (output == 0) {
    return false;
  }
  if (index >= kPaSettingCount) {
    return false;
  }
#ifdef __AVR__
  memcpy_P(output, &kPaSettings[index], sizeof(PaSetting));
#else
  *output = kPaSettings[index];
#endif
  return true;
}
/** Find one approved PA command without allocating memory.
 * Processing flow: command -> scan six flash rows -> copy match or fail.
 */
inline bool find_pa_setting(int8_t command_dbm, PaSetting* output) {
  if (output == 0) {
    return false;
  }
  for (uint8_t index = 0U; index < kPaSettingCount; ++index) {
    PaSetting candidate;
    bool read_ok = read_pa_setting(index, &candidate);
    if (!read_ok) {
      return false;
    }
    if (candidate.command_dbm == command_dbm) {
      *output = candidate;
      return true;
    }
  }
  return false;
}
}
}
#endif
