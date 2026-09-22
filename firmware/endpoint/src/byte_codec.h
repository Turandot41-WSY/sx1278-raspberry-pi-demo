#ifndef SX1278_BYTE_CODEC_H
#define SX1278_BYTE_CODEC_H

#include <stddef.h>
#include <stdint.h>

namespace sx1278 {

// A ByteReader consumes bounded serial-protocol fields in network byte order.
class ByteReader {
public:
    /** Bind a reader to one caller-owned immutable byte span.
     *
     */
    ByteReader(const uint8_t* data, size_t size);

    /** Read one unsigned byte without advancing after a bounds failure.
     *
     *
     * Processing flow:
     *   remaining-byte check -> field copy -> cursor advance
     */
    bool read_u8(uint8_t& value);

    /** Read one signed two's-complement byte through the unsigned primitive.
     *
     *
     * Processing flow:
     *   unsigned-byte read -> failure propagation -> signed interpretation
     */
    bool read_i8(int8_t& value);

    /** Read one unsigned 16-bit big-endian field atomically.
     *
     *
     * Processing flow:
     *   complete-field check -> big-endian assembly -> cursor advance
     */
    bool read_u16(uint16_t& value);

    /** Read one unsigned 24-bit big-endian field into a 32-bit value.
     *
     *
     * Processing flow:
     *   complete-field check -> big-endian assembly -> cursor advance
     */
    bool read_u24(uint32_t& value);

    /** Read one unsigned 32-bit big-endian field atomically.
     *
     *
     * Processing flow:
     *   complete-field check -> big-endian assembly -> cursor advance
     */
    bool read_u32(uint32_t& value);

    /** Copy a bounded byte field without advancing after a bounds failure.
     *
     *
     * Processing flow:
     *   source/destination check -> byte loop -> cursor advance
     */
    bool read_bytes(uint8_t* output, size_t count);

    /** Return the number of unread bytes in the bound span.
     *
     */
    size_t remaining() const;

    /** Report whether every byte in the bound span has been consumed.
     *
     */
    bool finished() const;

private:
    const uint8_t* data_;
    size_t size_;
    size_t position_;
};

// A ByteWriter emits bounded serial-protocol fields in network byte order.
class ByteWriter {
public:
    /** Bind a writer to one caller-owned mutable byte span.
     *
     */
    ByteWriter(uint8_t* data, size_t capacity);

    /** Write one unsigned byte without advancing after a bounds failure.
     *
     *
     * Processing flow:
     *   remaining-capacity check -> field store -> cursor advance
     */
    bool put_u8(uint8_t value);

    /** Write one signed two's-complement byte through the unsigned primitive.
     *
     */
    bool put_i8(int8_t value);

    /** Write one unsigned 16-bit big-endian field atomically.
     *
     *
     * Processing flow:
     *   complete-field check -> big-endian stores -> cursor advance
     */
    bool put_u16(uint16_t value);

    /** Write one range-checked unsigned 24-bit big-endian field atomically.
     *
     *
     * Processing flow:
     *   width/capacity check -> big-endian stores -> cursor advance
     */
    bool put_u24(uint32_t value);

    /** Write one unsigned 32-bit big-endian field atomically.
     *
     *
     * Processing flow:
     *   complete-field check -> big-endian stores -> cursor advance
     */
    bool put_u32(uint32_t value);

    /** Copy a bounded byte field without advancing after a bounds failure.
     *
     *
     * Processing flow:
     *   source/destination check -> byte loop -> cursor advance
     */
    bool put_bytes(const uint8_t* input, size_t count);

    /** Return the number of bytes written to the bound span.
     *
     */
    size_t size() const;

