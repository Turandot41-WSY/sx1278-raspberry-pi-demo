#ifndef SX1278_COBS_H
#define SX1278_COBS_H

#include <stddef.h>
#include <stdint.h>

namespace sx1278 {

/** Encode one delimiter-free COBS message body into a bounded buffer.
 *
 *
 * Processing flow:
 *   raw bytes -> bounded nonzero runs -> delimiter-free COBS body
 *
 * On failure, output_size is set to zero when that pointer is valid.  The
 * output buffer contents are unavailable and must not be consumed.
 */
bool cobs_encode(const uint8_t* input, size_t input_size, uint8_t* output,
                 size_t output_capacity, size_t* output_size);

/** Decode one delimiter-free COBS message body into a bounded buffer.
 *
 *
 * Processing flow:
 *   COBS code blocks -> validated nonzero runs -> reconstructed raw bytes
 *
 * On failure, output_size is set to zero when that pointer is valid.  The
 * output buffer contents are unavailable and must not be consumed.
 */
bool cobs_decode(const uint8_t* input, size_t input_size, uint8_t* output,
                 size_t output_capacity, size_t* output_size);

}  // namespace sx1278

#endif
