#include "crc16_ccitt.h"

namespace sx1278 {

bool crc16_ccitt_false(const uint8_t* data, size_t size, uint16_t* output) {
    const bool output_pointer_is_missing = output == 0;
    if (output_pointer_is_missing) {
        return false;
    }

    const bool input_buffer_is_missing = data == 0;
    if (input_buffer_is_missing) {
        const bool input_has_bytes = size > 0U;
        if (input_has_bytes) {
            return false;
        }
    }

    uint16_t remainder = 0xFFFFU;
    for (size_t byte_index = 0U; byte_index < size; ++byte_index) {
        const uint8_t source_byte = data[byte_index];
        const uint32_t widened_byte = static_cast<uint32_t>(source_byte);
        const uint32_t shifted_byte = widened_byte << 8U;
        const uint16_t aligned_byte = static_cast<uint16_t>(shifted_byte);
        const uint16_t mixed_remainder = remainder ^ aligned_byte;
        remainder = mixed_remainder;

        for (uint8_t bit_index = 0U; bit_index < 8U; ++bit_index) {
            const uint16_t masked_top_bit = remainder & 0x8000U;
            const bool top_bit_is_set = masked_top_bit != 0U;

            const uint32_t widened_remainder = static_cast<uint32_t>(remainder);
            const uint32_t shifted_remainder = widened_remainder << 1U;
            const uint16_t narrowed_remainder =
                static_cast<uint16_t>(shifted_remainder);

            if (top_bit_is_set) {
                const uint16_t polynomial_result = narrowed_remainder ^ 0x1021U;
                remainder = polynomial_result;
            } else {
                remainder = narrowed_remainder;
            }
        }
    }
    *output = remainder;
    return true;
}

}  // namespace sx1278
