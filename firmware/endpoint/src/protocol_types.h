#ifndef SX1278_PROTOCOL_TYPES_H
#define SX1278_PROTOCOL_TYPES_H

#include <stddef.h>
#include <stdint.h>

#include "generated/protocol_constants.h"

namespace sx1278 {

static const uint16_t kMagic = generated::kProtocolMagic;
static const uint8_t kVersion = generated::kProtocolVersion;
static const size_t kHeaderSize = 8U;
static const size_t kCrcSize = 2U;
static const size_t kMaxPayload = generated::kMaxPayload;
static const size_t kMaxDecoded = generated::kMaxDecoded;
static const size_t kMaxCobsFragment = generated::kMaxCobsFragment;
static const size_t kMaxWire = generated::kMaxWire;
static const uint32_t kInterbyteTimeoutMs = generated::kInterByteTimeoutMs;
static const uint8_t kFrameLength = 64U;

enum class MessageType : uint8_t {
    Hello = generated::kMessageHello,
    ResetToStandby = generated::kMessageResetToStandby,
    ApplyProfile = generated::kMessageApplyProfile,
    SetPa = generated::kMessageSetPa,
    LoadTx = generated::kMessageLoadTx,
    ArmRx = generated::kMessageArmRx,
    StartTx = generated::kMessageStartTx,
    CancelAttempt = generated::kMessageCancelAttempt,
    GetAttemptStatus = generated::kMessageGetAttemptStatus,
    Ack = generated::kMessageAck,
    HelloReport = generated::kMessageHelloReport,
    ConfigReport = generated::kMessageConfigReport,
    TxReady = generated::kMessageTxReady,
    RxArmed = generated::kMessageRxArmed,
    TxStarted = generated::kMessageTxStarted,
    TxDone = generated::kMessageTxDone,
    RxPacket = generated::kMessageRxPacket,
    RxTimeout = generated::kMessageRxTimeout,
    AttemptStatus = generated::kMessageAttemptStatus,
    EndpointError = generated::kMessageEndpointError
};

enum class AttemptState : uint8_t {
    Standby = generated::kStateStandby,
    TxLoaded = generated::kStateTxLoaded,
    RxArmed = generated::kStateRxArmed,
    TxStarted = generated::kStateTxStarted,
    TxDone = generated::kStateTxDone,
    RxPacket = generated::kStateRxPacket,
    RxTimeout = generated::kStateRxTimeout,
    Error = generated::kStateError
};

enum class ErrorCode : uint16_t {
    None = 0U,
    BadCobs = generated::kErrorBadCobs,
    BadMagic = generated::kErrorBadMagic,
    BadVersion = generated::kErrorBadVersion,
    BadLength = generated::kErrorBadLength,
    BadCrc = generated::kErrorBadCrc,
    UnknownType = generated::kErrorUnknownType,
    BadState = generated::kErrorBadState,
    ContextMismatch = generated::kErrorContextMismatch,
    FrameLength = generated::kErrorFrameLength,
    Profile = generated::kErrorProfile,
    Pa = generated::kErrorPa,
    RegisterReadback = generated::kErrorRegisterReadback,
    FrfReadback = generated::kErrorFrfReadback,
    DeviceRadioTimeout = generated::kErrorDeviceRadioTimeout,
    SerialOverflow = generated::kErrorSerialOverflow,
    EndpointReset = generated::kErrorEndpointReset
};

struct AttemptKey {
    uint32_t run_token;
    uint32_t attempt_index;
};

struct MessageView {
    MessageType type;
    uint16_t sequence;
    uint16_t payload_length;
    uint16_t decoded_crc;
    const uint8_t* payload;
};

/** Return whether a byte is any frozen protocol-v1 message code.
 *
 * References:
 * - conformance/serial_protocol_v1.json, message_types map.
 *
 * Processing flow:
 *   type byte -> explicit twenty-code switch -> known or unknown result
 */
inline bool is_known_message_type_code(uint8_t value) {
    switch (value) {
        case generated::kMessageHello:
        case generated::kMessageResetToStandby:
        case generated::kMessageApplyProfile:
        case generated::kMessageSetPa:
        case generated::kMessageLoadTx:
        case generated::kMessageArmRx:
        case generated::kMessageStartTx:
        case generated::kMessageCancelAttempt:
        case generated::kMessageGetAttemptStatus:
        case generated::kMessageAck:
        case generated::kMessageHelloReport:
        case generated::kMessageConfigReport:
        case generated::kMessageTxReady:
        case generated::kMessageRxArmed:
        case generated::kMessageTxStarted:
        case generated::kMessageTxDone:
        case generated::kMessageRxPacket:
        case generated::kMessageRxTimeout:
        case generated::kMessageAttemptStatus:
        case generated::kMessageEndpointError:
            return true;
        default:
            return false;
    }
}

/** Return whether a byte is one of the nine host-to-endpoint command codes.
 *
 *
 * Processing flow:
 *   type byte -> explicit command cases -> command or non-command result
 */
inline bool is_command_type_code(uint8_t value) {
    switch (value) {
        case generated::kMessageHello:
        case generated::kMessageResetToStandby:
        case generated::kMessageApplyProfile:
        case generated::kMessageSetPa:
        case generated::kMessageLoadTx:
        case generated::kMessageArmRx:
        case generated::kMessageStartTx:
        case generated::kMessageCancelAttempt:
        case generated::kMessageGetAttemptStatus:
            return true;
        default:
            return false;
    }
}

/** Return whether a byte is one of the eleven endpoint event codes.
 *
 *
 * Processing flow:
 *   type byte -> explicit event cases -> event or non-event result
 */
inline bool is_event_type_code(uint8_t value) {
    switch (value) {
        case generated::kMessageAck:
        case generated::kMessageHelloReport:
        case generated::kMessageConfigReport:
        case generated::kMessageTxReady:
        case generated::kMessageRxArmed:
        case generated::kMessageTxStarted:
        case generated::kMessageTxDone:
        case generated::kMessageRxPacket:
        case generated::kMessageRxTimeout:
        case generated::kMessageAttemptStatus:
        case generated::kMessageEndpointError:
            return true;
        default:
            return false;
    }
}

/** Return whether an attempt state fits the frozen contiguous state map.
 *
 * References:
 * - conformance/serial_protocol_v1.json, attempt_states map.
 */
inline bool is_valid_attempt_state(AttemptState value) {
    uint8_t encoded = static_cast<uint8_t>(value);
    return encoded <= generated::kStateError;
}

/** Return whether an error value is in the frozen protocol range.
 *
 * References:
 * - conformance/serial_protocol_v1.json, error_codes map.
 */
inline bool is_valid_error_code(ErrorCode value, bool allow_none) {
    uint16_t encoded = static_cast<uint16_t>(value);
    if (encoded == 0U) {
        return allow_none;
    }
    return encoded <= generated::kErrorEndpointReset;
}

/** Return whether a command attempt key has a nonzero run token.
 *
 */
inline bool is_valid_attempt_key(const AttemptKey& key) {
    return key.run_token != 0UL;
}

/** Compare both fields of two attempt keys without truncation.
 *
 *
 * Processing flow:
 *   run tokens -> reject mismatch -> attempt indices -> equality result
 */
inline bool same_attempt(const AttemptKey& first, const AttemptKey& second) {
    if (first.run_token != second.run_token) {
        return false;
    }
    return first.attempt_index == second.attempt_index;
}

/** Return whether both fields form the unique no-attempt sentinel pair.
 *
 * References:
 * - conformance/serial_protocol_v1.json, context object.
 */
inline bool attempt_has_no_context(const AttemptKey& key) {
    return generated::is_no_attempt_context(key.run_token, key.attempt_index);
}

}  // namespace sx1278

#endif
