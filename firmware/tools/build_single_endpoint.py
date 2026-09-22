"""Build the production endpoint for one operator-configured Nano.

Reads config/internal/transmit_endpoint.toml and copies production sources into an isolated
build directory. Only generated configuration/identity headers differ. No probe
sketch or alternate radio implementation is compiled. This tool never uploads.

Call tree:
main() - build the configured production firmware
+-- stage_endpoint() - preserve drivers and generate local board configuration
|   `-- generate_build_identity() - hash staged source and build settings
+-- subprocess.run() - invoke Arduino CLI and avr-size
`-- enforce_limits() - require the existing Flash/SRAM budget
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from firmware.tools.generate_build_identity import generate_build_identity
from firmware.tools.check_avr_size import parse_avr_size, enforce_limits

CLI = "/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"


def stage_endpoint(config_path: Path, build: Path) -> dict:
    """Stage the production source with one explicit local endpoint configuration.

    Processing flow:
        Validate local record -> copy production endpoint -> render local pin header
        -> hash configuration and sources -> write build manifest.

    Direct call tree (static source order):
        stage_endpoint
        +-- config_path.read_bytes
        +-- tomllib.loads
        +-- config_bytes.decode
        +-- ValueError
        +-- range
        +-- len
        +-- build.mkdir
        +-- endpoint.exists
        +-- shutil.rmtree
        +-- shutil.copytree
        +-- hashlib.sha256
        +-- hashlib.sha256(...).digest
        +-- octets.append
        +-- <str literal>.join
        +-- header.replace
        +-- str
        +-- header.replace(...).replace
        +-- header.replace(...).replace(...).replace
        +-- <BinOp expression>.write_text
        +-- hashlib.sha256(...).hexdigest
        +-- json.dumps
        +-- generate_build_identity
        +-- board_hash.hex
        +-- identity.hex
        +-- config_path.resolve
        `-- endpoint.resolve
    """
    config_bytes = config_path.read_bytes()
    config = tomllib.loads(config_bytes.decode())
    if not 1 <= config["endpoint_id"] <= 0xFFFFFFFF:
        raise ValueError("endpoint_id must be a nonzero uint32")
    nss, reset, dio = config["nss_pin"], config["reset_pin"], config["dio0_pin"]
    for pin in (nss, reset):
        if pin not in range(2, 20):
            raise ValueError("invalid Nano pin map")
    if dio not in (2, 3):
        raise ValueError("DIO0 must use D2 or D3")
    for pin in (nss, reset):
        if pin in (11, 12, 13):
            raise ValueError("pin map conflicts with hardware SPI")
    if len({nss, reset, dio}) != 3:
        raise ValueError("pin map uses the same signal twice")
    if not 1 <= config["spi_hz"] <= 8000000:
        raise ValueError("SPI clock must be between 1 Hz and 8 MHz")
    if config["fqbn"] not in ("arduino:avr:nano:cpu=atmega328old", "arduino:avr:nano:cpu=atmega328"):
        raise ValueError("single endpoint builder requires an ATmega328P Nano")
    build.mkdir(parents=True, exist_ok=True)
    stage = build / "source"
    endpoint = stage / "endpoint"
    if endpoint.exists():
        shutil.rmtree(endpoint)
    shutil.copytree(ROOT / "firmware/endpoint", endpoint)
    board_hash = hashlib.sha256(config_bytes).digest()
    octets = []
    for byte in board_hash:
        octets.append(f"0x{byte:02X}U")
    initializer = ", ".join(octets)
    # The local header implements the same configuration interface. Paired review
    # files and their review gates remain owned by the campaign build generator.
    header = '''#ifndef SX1278_GENERATED_ENDPOINT_CONFIG_H
#define SX1278_GENERATED_ENDPOINT_CONFIG_H
#include <stdint.h>
#include <string.h>
#ifdef __AVR__
#include <avr/pgmspace.h>
#else
#define PROGMEM
#endif
namespace sx1278 { namespace generated {
struct EndpointConfig {
  uint8_t role; uint32_t endpoint_id;
  uint8_t nss_pin; uint8_t reset_pin; uint8_t dio0_pin;
  uint8_t board_sha256[32]; uint8_t pin_map_sha256[32];
};
static const EndpointConfig kLocalEndpointConfig PROGMEM = {
  0U, ENDPOINT_IDUL, NSSU, RESETU, DIOU, {HASH_BYTES}, {HASH_BYTES}
};
/** Load the local operator record; no paired qualification is asserted.
 * Processing flow: validate role/output -> populate pins and identity -> ready.
 */
inline bool read_endpoint_config(uint8_t role, EndpointConfig* output) {
  if (role != 0U) { return false; }
  if (output == 0) { return false; }
#ifdef __AVR__
  memcpy_P(output, &kLocalEndpointConfig, sizeof(EndpointConfig));
#else
  *output = kLocalEndpointConfig;
#endif
  return true;
}
} }
#endif
'''
    header = header.replace("ENDPOINT_ID", str(config["endpoint_id"]))
    header = header.replace("NSS", str(nss)).replace("RESET", str(reset)).replace("DIO", str(dio))
    header = header.replace("HASH_BYTES", initializer)
    generated = endpoint / "src/generated"
    (generated / "endpoint_config.h").write_text(header)
    # Include the exact compile settings in source identity, so a clock or FQBN
    # change produces a different HELLO firmware hash even with identical drivers.
    settings_header = "// Build configuration identity (operator selected):\n"
    settings_header += "// Raw configuration SHA-256: " + hashlib.sha256(config_bytes).hexdigest() + "\n"
    settings_header += "// " + json.dumps(config, ensure_ascii=True, sort_keys=True) + "\n"
    (generated / "single_build_settings.h").write_text(settings_header)
    identity = generate_build_identity(stage, generated / "build_identity.h")
    manifest = {
        "schema": "sas2027-single-endpoint-v1", "endpoint_id": config["endpoint_id"],
        "board_sha256": board_hash.hex(), "firmware_sha256": identity.hex(),
        "configuration": config, "configuration_path": str(config_path.resolve()),
        "sketch": str(endpoint.resolve()), "compiled": False,
    }
    (build / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(arguments=None) -> int:
    """Compile the single endpoint from production sources and record artifact identity.

    Processing flow:
        Read arguments -> verify shared generated tables -> stage local configuration
        -> Arduino compile -> hash uploaded HEX bytes -> mark manifest compiled.

    Direct call tree (static source order):
        main
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- str
        +-- Path.home
        +-- parser.parse_args
        +-- subprocess.run
        +-- args.build.resolve
        +-- stage_endpoint
        +-- enforce_limits
        +-- parse_avr_size
        +-- hashlib.sha256
        +-- hashlib.sha256(...).hexdigest
        +-- hex_path.read_bytes
        +-- <BinOp expression>.write_text
        +-- json.dumps
        `-- print
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/internal/transmit_endpoint.toml")
    parser.add_argument("--build", type=Path, default=ROOT / "firmware/build/single-endpoint")
    parser.add_argument("--arduino-cli", default=CLI)
    parser.add_argument("--avr-size", default=str(Path.home() / "Library/Arduino15/packages/arduino/tools/avr-gcc/7.3.0-atmel3.6.1-arduino7/bin/avr-size"))
    args = parser.parse_args(arguments)
    subprocess.run([sys.executable, str(ROOT / "firmware/tools/generate_firmware_tables.py"), "--check"], cwd=ROOT, check=True)
    build = args.build.resolve()
    manifest = stage_endpoint(args.config, build)
    config = manifest["configuration"]
    flags = f'-DSX1278_ENDPOINT_ROLE=0 -DSERIAL_RX_BUFFER_SIZE=128 -DSX1278_SPI_HZ={config["spi_hz"]}UL'
    artifacts = build / "artifacts"
    subprocess.run([args.arduino_cli, "compile", "--fqbn", config["fqbn"],
                    "--build-property", "compiler.cpp.extra_flags=" + flags,
                    "--build-property", "compiler.c.elf.extra_flags=-Wl,-Map," + str(artifacts / "endpoint.map"),
                    "--build-path", str(artifacts), manifest["sketch"]], check=True)
    measurement = subprocess.run([args.avr_size, "-C", "--mcu=atmega328p",
                                  str(artifacts / "endpoint.ino.elf")],
                                 check=True, capture_output=True, text=True)
    usage = enforce_limits(parse_avr_size(measurement.stdout))
    manifest["flash_bytes"] = usage.flash_bytes
    manifest["static_ram_bytes"] = usage.static_ram_bytes
    hex_path = artifacts / "endpoint.ino.hex"
    manifest["hex_sha256"] = hashlib.sha256(hex_path.read_bytes()).hexdigest()
    manifest["compiled"] = True
    (build / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Production firmware compiled: {hex_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
