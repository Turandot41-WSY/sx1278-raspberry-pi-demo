#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wpedantic"
#pragma GCC diagnostic ignored "-Wshadow"
#pragma GCC diagnostic ignored "-Wsign-conversion"
#include <Arduino.h>
#pragma GCC diagnostic pop

#include "src/arduino_radio_io.h"
#include "src/boot_counter.h"
#include "src/command_parser.h"
#include "src/event_reporter.h"
#include "src/experiment_controller.h"
#include "src/generated/build_identity.h"
#include "src/generated/endpoint_config.h"
#include "src/generated/protocol_constants.h"
#include "src/profile_manager.h"
#include "src/radio_rx_state_machine.h"
#include "src/radio_tx_state_machine.h"
#include "src/sx1278_driver.h"

#ifndef SX1278_ENDPOINT_ROLE
#error SX1278_ENDPOINT_ROLE must select reviewed endpoint A=0 or B=1
#endif

static_assert(SERIAL_RX_BUFFER_SIZE >= 128, "Serial RX ring must hold one decoded envelope");

class ArduinoSerialSink : public sx1278::ByteSink {
public:
    /** Write one complete binary protocol message to USB serial.
     *
     * bytes and size describe the already encoded message. The return value is
     * true only when Serial.write accepts every byte; partial output is not
     * retried by this sink.
     *
     * Processing flow:
     *   Encoded message span -> Serial.write -> accepted-count comparison
     */
    bool write_bytes(const uint8_t* bytes, size_t size) override {
        size_t written = Serial.write(bytes, size);
        return written == size;
    }
};

sx1278::ArduinoRadioIo radio_io;
sx1278::Sx1278Driver radio(radio_io);
sx1278::ProfileManager profiles(radio);
sx1278::RadioTxStateMachine tx_machine(radio);
sx1278::RadioRxStateMachine rx_machine(radio);
ArduinoSerialSink serial_sink;
sx1278::EventReporter events(serial_sink);
sx1278::ArduinoEeprom eeprom;
sx1278::BootCounter boot_counter(eeprom);
sx1278::CommandParser parser;
uint8_t firmware_identity[32] = {0U};
uint8_t board_identity[32] = {0U};
sx1278::EndpointIdentity identity = {
    0UL,
    0UL,
    0U,
    false,
    firmware_identity,
    board_identity
};
sx1278::ExperimentController controller(
    profiles,
    tx_machine,
    rx_machine,
    events,
    identity
);

/** Copy generated flash identities into the controller's fixed RAM buffers.
 *
 * endpoint supplies the reviewed board hash only when endpoint_ready is true.
 * Successful flash reads populate firmware_identity; the fixed buffers retain
 * their existing bytes when a corresponding source is unavailable.
 *
 * Processing flow:
 *   32 indices -> firmware flash byte -> optional reviewed board byte -> buffers
 */
void load_identity_bytes(
    const sx1278::generated::EndpointConfig& endpoint,
    bool endpoint_ready
) {
    for (uint8_t index = 0U; index < 32U; ++index) {
        uint8_t firmware_byte = 0U;
        bool read_ok = sx1278::generated::read_build_identity_byte(
            index,
            &firmware_byte
        );
        if (read_ok) {
            firmware_identity[index] = firmware_byte;
        }
        if (endpoint_ready) {
            uint8_t board_byte = endpoint.board_sha256[index];
            board_identity[index] = board_byte;
        }
    }
}

/** Process one parser event without performing hidden retransmission.
 *
 * event selects decoded command dispatch or parser-error reporting; now_ms is
 * the current Arduino millisecond count used by any accepted radio action.
 * A None event does nothing, and this wrapper does not return delivery status.
 *
 * Processing flow:
 *   no-event/message/error -> controller command or structured error response
 */
