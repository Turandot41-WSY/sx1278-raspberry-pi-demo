#include "sx1278_driver.h"

#include "sx1278_registers.h"

namespace sx1278 {

Sx1278Driver::Sx1278Driver(RadioIo& io) : io_(io) {
    bank_ = RadioBank::Unknown;
    tx_start_detail_ = 0U;
    lora_tx_pending_ = false;
    lora_tx_standby_mode_ = 0U;
}

/** Exchange a register command and one data byte inside one SPI transaction.
 *
 * The address input already contains the caller-selected read/write bits. The
 * value is the transmitted data byte; the returned byte is received during that
 * second exchange. The command-phase received byte is discarded.
 *
 * Processing flow:
 *     Begin SPI transaction -> exchange command -> exchange data -> end
 *     transaction -> return received data byte
 */
uint8_t Sx1278Driver::transfer(uint8_t address, uint8_t value) {
    io_.begin_transaction();
    io_.exchange(address);
    uint8_t output = io_.exchange(value);
    io_.end_transaction();
    return output;
}

uint8_t Sx1278Driver::read_register(uint8_t address) {
    uint8_t read_address = address;
    read_address &= bit::Address;
    return transfer(read_address, 0U);
}

void Sx1278Driver::write_register(uint8_t address, uint8_t value) {
    uint8_t register_address = address;
    register_address &= bit::Address;
    uint8_t write_address = register_address;
    write_address |= bit::SpiWrite;
    transfer(write_address, value);
}

bool Sx1278Driver::write_checked(
    uint8_t address,
    uint8_t value,
    uint8_t mask,
    uint8_t expected,
    uint8_t* actual
) {
    if (actual == 0) {
        return false;
    }
    write_register(address, value);
    *actual = read_register(address);
    uint8_t masked_actual = *actual;
    masked_actual &= mask;
    uint8_t masked_expected = expected;
    masked_expected &= mask;
    return masked_actual == masked_expected;
}

bool Sx1278Driver::reset_and_probe(uint8_t* version) {
    if (version == 0) {
        return false;
    }
    io_.set_reset_high(false);
    io_.delay_ms(1U);
    io_.set_reset_high(true);
    io_.delay_ms(5U);
    bank_ = RadioBank::Unknown;
    lora_tx_pending_ = false;
    // Semtech Rev. 7, section 5.2.2, Figure 43, p. 117 requires 5 ms
    // after reset release. Project choice: allow up to 20 reads with 1 ms
    // spacing because the first post-reset SPI read may still be transient.
    // Only version reads repeat; reset and RF commands are never retried here.
    const uint8_t maximum_reads = 20U;
    for (uint8_t sample = 0U; sample < maximum_reads; ++sample) {
        *version = read_register(reg::Version);
        if (*version == 0x12U) {
            return true;
        }
        if (sample + 1U < maximum_reads) {
            io_.delay_ms(1U);
        }
    }
    return false;
}

bool Sx1278Driver::configure_profile_op_mode(
    uint8_t value,
    uint8_t mask,
    uint8_t expected
) {
    uint8_t current = read_register(reg::OpMode);
    uint8_t sleep_value = current;
    sleep_value &= bit::ModeKeepMask;
    write_register(reg::OpMode, sleep_value);
    uint8_t sleep_readback = read_register(reg::OpMode);
    uint8_t sleep_mode = sleep_readback;
    sleep_mode &= bit::ModeMask;
    if (sleep_mode != bit::Sleep) {
        return false;
    }

    uint8_t desired_sleep = value;
    desired_sleep &= bit::ModeKeepMask;
    write_register(reg::OpMode, desired_sleep);
    uint8_t actual = read_register(reg::OpMode);
    uint8_t masked_actual = actual;
    masked_actual &= mask;
    uint8_t masked_expected = expected;
    masked_expected &= mask;
    if (masked_actual != masked_expected) {
        return false;
    }
    uint8_t bank_bit = actual;
    bank_bit &= bit::LongRange;
    if (bank_bit == bit::LongRange) {
        bank_ = RadioBank::LoRa;
    } else {
        bank_ = RadioBank::FskOok;
    }
    return true;
}

/** Write and verify an operating mode outside the asynchronous LoRa TX path.
 *
 * References:
 * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), RegOpMode (0x01),
 *   pp. 93 and 108; section 2.1.4 Table 22, pp. 54-55, and section 2.1.5,
 *   Figure 17 and Table 23, pp. 56-57, describe FSK/OOK receiver startup.
 *   LoRa TX uses request_lora_transmit and terminal validation.
 *
 * Project choice: allow 20 observations separated by 1 ms for FSK/OOK RX.
 * Its mode readback can still show FSRx while the receiver starts. Request RX
 * once, then observe it; a persistent mismatch remains a readback failure.
 *
 * Processing flow:
 *   known bank -> preserve non-mode bits -> write requested mode -> read back ->
 *   bounded FSK/OOK RX transition wait -> retain byte -> compare mode bits
 */
bool Sx1278Driver::set_mode(uint8_t mode, uint8_t* readback) {
    if (bank_ == RadioBank::Unknown) {
        return false;
    }
    uint8_t current = read_register(reg::OpMode);
    uint8_t without_mode = current;
    without_mode &= bit::ModeKeepMask;
    uint8_t desired = without_mode;
    desired |= mode;
    write_register(reg::OpMode, desired);
    uint8_t actual = read_register(reg::OpMode);
    if (bank_ == RadioBank::FskOok) {
        if (mode == bit::RxContinuous) {
            const uint8_t maximum_reads = 20U;
            for (uint8_t sample = 1U; sample < maximum_reads; ++sample) {
                uint8_t observed_mode = actual & bit::ModeMask;
                if (observed_mode == mode) {
                    break;
                }
                io_.delay_ms(1U);
                actual = read_register(reg::OpMode);
            }
        }
    }
    if (readback != 0) {
        *readback = actual;
    }
    uint8_t actual_mode = actual;
    actual_mode &= bit::ModeMask;
    return actual_mode == mode;
}

bool Sx1278Driver::standby() {
    return set_mode(bit::Standby);
}

RadioBank Sx1278Driver::bank() const {
    return bank_;
}

uint32_t Sx1278Driver::read_frf_word() {
    uint8_t msb = read_register(reg::FrfMsb);
    uint8_t middle = read_register(reg::FrfMid);
    uint8_t lsb = read_register(reg::FrfLsb);
    uint32_t msb_part = static_cast<uint32_t>(msb);
    msb_part <<= 16U;
    uint32_t middle_part = static_cast<uint32_t>(middle);
    middle_part <<= 8U;
    uint32_t word = msb_part;
    word += middle_part;
    word += static_cast<uint32_t>(lsb);
    return word;
}

bool Sx1278Driver::set_frf_word(uint32_t word, uint32_t* readback) {
    if (readback == 0) {
        return false;
    }
    if (word > 0x00FFFFFFUL) {
        return false;
    }
    if (!standby()) {
        return false;
    }
    uint32_t shifted_msb = word >> 16U;
    uint8_t msb = static_cast<uint8_t>(shifted_msb);
    uint32_t shifted_middle = word >> 8U;
    uint8_t middle = static_cast<uint8_t>(shifted_middle);
    uint8_t lsb = static_cast<uint8_t>(word);
    write_register(reg::FrfMsb, msb);
    write_register(reg::FrfMid, middle);
    write_register(reg::FrfLsb, lsb);
    *readback = read_frf_word();
    return *readback == word;
}

bool Sx1278Driver::set_pa_registers(
    uint8_t pa_config,
    uint8_t pa_dac,
    uint8_t ocp
) {
    if (!standby()) {
        return false;
    }
    uint8_t actual = 0U;
    bool pa_dac_ok = write_checked(reg::PaDac, pa_dac, 0xFFU, pa_dac, &actual);
    if (!pa_dac_ok) {
        return false;
    }
    bool ocp_ok = write_checked(reg::Ocp, ocp, 0xFFU, ocp, &actual);
    if (!ocp_ok) {
        return false;
    }
    return write_checked(reg::PaConfig, pa_config, 0xFFU, pa_config, &actual);
}

bool Sx1278Driver::write_tx_fifo(const uint8_t frame[64]) {
    if (frame == 0) {
        return false;
    }
    if (!standby()) {
        return false;
    }
    if (bank_ == RadioBank::LoRa) {
        write_register(reg::LoRaFifoTxBase, 0U);
        write_register(reg::LoRaFifoAddrPtr, 0U);
    } else {
        write_register(reg::FskIrqFlags2, bit::FskFifoOverrun);
    }
    uint8_t fifo_write = reg::Fifo;
    fifo_write |= bit::SpiWrite;
    io_.begin_transaction();
    io_.exchange(fifo_write);
    for (uint8_t index = 0U; index < 64U; ++index) {
        io_.exchange(frame[index]);
    }
    io_.end_transaction();
    return true;
}

bool Sx1278Driver::prepare_tx(
    uint32_t frf_word,
    const uint8_t frame[64],
    uint32_t* frf_readback
) {
    if (frame == 0) {
        return false;
    }
    if (!set_frf_word(frf_word, frf_readback)) {
        return false;
    }
    return write_tx_fifo(frame);
}

bool Sx1278Driver::start_transmit() {
    tx_start_detail_ = 0U;
    if (bank_ == RadioBank::Unknown) {
        return false;
    }
    if (lora_tx_pending_) {
        return false;
    }
    if (bank_ == RadioBank::LoRa) {
        uint8_t actual = 0U;
        bool mapping_ok = write_checked(
            reg::DioMapping1,
            bit::LoRaDio0TxDone,
            bit::Dio0Mask,
            bit::LoRaDio0TxDone,
            &actual
        );
        if (!mapping_ok) {
            tx_start_detail_ = static_cast<uint16_t>(reg::DioMapping1);
            tx_start_detail_ <<= 8U;
            tx_start_detail_ |= actual;
            return false;
        }
        return request_lora_transmit();
    }
    uint8_t actual = 0U;
    bool started = set_mode(bit::Tx, &actual);
    if (!started) {
        // Project diagnostic bytes use the existing ENDPOINT_ERROR detail field.
        // Capture now: cleanup subsequently writes Standby to the same register.
        tx_start_detail_ = static_cast<uint16_t>(reg::OpMode);
        tx_start_detail_ <<= 8U;
        tx_start_detail_ |= actual;
    }
    return started;
}

/** Issue one LoRa TX request after checking idle identity, mode and IRQ state.
 *
 * References:
 * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Figure 9, p. 38;
 *   RegVersion (0x42), p. 105; RegOpMode (0x01), p. 108;
 *   RegIrqFlags (0x12), p. 111.
 *
 * Project policy: do not read SPI during active TX. On the attached hardware,
 * even RegVersion becomes corrupt until the packet ends. A request therefore
 * remains pending until DIO0 and valid terminal registers confirm completion.
 *
 * Processing flow:
 *   idle version/mode checks -> clear and verify IRQ -> require DIO0 low ->
 *   preserve verified mode bits -> write TX once -> mark pending
 */
bool Sx1278Driver::request_lora_transmit() {
    uint8_t version = read_register(reg::Version);
    tx_start_detail_ = static_cast<uint16_t>(reg::Version);
    tx_start_detail_ <<= 8U;
    tx_start_detail_ |= version;
    if (version != 0x12U) {
        return false;
    }
    uint8_t current = read_register(reg::OpMode);
    uint8_t repeated = read_register(reg::OpMode);
    tx_start_detail_ = static_cast<uint16_t>(reg::OpMode);
    tx_start_detail_ <<= 8U;
    tx_start_detail_ |= repeated;
    // This project uses the LoRa low-frequency bank in Standby (437.5 MHz).
    if (current != 0x89U) {
        return false;
    }
    if (repeated != current) {
        return false;
    }
    write_register(reg::LoRaIrqFlags, 0xFFU);
    uint8_t flags = read_register(reg::LoRaIrqFlags);
    tx_start_detail_ = static_cast<uint16_t>(reg::LoRaIrqFlags);
    tx_start_detail_ <<= 8U;
    tx_start_detail_ |= flags;
    if (flags != 0U) {
        return false;
    }
    if (io_.dio0_high()) {
        return false;
    }
    tx_start_detail_ = 0U;
    lora_tx_standby_mode_ = current;
    uint8_t requested = current & bit::ModeKeepMask;
    requested |= bit::Tx;
    write_register(reg::OpMode, requested);
    lora_tx_pending_ = true;
    return true;
}

/** Confirm a pending LoRa transmission only from consistent terminal evidence.
 *
 * References:
 * - Semtech, SX1276/77/78/79 Datasheet Rev. 7 (May 2020), Figure 9, p. 38;
 *   Table 18, p. 46; RegIrqFlags (0x12), p. 111.
 *
 * Project policy: qualify two matching TxDone samples with the fixed version
 * and the automatic return to Standby. Invalid samples leave the attempt
 * pending; the state machine's existing watchdog bounds these read-only checks.
 * The empty output never turns an untrusted sample into success.
 *
 * Processing flow:
 *   DIO0 gate -> version/IRQ/mode/IRQ/version snapshot -> consistency checks ->
 *   confirm TxDone or leave pending for the next tick
 */
bool Sx1278Driver::poll_lora_tx_done(IrqSnapshot* output) {
    if (!io_.dio0_high()) {
        return true;
    }
    uint8_t version_before = read_register(reg::Version);
    uint8_t flags_before = read_register(reg::LoRaIrqFlags);
    uint8_t mode = read_register(reg::OpMode);
    uint8_t flags_after = read_register(reg::LoRaIrqFlags);
    uint8_t version_after = read_register(reg::Version);
    if (version_before != 0x12U) {
        return true;
    }
    if (version_after != 0x12U) {
        return true;
    }
    if (mode != lora_tx_standby_mode_) {
        return true;
    }
    if (flags_before != bit::LoRaTxDone) {
        return true;
    }
    if (flags_after != flags_before) {
        return true;
    }
    output->tx_done = io_.dio0_high();
    return true;
}

bool Sx1278Driver::prepare_rx(uint32_t* frf_readback) {
    lora_tx_pending_ = false;
    if (!set_frf_word(reg::NominalFrfWord, frf_readback)) {
        return false;
    }
    if (*frf_readback != reg::NominalFrfWord) {
        return false;
    }
    if (bank_ == RadioBank::LoRa) {
        write_register(reg::LoRaIrqFlags, 0xFFU);
        uint8_t actual = 0U;
        bool mapping_ok = write_checked(
            reg::DioMapping1,
            bit::LoRaDio0RxDone,
            bit::Dio0Mask,
            bit::LoRaDio0RxDone,
            &actual
        );
        if (!mapping_ok) {
            return false;
        }
        uint8_t receive_base = read_register(reg::LoRaFifoRxBase);
        write_register(reg::LoRaFifoAddrPtr, receive_base);
        return set_mode(bit::RxContinuous);
    }
    write_register(reg::FskIrqFlags2, bit::FskFifoOverrun);
    return set_mode(bit::RxContinuous);
}

bool Sx1278Driver::terminal_irq_asserted() const {
    return io_.dio0_high();
}

bool Sx1278Driver::poll_irq(IrqSnapshot* output) {
    if (output == 0) {
        return false;
    }
    IrqSnapshot empty = {};
    *output = empty;
    if (bank_ == RadioBank::Unknown) {
        return false;
    }

    if (bank_ == RadioBank::LoRa) {
        if (lora_tx_pending_) {
            return poll_lora_tx_done(output);
        }
        uint8_t flags = read_register(reg::LoRaIrqFlags);
        uint8_t tx_flag = flags;
        tx_flag &= bit::LoRaTxDone;
        output->tx_done = tx_flag != 0U;
        uint8_t rx_flag = flags;
        rx_flag &= bit::LoRaRxDone;
        output->rx_done = rx_flag != 0U;
        if (!output->rx_done) {
            return true;
        }
        uint8_t crc_flag = flags;
        crc_flag &= bit::LoRaPayloadCrcError;
        output->phy_crc_ok = crc_flag == 0U;
        output->received_length = read_register(reg::LoRaRxNbBytes);
        output->metrics_flags = 0x03U;
        output->rssi_raw = read_register(reg::LoRaPktRssi);
        uint8_t encoded_snr = read_register(reg::LoRaPktSnr);
        if (encoded_snr <= 127U) {
            output->snr_raw = static_cast<int8_t>(encoded_snr);
        } else {
            int16_t signed_snr = static_cast<int16_t>(encoded_snr);
            signed_snr -= 256;
            output->snr_raw = static_cast<int8_t>(signed_snr);
        }
        return true;
    }

    uint8_t flags = read_register(reg::FskIrqFlags2);
    uint8_t tx_flag = flags;
    tx_flag &= bit::FskPacketSent;
    output->tx_done = tx_flag != 0U;
    uint8_t rx_flag = flags;
    rx_flag &= bit::FskPayloadReady;
    output->rx_done = rx_flag != 0U;
    if (!output->rx_done) {
        return true;
    }
    uint8_t crc_flag = flags;
    crc_flag &= bit::FskCrcOk;
    output->phy_crc_ok = crc_flag != 0U;
    output->received_length = read_register(reg::FskPayloadLength);
    output->metrics_flags = 0x01U;
    output->rssi_raw = read_register(reg::FskRssi);
    output->snr_raw = 0;
    return true;
}

bool Sx1278Driver::read_rx_fifo(uint8_t* frame, uint8_t count) {
    if (count > 64U) {
        return false;
    }
    if (bank_ == RadioBank::Unknown) {
        return false;
    }
    if (count == 0U) {
        return true;
    }
    if (frame == 0) {
        return false;
    }
    if (bank_ == RadioBank::LoRa) {
        uint8_t current_address = read_register(reg::LoRaFifoRxCurrent);
        write_register(reg::LoRaFifoAddrPtr, current_address);
    }
    io_.begin_transaction();
    io_.exchange(reg::Fifo);
    for (uint8_t index = 0U; index < count; ++index) {
        frame[index] = io_.exchange(0U);
    }
    io_.end_transaction();
    return true;
}

bool Sx1278Driver::finish_terminal() {
    lora_tx_pending_ = false;
    if (bank_ == RadioBank::Unknown) {
        return false;
    }
    if (bank_ == RadioBank::LoRa) {
        write_register(reg::LoRaIrqFlags, 0xFFU);
    } else {
        write_register(reg::FskIrqFlags2, bit::FskFifoOverrun);
    }
    return standby();
}

}  // namespace sx1278
