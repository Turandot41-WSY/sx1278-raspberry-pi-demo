#ifndef SX1278_REGISTERS_H
#define SX1278_REGISTERS_H

#include <stdint.h>

namespace sx1278 {
namespace reg {

// Register addresses come from Semtech SX1276/77/78/79 Datasheet Rev. 7,
// Table 41 and sections 4.2/4.4, pp. 92-115.
static const uint8_t Fifo = 0x00U;
static const uint8_t OpMode = 0x01U;
static const uint8_t FrfMsb = 0x06U;
static const uint8_t FrfMid = 0x07U;
static const uint8_t FrfLsb = 0x08U;
static const uint8_t PaConfig = 0x09U;
static const uint8_t Ocp = 0x0BU;
static const uint8_t LoRaFifoAddrPtr = 0x0DU;
static const uint8_t LoRaFifoTxBase = 0x0EU;
static const uint8_t LoRaFifoRxBase = 0x0FU;
static const uint8_t LoRaFifoRxCurrent = 0x10U;
static const uint8_t LoRaIrqFlags = 0x12U;
static const uint8_t LoRaRxNbBytes = 0x13U;
static const uint8_t LoRaPktSnr = 0x19U;
static const uint8_t LoRaPktRssi = 0x1AU;
static const uint8_t FskRssi = 0x24U;
static const uint8_t FskPayloadLength = 0x32U;
static const uint8_t FskIrqFlags1 = 0x3EU;
static const uint8_t FskIrqFlags2 = 0x3FU;
static const uint8_t DioMapping1 = 0x40U;
static const uint8_t Version = 0x42U;
static const uint8_t PaDac = 0x4DU;

// Project choice: use 437.5 MHz as the common nominal carrier. 0x6D6000 uses
// Semtech Rev. 7 section 3.3.3, p. 82, FSTEP = 32 MHz / 2^19.
static const uint32_t NominalFrfWord = 0x006D6000UL;

}  // namespace reg

namespace bit {

// SPI address bits follow Semtech Rev. 7 section 2.2, p. 80.
static const uint8_t SpiWrite = 0x80U;
static const uint8_t Address = 0x7FU;

// RegOpMode fields follow Semtech Rev. 7 sections 4.2 and 4.4, pp. 93 and
// 108. LongRangeMode may change only while Mode is Sleep.
static const uint8_t LongRange = 0x80U;
static const uint8_t ModeMask = 0x07U;
static const uint8_t ModeKeepMask = 0xF8U;
static const uint8_t Sleep = 0x00U;
static const uint8_t Standby = 0x01U;
static const uint8_t FsTx = 0x02U;
static const uint8_t Tx = 0x03U;
static const uint8_t RxContinuous = 0x05U;
static const uint8_t RxSingle = 0x06U;

// LoRa IRQ bits follow Semtech Rev. 7 section 4.4 RegIrqFlags (0x12),
// pp. 110-111. Each LoRa flag is cleared by writing one to that bit.
static const uint8_t LoRaTxDone = 0x08U;
static const uint8_t LoRaPayloadCrcError = 0x20U;
static const uint8_t LoRaRxDone = 0x40U;

// FSK/OOK status bits follow Semtech Rev. 7 section 4.2 RegIrqFlags2
// (0x3F), p. 104. These three bits clear by state/FIFO changes, so this
// driver never applies the LoRa write-0xFF rule to the FSK/OOK bank.
static const uint8_t FskPacketSent = 0x08U;
static const uint8_t FskPayloadReady = 0x04U;
static const uint8_t FskCrcOk = 0x02U;
static const uint8_t FskFifoOverrun = 0x10U;

// DIO0 mappings follow Semtech Rev. 7 Table 18 (p. 46): mapping 01 selects
// LoRa TxDone and mapping 00 selects LoRa RxDone. FSK/OOK packet mode uses
// mapping 00 for PayloadReady in RX and PacketSent in TX (Table 30, p. 69).
static const uint8_t Dio0Mask = 0xC0U;
static const uint8_t LoRaDio0RxDone = 0x00U;
static const uint8_t LoRaDio0TxDone = 0x40U;

}  // namespace bit
}  // namespace sx1278

#endif