void process_parse_event(const sx1278::ParseEvent& event, uint32_t now_ms) {
    if (event.kind == sx1278::ParseKind::MessageReady) {
        controller.handle(parser.message(), now_ms);
        return;
    }
    if (event.kind == sx1278::ParseKind::Error) {
        controller.report_parse_error(event);
    }
}

/** Initialize serial and endpoint identity before enabling the reviewed radio.
 *
 * Arduino calls this entry point once after boot. Generated role and identity
 * data select the endpoint configuration; EEPROM supplies the next boot count.
 * Configuration, pin validation or SPI failure leaves radio_ready false.
 * A completed probe stores the observed version and its acceptance result.
 *
 * Processing flow:
 *   UART/boot count -> endpoint review gate -> pin/SPI setup -> SX1278 probe
 *
 * Call tree:
 *   setup()
 *   +-- Serial.begin(kUartBaud)
 *   +-- boot_counter.increment() -> persistent boot count
 *   +-- profiles.invalidate_configuration()
 *   +-- generated::read_endpoint_config(role, &endpoint)
 *   +-- load_identity_bytes(endpoint, config_loaded)
 *   +-- [configuration loaded] radio_io.configure(nss, reset, dio0)
 *   +-- [pins accepted] radio_io.begin()
 *   `-- [SPI initialized] radio.reset_and_probe(&version)
 */
void setup() {
    Serial.begin(sx1278::generated::kUartBaud);
    identity.boot_count = boot_counter.increment();
    profiles.invalidate_configuration();

    sx1278::generated::EndpointConfig endpoint = {};
    uint8_t role = static_cast<uint8_t>(SX1278_ENDPOINT_ROLE);
    bool config_loaded = sx1278::generated::read_endpoint_config(role, &endpoint);
    load_identity_bytes(endpoint, config_loaded);
    if (!config_loaded) {
        identity.radio_ready = false;
        return;
    }
    identity.endpoint_id = endpoint.endpoint_id;
    bool pins_ready = radio_io.configure(
        endpoint.nss_pin,
        endpoint.reset_pin,
        endpoint.dio0_pin
    );
    if (!pins_ready) {
        identity.radio_ready = false;
        return;
    }
    bool io_ready = radio_io.begin();
    if (!io_ready) {
        identity.radio_ready = false;
        return;
    }
    uint8_t version = 0U;
    bool probe_ok = radio.reset_and_probe(&version);
    identity.reg_version = version;
    identity.radio_ready = probe_ok;
}

/** Service UART parsing and radio deadlines without blocking the Nano loop.
 *
 * Arduino repeatedly calls this entry point. Available UART bytes and the
 * current millisecond count drive command parsing; controller.tick services
 * the active RF attempt and any pending terminal report. Incoming command and
 * error events produce serial replies through process_parse_event.
 *
 * Processing flow:
 *   timeout poll -> available serial bytes -> controller radio tick
 *
 * Call tree:
 *   loop()
 *   +-- millis() -> current parser timestamp
 *   +-- parser.poll_timeout(now_ms)
 *   +-- process_parse_event(timeout_event, now_ms)
 *   +-- [while Serial.available() > 0]
 *   |   +-- Serial.read() -> stop draining if no byte remains
 *   |   +-- millis() -> received-byte timestamp
 *   |   +-- parser.push(received_byte, now_ms)
 *   |   `-- process_parse_event(event, now_ms)
 *   `-- controller.tick(millis())
 */
void loop() {
    uint32_t now_ms = millis();
    sx1278::ParseEvent timeout_event = parser.poll_timeout(now_ms);
    process_parse_event(timeout_event, now_ms);

    while (Serial.available() > 0) {
        int received = Serial.read();
        if (received < 0) {
            break;
        }
        uint8_t received_byte = static_cast<uint8_t>(received);
        now_ms = millis();
        sx1278::ParseEvent event = parser.push(received_byte, now_ms);
        process_parse_event(event, now_ms);
    }
    controller.tick(millis());
}
