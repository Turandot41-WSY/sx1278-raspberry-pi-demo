#include "boot_counter.h"

#include "byte_codec.h"
#include "crc16_ccitt.h"

namespace sx1278 {

static const uint8_t kBootSlotCount = 16U;
static const uint8_t kBootSlotSize = 8U;
static const uint8_t kBootMagicFirst = 0x53U;
static const uint8_t kBootMagicSecond = 0x58U;

BootCounter::BootCounter(EepromIo& eeprom) : eeprom_(eeprom) {}

/** Recover a boot count only from a complete journal slot with matching CRC.
 *
 * The slot input selects one of sixteen EEPROM records. A nonnull value receives
 * the decoded count only on success; false leaves the caller's output unchanged.
 *
 * Processing flow:
 *     Slot/output bounds -> eight EEPROM bytes -> commit markers -> count and CRC
 *     decode -> CRC comparison -> publish recovered count
 */
bool BootCounter::read_valid_slot(uint8_t slot, uint32_t* value) {
    if (value == 0) {
        return false;
    }
    if (slot >= kBootSlotCount) {
        return false;
    }
    uint8_t bytes[kBootSlotSize] = {0U};
    uint16_t start = static_cast<uint16_t>(slot);
    start *= kBootSlotSize;
    for (uint8_t index = 0U; index < kBootSlotSize; ++index) {
        uint16_t address = start;
        address += index;
        bytes[index] = eeprom_.read(address);
    }
    if (bytes[0] != kBootMagicFirst) {
        return false;
    }
    if (bytes[1] != kBootMagicSecond) {
        return false;
    }
    ByteReader value_reader(bytes + 2U, 4U);
    uint32_t decoded_value = 0UL;
    if (!value_reader.read_u32(decoded_value)) {
        return false;
    }
    ByteReader crc_reader(bytes + 6U, 2U);
    uint16_t stored_crc = 0U;
    if (!crc_reader.read_u16(stored_crc)) {
        return false;
    }
    uint16_t calculated_crc = 0U;
    bool crc_ok = crc16_ccitt_false(bytes + 2U, 4U, &calculated_crc);
    if (!crc_ok) {
        return false;
    }
    if (stored_crc != calculated_crc) {
        return false;
    }
    *value = decoded_value;
    return true;
}

/** Store a boot count in an invalidated journal slot and commit its markers last.
 *
 * The caller supplies an already bounded slot index and the count to persist.
 * This method has no success result; an early encoding failure leaves the slot
 * invalid so a later boot scan will not accept an incomplete record.
 *
 * Processing flow:
 *     Clear both commit markers -> encode and write count -> calculate and write
 *     CRC -> write both commit markers
 */
void BootCounter::write_slot(uint8_t slot, uint32_t value) {
    uint16_t start = static_cast<uint16_t>(slot);
    start *= kBootSlotSize;
    eeprom_.update(start, 0U);
    uint16_t second_magic_address = start + 1U;
    eeprom_.update(second_magic_address, 0U);

    uint8_t value_bytes[4] = {0U};
    ByteWriter writer(value_bytes, sizeof(value_bytes));
    if (!writer.put_u32(value)) {
        return;
    }
    for (uint8_t index = 0U; index < 4U; ++index) {
        uint16_t address = start + 2U;
        address += index;
        eeprom_.update(address, value_bytes[index]);
    }
    uint16_t crc = 0U;
    if (!crc16_ccitt_false(value_bytes, sizeof(value_bytes), &crc)) {
        return;
    }
    uint8_t crc_bytes[2] = {0U};
    ByteWriter crc_writer(crc_bytes, sizeof(crc_bytes));
    if (!crc_writer.put_u16(crc)) {
        return;
    }
    uint16_t first_crc_address = start + 6U;
    uint16_t second_crc_address = start + 7U;
    eeprom_.update(first_crc_address, crc_bytes[0]);
    eeprom_.update(second_crc_address, crc_bytes[1]);
    eeprom_.update(start, kBootMagicFirst);
    eeprom_.update(second_magic_address, kBootMagicSecond);
}

uint32_t BootCounter::increment() {
    uint32_t best_value = 0UL;
    uint8_t best_slot = 0U;
    bool found = false;
    for (uint8_t slot = 0U; slot < kBootSlotCount; ++slot) {
        uint32_t candidate = 0UL;
        if (!read_valid_slot(slot, &candidate)) {
            continue;
        }
        if (!found) {
            found = true;
            best_value = candidate;
            best_slot = slot;
            continue;
        }
        if (candidate >= best_value) {
            best_value = candidate;
            best_slot = slot;
        }
    }
    if (best_value == 0xFFFFFFFFUL) {
        return 0UL;
    }
    uint8_t next_slot = 0U;
    if (found) {
        uint16_t widened_slot = static_cast<uint16_t>(best_slot);
        widened_slot += 1U;
        next_slot = static_cast<uint8_t>(widened_slot);
        if (next_slot >= kBootSlotCount) {
            next_slot = 0U;
        }
    }
    uint32_t next_value = best_value + 1UL;
    write_slot(next_slot, next_value);
    return next_value;
}

}  // namespace sx1278