    /** Return the number of unwritten bytes in the bound span.
     *
     */
    size_t remaining() const;

private:
    uint8_t* data_;
    size_t capacity_;
    size_t position_;
};

inline ByteReader::ByteReader(const uint8_t* data, size_t size) {
    data_ = data;
    size_ = size;
    position_ = 0U;
}

inline bool ByteReader::read_u8(uint8_t& value) {
    const bool input_buffer_is_missing = data_ == 0;
    if (input_buffer_is_missing) {
        return false;
    }
    const bool field_is_truncated = remaining() < 1U;
    if (field_is_truncated) {
        return false;
    }
    value = data_[position_];
    position_ += 1U;
    return true;
}

inline bool ByteReader::read_i8(int8_t& value) {
    uint8_t encoded = 0U;
    if (!read_u8(encoded)) {
        return false;
    }
    if (encoded <= 127U) {
        value = static_cast<int8_t>(encoded);
        return true;
    }
    int16_t signed_value = static_cast<int16_t>(encoded);
    signed_value -= 256;
    value = static_cast<int8_t>(signed_value);
    return true;
}

inline bool ByteReader::read_u16(uint16_t& value) {
    const bool input_buffer_is_missing = data_ == 0;
    if (input_buffer_is_missing) {
        return false;
    }
    const bool field_is_truncated = remaining() < 2U;
    if (field_is_truncated) {
        return false;
    }
    const size_t high_index = position_;
    const uint8_t high_byte = data_[high_index];
    const uint32_t high_widened = static_cast<uint32_t>(high_byte);
    const uint32_t high_shifted = high_widened << 8U;

    const size_t low_index = position_ + 1U;
    const uint8_t low_byte = data_[low_index];
    const uint32_t low_widened = static_cast<uint32_t>(low_byte);

    const uint32_t wide_result = high_shifted | low_widened;
    const uint16_t result = static_cast<uint16_t>(wide_result);
    value = result;
    position_ += 2U;
    return true;
}

inline bool ByteReader::read_u24(uint32_t& value) {
    const bool input_buffer_is_missing = data_ == 0;
    if (input_buffer_is_missing) {
        return false;
    }
    const bool field_is_truncated = remaining() < 3U;
    if (field_is_truncated) {
        return false;
    }
    const size_t high_index = position_;
    const uint8_t high_byte = data_[high_index];
    const uint32_t high_widened = static_cast<uint32_t>(high_byte);
    const uint32_t high_shifted = high_widened << 16U;

    const size_t middle_index = position_ + 1U;
    const uint8_t middle_byte = data_[middle_index];
    const uint32_t middle_widened = static_cast<uint32_t>(middle_byte);
    const uint32_t middle_shifted = middle_widened << 8U;

    const size_t low_index = position_ + 2U;
    const uint8_t low_byte = data_[low_index];
    const uint32_t low_widened = static_cast<uint32_t>(low_byte);

    const uint32_t high_and_middle = high_shifted | middle_shifted;
    const uint32_t result = high_and_middle | low_widened;
    value = result;
    position_ += 3U;
    return true;
}

inline bool ByteReader::read_u32(uint32_t& value) {
    const bool input_buffer_is_missing = data_ == 0;
    if (input_buffer_is_missing) {
        return false;
    }
    const bool field_is_truncated = remaining() < 4U;
    if (field_is_truncated) {
        return false;
    }
    const size_t first_index = position_;
    const uint8_t first_byte = data_[first_index];
    const uint32_t first_widened = static_cast<uint32_t>(first_byte);
    const uint32_t first_shifted = first_widened << 24U;

    const size_t second_index = position_ + 1U;
    const uint8_t second_byte = data_[second_index];
    const uint32_t second_widened = static_cast<uint32_t>(second_byte);
    const uint32_t second_shifted = second_widened << 16U;

    const size_t third_index = position_ + 2U;
    const uint8_t third_byte = data_[third_index];
    const uint32_t third_widened = static_cast<uint32_t>(third_byte);
    const uint32_t third_shifted = third_widened << 8U;

    const size_t fourth_index = position_ + 3U;
    const uint8_t fourth_byte = data_[fourth_index];
    const uint32_t fourth_widened = static_cast<uint32_t>(fourth_byte);

    const uint32_t first_pair = first_shifted | second_shifted;
    const uint32_t first_three = first_pair | third_shifted;
    const uint32_t result = first_three | fourth_widened;
    value = result;
    position_ += 4U;
    return true;
}

inline bool ByteReader::read_bytes(uint8_t* output, size_t count) {
    const bool field_is_truncated = count > remaining();
    if (field_is_truncated) {
        return false;
    }
    const bool field_is_empty = count == 0U;
    if (field_is_empty) {
        return true;
    }
    const bool input_buffer_is_missing = data_ == 0;
    if (input_buffer_is_missing) {
        return false;
    }
    const bool output_buffer_is_missing = output == 0;
    if (output_buffer_is_missing) {
        return false;
    }
    for (size_t index = 0U; index < count; ++index) {
        const size_t source_index = position_ + index;
        const uint8_t source_byte = data_[source_index];
        output[index] = source_byte;
    }
    position_ += count;
    return true;
}

inline size_t ByteReader::remaining() const {
    return size_ - position_;
}

inline bool ByteReader::finished() const {
    return position_ == size_;
}

inline ByteWriter::ByteWriter(uint8_t* data, size_t capacity) {
    data_ = data;
    capacity_ = capacity;
    position_ = 0U;
}

inline bool ByteWriter::put_u8(uint8_t value) {
    const bool output_buffer_is_missing = data_ == 0;
    if (output_buffer_is_missing) {
        return false;
    }
    const bool field_will_not_fit = remaining() < 1U;
    if (field_will_not_fit) {
        return false;
    }
    data_[position_] = value;
    position_ += 1U;
    return true;
}

inline bool ByteWriter::put_i8(int8_t value) {
    const uint8_t encoded = static_cast<uint8_t>(value);
    return put_u8(encoded);
}

inline bool ByteWriter::put_u16(uint16_t value) {
    const bool output_buffer_is_missing = data_ == 0;
    if (output_buffer_is_missing) {
        return false;
    }
    const bool field_will_not_fit = remaining() < 2U;
    if (field_will_not_fit) {
        return false;
    }
    const uint16_t high_shifted = value >> 8U;
    const uint16_t high_masked = high_shifted & 0x00FFU;
    const uint8_t high_byte = static_cast<uint8_t>(high_masked);
    const size_t high_index = position_;
    data_[high_index] = high_byte;

    const uint16_t low_masked = value & 0x00FFU;
    const uint8_t low_byte = static_cast<uint8_t>(low_masked);
    const size_t low_index = position_ + 1U;
    data_[low_index] = low_byte;
    position_ += 2U;
    return true;
}

inline bool ByteWriter::put_u24(uint32_t value) {
    const bool output_buffer_is_missing = data_ == 0;
    if (output_buffer_is_missing) {
        return false;
    }
    const bool field_will_not_fit = remaining() < 3U;
    if (field_will_not_fit) {
        return false;
    }
    const bool value_is_too_wide = value > 0x00FFFFFFUL;
    if (value_is_too_wide) {
        return false;
    }
    const uint32_t high_shifted = value >> 16U;
    const uint32_t high_masked = high_shifted & 0x000000FFUL;
    const uint8_t high_byte = static_cast<uint8_t>(high_masked);
    const size_t high_index = position_;
    data_[high_index] = high_byte;

    const uint32_t middle_shifted = value >> 8U;
    const uint32_t middle_masked = middle_shifted & 0x000000FFUL;
    const uint8_t middle_byte = static_cast<uint8_t>(middle_masked);
    const size_t middle_index = position_ + 1U;
    data_[middle_index] = middle_byte;

    const uint32_t low_masked = value & 0x000000FFUL;
    const uint8_t low_byte = static_cast<uint8_t>(low_masked);
    const size_t low_index = position_ + 2U;
    data_[low_index] = low_byte;
    position_ += 3U;
    return true;
}

inline bool ByteWriter::put_u32(uint32_t value) {
    const bool output_buffer_is_missing = data_ == 0;
    if (output_buffer_is_missing) {
        return false;
    }
    const bool field_will_not_fit = remaining() < 4U;
    if (field_will_not_fit) {
        return false;
    }
    const uint32_t first_shifted = value >> 24U;
    const uint32_t first_masked = first_shifted & 0x000000FFUL;
    const uint8_t first_byte = static_cast<uint8_t>(first_masked);
    const size_t first_index = position_;
    data_[first_index] = first_byte;

    const uint32_t second_shifted = value >> 16U;
    const uint32_t second_masked = second_shifted & 0x000000FFUL;
    const uint8_t second_byte = static_cast<uint8_t>(second_masked);
    const size_t second_index = position_ + 1U;
    data_[second_index] = second_byte;

    const uint32_t third_shifted = value >> 8U;
    const uint32_t third_masked = third_shifted & 0x000000FFUL;
    const uint8_t third_byte = static_cast<uint8_t>(third_masked);
    const size_t third_index = position_ + 2U;
    data_[third_index] = third_byte;

    const uint32_t fourth_masked = value & 0x000000FFUL;
    const uint8_t fourth_byte = static_cast<uint8_t>(fourth_masked);
    const size_t fourth_index = position_ + 3U;
    data_[fourth_index] = fourth_byte;
    position_ += 4U;
    return true;
}

inline bool ByteWriter::put_bytes(const uint8_t* input, size_t count) {
    const bool field_will_not_fit = count > remaining();
    if (field_will_not_fit) {
        return false;
    }
    const bool field_is_empty = count == 0U;
    if (field_is_empty) {
        return true;
    }
    const bool output_buffer_is_missing = data_ == 0;
    if (output_buffer_is_missing) {
        return false;
    }
    const bool input_buffer_is_missing = input == 0;
    if (input_buffer_is_missing) {
        return false;
    }
    for (size_t index = 0U; index < count; ++index) {
        const uint8_t source_byte = input[index];
        const size_t output_index = position_ + index;
        data_[output_index] = source_byte;
    }
    position_ += count;
    return true;
}

inline size_t ByteWriter::size() const {
    return position_;
}

inline size_t ByteWriter::remaining() const {
    return capacity_ - position_;
}

}  // namespace sx1278

#endif
