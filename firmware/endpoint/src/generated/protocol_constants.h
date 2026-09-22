#ifndef SX1278_GENERATED_PROTOCOL_CONSTANTS_H
#define SX1278_GENERATED_PROTOCOL_CONSTANTS_H
#include <stddef.h>
#include <stdint.h>
namespace sx1278 {
namespace generated {
static const uint16_t kProtocolMagic = 21336U;
static const uint8_t kProtocolVersion = 1U;
static const uint32_t kNoAttemptRunToken = 4294967295UL;
static const uint32_t kNoAttemptIndex = 4294967295UL;
static const size_t kErrorContextHeaderBytesRequired = 8U;
static const uint16_t kUnavailableMsgSeqPlaceholder = 0U;
static const uint8_t kUnavailableRelatedTypePlaceholder = 0U;
static const uint8_t kMessageAck = 0x80U;
static const uint8_t kMessageApplyProfile = 0x10U;
static const uint8_t kMessageArmRx = 0x21U;
static const uint8_t kMessageAttemptStatus = 0xA6U;
static const uint8_t kMessageCancelAttempt = 0x23U;
static const uint8_t kMessageConfigReport = 0x90U;
static const uint8_t kMessageEndpointError = 0xE0U;
static const uint8_t kMessageGetAttemptStatus = 0x24U;
static const uint8_t kMessageHello = 0x01U;
static const uint8_t kMessageHelloReport = 0x81U;
static const uint8_t kMessageLoadTx = 0x20U;
static const uint8_t kMessageResetToStandby = 0x02U;
static const uint8_t kMessageRxArmed = 0xA1U;
static const uint8_t kMessageRxPacket = 0xA4U;
static const uint8_t kMessageRxTimeout = 0xA5U;
static const uint8_t kMessageSetPa = 0x11U;
static const uint8_t kMessageStartTx = 0x22U;
static const uint8_t kMessageTxDone = 0xA3U;
static const uint8_t kMessageTxReady = 0xA0U;
static const uint8_t kMessageTxStarted = 0xA2U;
static const uint8_t kStateError = 7U;
static const uint8_t kStateRxArmed = 2U;
static const uint8_t kStateRxPacket = 5U;
static const uint8_t kStateRxTimeout = 6U;
static const uint8_t kStateStandby = 0U;
static const uint8_t kStateTxDone = 4U;
static const uint8_t kStateTxLoaded = 1U;
static const uint8_t kStateTxStarted = 3U;
static const uint8_t kProfileFsk = 1U;
static const uint8_t kProfileGfsk = 2U;
static const uint8_t kProfileGmsk = 4U;
static const uint8_t kProfileLoRa = 0U;
static const uint8_t kProfileMsk = 3U;
static const uint8_t kProfileOok = 5U;
static const uint16_t kErrorBadCobs = 1U;
static const uint16_t kErrorBadCrc = 5U;
static const uint16_t kErrorBadLength = 4U;
static const uint16_t kErrorBadMagic = 2U;
static const uint16_t kErrorBadState = 7U;
static const uint16_t kErrorBadVersion = 3U;
static const uint16_t kErrorContextMismatch = 8U;
static const uint16_t kErrorDeviceRadioTimeout = 14U;
static const uint16_t kErrorEndpointReset = 16U;
static const uint16_t kErrorFrameLength = 9U;
static const uint16_t kErrorFrfReadback = 13U;
static const uint16_t kErrorPa = 11U;
static const uint16_t kErrorProfile = 10U;
static const uint16_t kErrorRegisterReadback = 12U;
static const uint16_t kErrorSerialOverflow = 15U;
static const uint16_t kErrorUnknownType = 6U;
static const size_t kMaxPayload = 118U;
static const size_t kMaxDecoded = 128U;
static const size_t kMaxCobsFragment = 129U;
static const size_t kMaxWire = 130U;
static const uint16_t kInterByteTimeoutMs = 250U;
static const uint32_t kUartBaud = 115200UL;
/**
 * Return true only for the frozen no-attempt context pair.
 *
 * References:
 *   conformance/serial_protocol_v1.json, serial-conformance-v1
 *   context object.
 *
 * Processing flow:
 *   run token -> run sentinel check -> index sentinel check -> result
 */
inline bool is_no_attempt_context(
    uint32_t run_token,
    uint32_t attempt_index
) {
    if (run_token != kNoAttemptRunToken) {
        return false;
    }
    if (attempt_index != kNoAttemptIndex) {
        return false;
    }
    return true;
}
}
}
#endif
