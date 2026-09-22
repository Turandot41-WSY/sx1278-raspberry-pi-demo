"""Verify the local build uses production drivers and binds operator settings."""

from pathlib import Path

from firmware.tools.build_single_endpoint import stage_endpoint

ROOT = Path(__file__).resolve().parents[2]


def test_local_build_reuses_driver_sources_and_binds_clock(tmp_path):
    """Verify that local build reuses driver sources and binds clock.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_local_build_reuses_driver_sources_and_binds_clock
        +-- config.write_bytes
        +-- <BinOp expression>.read_bytes
        +-- stage_endpoint
        +-- Path
        +-- <BinOp expression>.read_text
        +-- config.write_text
        +-- config.read_text
        `-- config.read_text(...).replace
    """
    config = tmp_path / "endpoint.toml"
    config.write_bytes((ROOT / "config/internal/transmit_endpoint.toml").read_bytes())
    build = tmp_path / "build"
    first = stage_endpoint(config, build)
    staged = Path(first["sketch"])
    for relative in ("endpoint.ino", "src/sx1278_driver.cpp", "src/radio_tx_state_machine.cpp",
                     "src/experiment_controller.cpp", "src/arduino_radio_io.cpp"):
        assert (staged / relative).read_bytes() == (ROOT / "firmware/endpoint" / relative).read_bytes()
    assert first["compiled"] is False
    header = (staged / "src/generated/endpoint_config.h").read_text()
    assert "PROGMEM" in header and "memcpy_P" in header
    config.write_text(config.read_text().replace("spi_hz = 100000", "spi_hz = 200000"))
    second = stage_endpoint(config, build)
    assert second["board_sha256"] != first["board_sha256"]
    assert second["firmware_sha256"] != first["firmware_sha256"]
