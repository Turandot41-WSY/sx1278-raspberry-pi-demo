#include "cobs.h"

namespace sx1278 {

bool cobs_encode(const uint8_t* input, size_t input_size, uint8_t* output,
                 size_t output_capacity, size_t* output_size) {
    const bool output_size_pointer_is_invalid = output_size == 0;
    if (output_size_pointer_is_invalid) {
        return false;
    }
    *output_size = 0U;

    bool input_pointer_is_invalid = false;
    if (input == 0) {
        if (input_size > 0U) {
            input_pointer_is_invalid = true;
        }
    }
    if (input_pointer_is_invalid) {
        return false;
    }

    const bool output_pointer_is_invalid = output == 0;
    if (output_pointer_is_invalid) {
        return false;
    }

    const bool output_capacity_is_empty = output_capacity == 0U;
    if (output_capacity_is_empty) {
        return false;
    }

    size_t read_index = 0U;
    size_t write_index = 1U;
    size_t code_index = 0U;
    uint8_t code = 1U;

    while (read_index < input_size) {
        const bool input_byte_is_zero = input[read_index] == 0U;
        if (input_byte_is_zero) {
            output[code_index] = code;
            code = 1U;
            code_index = write_index;
            const bool output_is_full = write_index >= output_capacity;
            if (output_is_full) {
                return false;
            }
            write_index += 1U;
            read_index += 1U;
        } else {
            const bool output_is_full = write_index >= output_capacity;
            if (output_is_full) {
                return false;
            }
            const uint8_t input_byte = input[read_index];
            output[write_index] = input_byte;
            write_index += 1U;
            read_index += 1U;
            const uint16_t widened_code = static_cast<uint16_t>(code);
            const uint16_t incremented_code = widened_code + 1U;
            code = static_cast<uint8_t>(incremented_code);
            const bool run_reached_254_bytes = code == 0xFFU;
            if (run_reached_254_bytes) {
                output[code_index] = code;
                const bool input_is_finished = read_index == input_size;
                if (input_is_finished) {
                    *output_size = write_index;
                    return true;
                }
                code = 1U;
                code_index = write_index;
                const bool output_is_full_after_run = write_index >= output_capacity;
                if (output_is_full_after_run) {
                    return false;
                }
                write_index += 1U;
            }
        }
    }

    output[code_index] = code;
    *output_size = write_index;
    return true;
}

bool cobs_decode(const uint8_t* input, size_t input_size, uint8_t* output,
                 size_t output_capacity, size_t* output_size) {
    const bool output_size_pointer_is_invalid = output_size == 0;
    if (output_size_pointer_is_invalid) {
        return false;
    }
    *output_size = 0U;

    const bool input_pointer_is_invalid = input == 0;
    if (input_pointer_is_invalid) {
        return false;
    }

    const bool input_body_is_empty = input_size == 0U;
    if (input_body_is_empty) {
        return false;
    }

    bool output_pointer_is_invalid = false;
    if (output == 0) {
        if (output_capacity > 0U) {
            output_pointer_is_invalid = true;
        }
    }
    if (output_pointer_is_invalid) {
        return false;
    }

    size_t read_index = 0U;
    size_t write_index = 0U;
    while (read_index < input_size) {
        const uint8_t code = input[read_index];
        read_index += 1U;
        const bool code_is_zero = code == 0U;
        if (code_is_zero) {
            return false;
        }

        const uint16_t widened_block_code = static_cast<uint16_t>(code);
        const uint16_t decremented_block_code = widened_block_code - 1U;
        const uint8_t encoded_block_size =
            static_cast<uint8_t>(decremented_block_code);
        const size_t block_size = static_cast<size_t>(encoded_block_size);
        const size_t input_remaining = input_size - read_index;
        const bool block_is_truncated = block_size > input_remaining;
        if (block_is_truncated) {
            return false;
        }

        const size_t output_remaining = output_capacity - write_index;
        const bool output_would_overflow = block_size > output_remaining;
        if (output_would_overflow) {
            return false;
        }
        for (size_t block_index = 0U; block_index < block_size; ++block_index) {
            const size_t input_index = read_index + block_index;
            const uint8_t value = input[input_index];
            const bool encoded_body_contains_zero = value == 0U;
            if (encoded_body_contains_zero) {
                return false;
            }
            const size_t output_index = write_index + block_index;
            output[output_index] = value;
        }
        read_index += block_size;
        write_index += block_size;

        const bool block_implies_zero = code != 0xFFU;
        const bool another_block_follows = read_index < input_size;
        if (block_implies_zero) {
            if (!another_block_follows) {
                continue;
            }
            const bool output_is_full = write_index >= output_capacity;
            if (output_is_full) {
                return false;
            }
            const bool output_is_missing = output == 0;
            if (output_is_missing) {
                return false;
            }
            output[write_index] = 0U;
            write_index += 1U;
        }
    }

    *output_size = write_index;
    return true;
}

}  // namespace sx1278
