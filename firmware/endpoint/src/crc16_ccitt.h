#ifndef SX1278_CRC16_CCITT_H
#define SX1278_CRC16_CCITT_H

#include <stddef.h>
#include <stdint.h>

namespace sx1278 {

/** Compute the serial-message CRC-16/CCITT-FALSE remainder into caller storage.
 *
 *
 * The function returns false when output is null, or when data is null while
 * size is positive.  On either failure it does not publish a remainder.
 *
 * Processing flow:
 *   pointer validation -> MSB-first polynomial division -> output publication
 */
bool crc16_ccitt_false(const uint8_t* data, size_t size, uint16_t* output);

}  // namespace sx1278

#endif
