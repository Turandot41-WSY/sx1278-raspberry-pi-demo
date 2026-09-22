"""Generate bounded AVR headers from the single reviewed profile truth.

Configuration: config/internal/firmware_tables.toml
Function call tree (main task paths; branch labels indicate execution conditions):
main() -> host.common.runtime_config.parse_configured_args() Read firmware_tables.toml
`-- generate_tables()                        Generate configuration tables for the firmware
    +-- host.radio.profile_truth.load_profile_truth() Load profile, PA, and register CSV tables
    +-- load_register_review()                Validate the register review record
    +-- read_endpoints()                      Load endpoint identities and pin definitions
    +-- emit_profile_header()                 Generate modulation settings
    +-- emit_pa_header()                      Generate power settings
    +-- emit_endpoint_header()                Generate endpoint settings
    `-- _write_or_check()                     Write generated files or compare them with existing files
"""

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from host.common.runtime_config import parse_configured_args
from host.radio.profile_truth import (
    PROFILE_ORDER,
    ProfileTruth,
    ProfileTruthError,
    load_profile_truth,
)


ENDPOINT_COLUMNS = (
    "Role",
    "EndpointId",
    "NssPin",
    "ResetPin",
    "Dio0Pin",
    "BoardIdentitySha256",
    "PinMapRecordSha256",
)
PROFILE_CODES = {
    "LoRa": 0,
    "FSK": 1,
    "GFSK": 2,
    "MSK": 3,
    "GMSK": 4,
    "OOK": 5,
}
BANK_CODES = {"LoRa": 1, "FSK": 2}
SEMTECH_REV7_SHA256 = (
    "330745f933df00015d2de3efd582608339350ba3a21001d11b9d449839ce016b"
)
SEMTECH_ERRATA_REV1_SHA256 = (
    "1e78fe3855553edd8f820c36a6c52f5cb983bbe38de017064b873ec2b1d3d322"
)
REVIEW_KEYS = (
    "datasheet",
    "errata",
    "human_approval_status",
    "physical_readback_status",
    "profile_registers_sha256",
    "review_status",
    "reviewed_utc",
    "reviewer",
    "reviewer_kind",
    "schema_version",
)
DATASHEET_KEYS = (
    "revision",
    "sections",
    "source_file_sha256",
    "title",
)
ERRATA_KEYS = (
    "official_source_url",
    "revision",
    "reviewed_artifact_url",
    "sections",
    "source_file_sha256",
    "title",
)


class EndpointTruthError(ValueError):
    """Report a fail-closed endpoint or review-contract violation."""


@dataclass(frozen=True)
class EndpointRecord:
    """Hold one reviewed endpoint row or one entirely blank pending row."""

    role: str
    endpoint_id: int | None
    nss_pin: int | None
    reset_pin: int | None
    dio0_pin: int | None
    board_identity_sha256: str | None
    pin_map_record_sha256: str | None


@dataclass(frozen=True)
class EndpointTruth:
    """Hold both role rows and whether physical review has completed."""

    records: tuple[EndpointRecord, ...]
    roles: tuple[str, ...]
    production_ready: bool


@dataclass(frozen=True)
class RegisterReview:
    """Hold the verified decision-record gates for generated profile bytes."""

    automated_audit_complete: bool
    human_approval_complete: bool
    physical_readback_complete: bool
    profile_registers_sha256: str


def _parse_decimal(text: str, field: str, minimum: int, maximum: int) -> int:
    """Parse one canonical decimal endpoint field within fixed bounds.

    Processing flow:
        Endpoint field text -> require decimal digits without a leading zero
        -> convert to an integer -> enforce the field minimum and maximum.

    Direct call tree (static source order):
        _parse_decimal
        +-- EndpointTruthError
        +-- len
        +-- text.startswith
        `-- int
    """
    if text == "":
        raise EndpointTruthError(field + " is empty")
    decimal_characters = "0123456789"
    for character in text:
        if character not in decimal_characters:
            raise EndpointTruthError(field + " must be canonical decimal text")
    if len(text) > 1:
        if text.startswith("0"):
            raise EndpointTruthError(field + " must not have a leading zero")
    value = int(text)
    if value < minimum:
        raise EndpointTruthError(field + " is below its minimum")
    if value > maximum:
        raise EndpointTruthError(field + " is above its maximum")
    return value


def _parse_sha256(text: str, field: str) -> str:
    """Parse one lowercase 64-character SHA-256 endpoint identity.

    Processing flow:
        Endpoint identity text -> require exactly 64 lowercase hexadecimal characters
        -> retain the canonical identity; reject a different length or alphabet.

    Direct call tree (static source order):
        _parse_sha256
        +-- len
        `-- EndpointTruthError
    """
    if len(text) != 64:
        raise EndpointTruthError(field + " must contain 64 lowercase hex characters")
    allowed = "0123456789abcdef"
    for character in text:
        if character not in allowed:
            raise EndpointTruthError(field + " must contain lowercase hexadecimal")
    return text


def read_endpoints(path: Path) -> EndpointTruth:
    """Read two physical endpoint rows without inferring missing hardware facts.

    Processing flow:
        exact A/B CSV -> classify all-empty or all-filled hardware fields
                     -> strict range/hash/pin checks -> EndpointTruth

    Direct call tree (static source order):
        read_endpoints
        +-- path.open
        +-- csv.DictReader
        +-- tuple
        +-- EndpointTruthError
        +-- row.get
        +-- rows.append
        +-- len
        +-- hardware_values.append
        +-- EndpointRecord
        +-- records.append
        +-- EndpointTruth
        +-- _parse_decimal
        +-- _parse_sha256
        +-- endpoint_ids.append
        `-- board_hashes.append
    """
    rows: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = reader.fieldnames
            actual_columns: tuple[str, ...] = ()
            if fieldnames is not None:
                actual_columns = tuple(fieldnames)
            if actual_columns != ENDPOINT_COLUMNS:
                raise EndpointTruthError("firmware_endpoints.csv header is not exact")
            for row in reader:
                if None in row:
                    raise EndpointTruthError("firmware_endpoints.csv has extra columns")
                copied: dict[str, str] = {}
                for column in ENDPOINT_COLUMNS:
                    value = row.get(column)
                    if value is None:
                        raise EndpointTruthError("firmware_endpoints.csv has a missing field")
                    copied[column] = value
                rows.append(copied)
    except EndpointTruthError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise EndpointTruthError("cannot read firmware endpoint truth") from error

    if len(rows) != 2:
        raise EndpointTruthError("firmware_endpoints.csv must contain exactly two rows")
    if rows[0]["Role"] != "A":
        raise EndpointTruthError("first endpoint role must be A")
    if rows[1]["Role"] != "B":
        raise EndpointTruthError("second endpoint role must be B")

    records: list[EndpointRecord] = []
    all_rows_are_pending = True
    all_rows_are_reviewed = True
    for row in rows:
        hardware_values: list[str] = []
        for column in ENDPOINT_COLUMNS[1:]:
            hardware_values.append(row[column])
        row_is_pending = True
        row_is_reviewed = True
        for value in hardware_values:
            if value != "":
                row_is_pending = False
            if value == "":
                row_is_reviewed = False
        if not row_is_pending:
            all_rows_are_pending = False
        if not row_is_reviewed:
            all_rows_are_reviewed = False

    valid_classification = all_rows_are_pending
    if all_rows_are_reviewed:
        valid_classification = True
    if not valid_classification:
        raise EndpointTruthError(
            "endpoint hardware fields must be all pending or all reviewed"
        )

    if all_rows_are_pending:
        for row in rows:
            record = EndpointRecord(
                role=row["Role"],
                endpoint_id=None,
                nss_pin=None,
                reset_pin=None,
                dio0_pin=None,
                board_identity_sha256=None,
                pin_map_record_sha256=None,
            )
            records.append(record)
        return EndpointTruth(
            records=tuple(records),
            roles=("A", "B"),
            production_ready=False,
        )

    endpoint_ids: list[int] = []
    board_hashes: list[str] = []
    for row in rows:
        endpoint_id = _parse_decimal(row["EndpointId"], "EndpointId", 1, 0xFFFFFFFF)
        nss_pin = _parse_decimal(row["NssPin"], "NssPin", 2, 19)
        reset_pin = _parse_decimal(row["ResetPin"], "ResetPin", 2, 19)
        dio0_pin = _parse_decimal(row["Dio0Pin"], "Dio0Pin", 2, 3)
        hardware_spi_pins = (11, 12, 13)
        if nss_pin in hardware_spi_pins:
            raise EndpointTruthError("NssPin conflicts with a hardware SPI pin")
        if reset_pin in hardware_spi_pins:
            raise EndpointTruthError("ResetPin conflicts with a hardware SPI pin")
        if nss_pin == reset_pin:
            raise EndpointTruthError("NssPin and ResetPin must be distinct")
        if nss_pin == dio0_pin:
            raise EndpointTruthError("NssPin and Dio0Pin must be distinct")
        if reset_pin == dio0_pin:
            raise EndpointTruthError("ResetPin and Dio0Pin must be distinct")
        board_hash = _parse_sha256(
            row["BoardIdentitySha256"],
            "BoardIdentitySha256",
        )
        pin_hash = _parse_sha256(
            row["PinMapRecordSha256"],
            "PinMapRecordSha256",
        )
        record = EndpointRecord(
            role=row["Role"],
            endpoint_id=endpoint_id,
            nss_pin=nss_pin,
            reset_pin=reset_pin,
            dio0_pin=dio0_pin,
            board_identity_sha256=board_hash,
            pin_map_record_sha256=pin_hash,
        )
        records.append(record)
        endpoint_ids.append(endpoint_id)
        board_hashes.append(board_hash)
    if endpoint_ids[0] == endpoint_ids[1]:
        raise EndpointTruthError("EndpointId values must be unique")
    if board_hashes[0] == board_hashes[1]:
        raise EndpointTruthError("board identity hashes must be unique")
    return EndpointTruth(
        records=tuple(records),
        roles=("A", "B"),
        production_ready=True,
    )


def load_register_review(path: Path, expected_csv_sha256: str) -> RegisterReview:
    """Validate the review record and bind it to the loaded register CSV.

    Processing flow:
        review JSON -> exact datasheet/errata fields -> CSV-hash equality -> gates

    Direct call tree (static source order):
        load_register_review
        +-- json.loads
        +-- path.read_text
        +-- EndpointTruthError
        +-- isinstance
        +-- tuple
        +-- sorted
        +-- value.get
        +-- datasheet.get
        +-- errata.get
        +-- reviewer.strip
        +-- reviewed_utc.endswith
        `-- RegisterReview
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EndpointTruthError("cannot read profile register review") from error
    if not isinstance(value, dict):
        raise EndpointTruthError("profile register review must be an object")
    actual_review_keys = tuple(sorted(value))
    expected_review_keys = tuple(sorted(REVIEW_KEYS))
    if actual_review_keys != expected_review_keys:
        raise EndpointTruthError("profile register review fields are not exact")
    if value.get("schema_version") != "sx1278-register-review-v2":
        raise EndpointTruthError("profile register review schema mismatch")
    actual_csv_sha256 = value.get("profile_registers_sha256")
    if actual_csv_sha256 != expected_csv_sha256:
        raise EndpointTruthError("profile register review CSV hash mismatch")
    datasheet = value.get("datasheet")
    if not isinstance(datasheet, dict):
        raise EndpointTruthError("profile register review datasheet must be an object")
    actual_datasheet_keys = tuple(sorted(datasheet))
    expected_datasheet_keys = tuple(sorted(DATASHEET_KEYS))
    if actual_datasheet_keys != expected_datasheet_keys:
        raise EndpointTruthError("profile register review datasheet fields are not exact")
    if datasheet.get("title") != "SX1276/77/78/79 Datasheet":
        raise EndpointTruthError("profile register review datasheet title mismatch")
    if datasheet.get("revision") != "7":
        raise EndpointTruthError("profile register review datasheet revision mismatch")
    if datasheet.get("sections") != ["4.2", "4.4"]:
        raise EndpointTruthError("profile register review datasheet sections mismatch")
    if datasheet.get("source_file_sha256") != SEMTECH_REV7_SHA256:
        raise EndpointTruthError("profile register review datasheet hash mismatch")
    errata = value.get("errata")
    if not isinstance(errata, dict):
        raise EndpointTruthError("profile register review errata must be an object")
    actual_errata_keys = tuple(sorted(errata))
    expected_errata_keys = tuple(sorted(ERRATA_KEYS))
    if actual_errata_keys != expected_errata_keys:
        raise EndpointTruthError("profile register review errata fields are not exact")
    if errata.get("title") != "SX1276/77/78 Errata Note":
        raise EndpointTruthError("profile register review errata title mismatch")
    if errata.get("revision") != "1":
        raise EndpointTruthError("profile register review errata revision mismatch")
    if errata.get("sections") != ["2.3"]:
        raise EndpointTruthError("profile register review errata sections mismatch")
    if errata.get("source_file_sha256") != SEMTECH_ERRATA_REV1_SHA256:
        raise EndpointTruthError("profile register review errata hash mismatch")
    official_url = errata.get("official_source_url")
    expected_official_url = (
        "https://semtech.my.salesforce.com/sfc/p/E0000000JelG/a/"
        "2R000000HSPv/sqi9xX0gs6hgzl2LoPwCK0TS9GDPlMwsXmcNzJCMHjw"
    )
    if official_url != expected_official_url:
        raise EndpointTruthError("profile register review official errata URL mismatch")
    reviewed_url = errata.get("reviewed_artifact_url")
    expected_reviewed_url = (
        "https://device.report/m/"
        "1e78fe3855553edd8f820c36a6c52f5cb983bbe38de017064b873ec2b1d3d322.pdf"
    )
    if reviewed_url != expected_reviewed_url:
        raise EndpointTruthError("profile register review artifact URL mismatch")
    reviewer = value.get("reviewer")
    if not isinstance(reviewer, str):
        raise EndpointTruthError("profile register review reviewer must be text")
    if reviewer.strip() != reviewer:
        raise EndpointTruthError("profile register review reviewer is not canonical")
    if reviewer == "":
        raise EndpointTruthError("profile register review reviewer is empty")
    reviewed_utc = value.get("reviewed_utc")
    if not isinstance(reviewed_utc, str):
        raise EndpointTruthError("profile register review time must be text")
    if not reviewed_utc.endswith("Z"):
        raise EndpointTruthError("profile register review time must end in Z")
    review_status = value.get("review_status")
    audit_is_automated = review_status == "automated_datasheet_audit_complete"
    audit_is_human = review_status == "human_datasheet_review_complete"
    audit_complete = audit_is_automated
    if audit_is_human:
        audit_complete = True
    if not audit_complete:
        raise EndpointTruthError("automated datasheet audit is incomplete")
    human_status = value.get("human_approval_status")
    physical_status = value.get("physical_readback_status")
    if audit_is_automated:
        if human_status != "pending":
            raise EndpointTruthError("automated audit has invalid human approval status")
        if value.get("reviewer_kind") != "automated_datasheet_audit":
            raise EndpointTruthError("automated audit has invalid reviewer kind")
    if audit_is_human:
        if human_status != "approved":
            raise EndpointTruthError("human review has invalid human approval status")
        if value.get("reviewer_kind") != "human_datasheet_reviewer":
            raise EndpointTruthError("human review has invalid reviewer kind")
    if physical_status not in ("pending_stage0", "stage0_complete"):
        raise EndpointTruthError("profile register review physical status is invalid")
    human_complete = human_status == "approved"
    physical_complete = physical_status == "stage0_complete"
    return RegisterReview(
        automated_audit_complete=True,
        human_approval_complete=human_complete,
        physical_readback_complete=physical_complete,
        profile_registers_sha256=expected_csv_sha256,
    )


def hex_bytes(value: bytes) -> str:
    """Format bytes as a simple comma-separated C++ initializer.

    Processing flow:
        bytes in order -> two-digit uppercase literals -> comma-separated text

    Direct call tree (static source order):
        hex_bytes
        +-- parts.append
        `-- <str literal>.join
    """
    parts: list[str] = []
    for octet in value:
        parts.append(f"0x{octet:02X}")
    return ", ".join(parts)


def emit_profile_header(truth: ProfileTruth, review: RegisterReview) -> str:
    """Serialize reviewed profile rows into one bounded PROGMEM header.

            References:
                Semtech ``SX1276/77/78/79 Datasheet``, Rev. 7 (May 2020), sections 6.2 and 6.4.

            Processing flow:
                ordered register truth -> six bounded slices -> PROGMEM rows/hash/accessors

    Direct call tree (static source order):
        emit_profile_header
        +-- selected.append
        +-- len
        +-- EndpointTruthError
        +-- actual_orders.append
        +-- expected_orders.append
        +-- slice_lines.append
        +-- register_lines.append
        +-- str
        +-- bytes.fromhex
        +-- lines.extend
        +-- lines.append
        +-- hex_bytes
        `-- <str literal>.join
    """
    register_lines: list[str] = []
    slice_lines: list[str] = []
    first_index = 0
    for profile_id in PROFILE_ORDER:
        selected = []
        for row in truth.register_rows:
            if row.profile_id == profile_id:
                selected.append(row)
        if len(selected) == 0:
            raise EndpointTruthError(profile_id + " profile table is empty")
        if len(selected) > 55:
            raise EndpointTruthError(profile_id + " profile table exceeds 55 rows")
        actual_orders: list[int] = []
        expected_orders: list[int] = []
        expected_order = 1
        for row in selected:
            actual_orders.append(row.write_order)
            expected_orders.append(expected_order)
            expected_order += 1
        if actual_orders != expected_orders:
            raise EndpointTruthError(
                profile_id + ": WriteOrder must be contiguous from 1"
            )
        if selected[0].address != 0x01:
            raise EndpointTruthError(profile_id + ": first row must be RegOpMode")
        for row in selected:
            address_is_pa_config = row.address == 0x09
            address_is_ocp = row.address == 0x0B
            address_is_pa_dac = row.address == 0x4D
            if address_is_pa_config:
                raise EndpointTruthError(
                    profile_id + ": PA/OCP registers belong to pa_settings.csv"
                )
            if address_is_ocp:
                raise EndpointTruthError(
                    profile_id + ": PA/OCP registers belong to pa_settings.csv"
                )
            if address_is_pa_dac:
                raise EndpointTruthError(
                    profile_id + ": PA/OCP registers belong to pa_settings.csv"
                )
        profile_code = PROFILE_CODES[profile_id]
        slice_lines.append(
            f"    {{{profile_code}U, {first_index}U, {len(selected)}U}},"
        )
        for row in selected:
            bank_code = BANK_CODES[row.bank]
            register_lines.append(
                "    {"
                + str(profile_code)
                + "U, "
                + str(bank_code)
                + "U, "
                + f"0x{row.address:02X}U, 0x{row.write_value:02X}U, "
                + f"0x{row.readback_mask:02X}U, 0x{row.expected_readback:02X}U"
                + "},"
            )
        first_index += len(selected)

    digest_bytes = bytes.fromhex(truth.profile_registers_sha256)
    human_value = 0
    if review.human_approval_complete:
        human_value = 1
    physical_value = 0
    if review.physical_readback_complete:
        physical_value = 1
    lines = [
        "#ifndef SX1278_GENERATED_PROFILE_TABLE_H",
        "#define SX1278_GENERATED_PROFILE_TABLE_H",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "#ifdef __AVR__",
        "#include <avr/pgmspace.h>",
        "#else",
        "#define PROGMEM",
        "#endif",
        "namespace sx1278 {",
        "namespace generated {",
        "struct RegisterSetting {",
        "  uint8_t profile_code;",
        "  uint8_t bank;",
        "  uint8_t address;",
        "  uint8_t write_value;",
        "  uint8_t readback_mask;",
        "  uint8_t expected_readback;",
        "};",
        "struct ProfileSlice {",
        "  uint8_t profile_code;",
        "  uint16_t first;",
        "  uint8_t count;",
        "};",
        "static const uint8_t kProfileDatasheetAuditComplete = 1U;",
        f"static const uint8_t kProfileHumanApprovalComplete = {human_value}U;",
        f"static const uint8_t kProfilePhysicalReadbackComplete = {physical_value}U;",
        f"static const uint16_t kRegisterSettingCount = {len(truth.register_rows)}U;",
        "static const uint8_t kProfileCount = 6U;",
        "static const RegisterSetting kRegisterSettings[] PROGMEM = {",
    ]
    lines.extend(register_lines)
    lines.append("};")
    lines.append("static const ProfileSlice kProfileSlices[6] PROGMEM = {")
    lines.extend(slice_lines)
    lines.append("};")
    hash_text = hex_bytes(digest_bytes)
    lines.append(
        "static const uint8_t kProfileTableSha256[32] PROGMEM = {" + hash_text + "};"
    )
    lines.extend(
        [
            "/** Read one bounded register row from native memory or AVR flash.",
            " * Processing flow: index -> bounds check -> platform copy -> result.",
            " */",
            "inline bool read_register_setting(uint16_t index, RegisterSetting* output) {",
            "  if (output == 0) {",
            "    return false;",
            "  }",
            "  if (index >= kRegisterSettingCount) {",
            "    return false;",
            "  }",
            "#ifdef __AVR__",
            "  memcpy_P(output, &kRegisterSettings[index], sizeof(RegisterSetting));",
            "#else",
            "  *output = kRegisterSettings[index];",
            "#endif",
            "  return true;",
            "}",
            "/** Read one bounded profile slice from native memory or AVR flash.",
            " * Processing flow: profile code -> bounds check -> platform copy -> result.",
            " */",
            "inline bool read_profile_slice(uint8_t profile_code, ProfileSlice* output) {",
            "  if (output == 0) {",
            "    return false;",
            "  }",
            "  if (profile_code >= kProfileCount) {",
            "    return false;",
            "  }",
            "#ifdef __AVR__",
            "  memcpy_P(output, &kProfileSlices[profile_code], sizeof(ProfileSlice));",
            "#else",
            "  *output = kProfileSlices[profile_code];",
            "#endif",
            "  return true;",
            "}",
            "/** Read one SHA-256 byte from native memory or AVR flash.",
            " * Processing flow: index/output checks -> platform read -> byte result.",
            " */",
            "inline bool read_profile_hash_byte(uint8_t index, uint8_t* output) {",
            "  if (output == 0) {",
            "    return false;",
            "  }",
            "  if (index >= 32U) {",
            "    return false;",
            "  }",
            "#ifdef __AVR__",
            "  *output = pgm_read_byte(&kProfileTableSha256[index]);",
            "#else",
            "  *output = kProfileTableSha256[index];",
            "#endif",
            "  return true;",
            "}",
            "}",
            "}",
            "#endif",
        ]
    )
    return "\n".join(lines) + "\n"


def emit_pa_header(truth: ProfileTruth) -> str:
    """Serialize the six approved PA/OCP command rows into PROGMEM.

            References:
                Semtech ``SX1276/77/78/79 Datasheet``, Rev. 7 (May 2020), section 5.4.2 Table
                33, section 5.4.3 Table 34, and section 5.4.4 Table 37.

            Processing flow:
                six PA rows -> candidate-value checks -> PROGMEM table/accessors

    Direct call tree (static source order):
        emit_pa_header
        +-- len
        +-- EndpointTruthError
        +-- row_lines.append
        +-- str
        +-- lines.extend
        `-- <str literal>.join
    """
    if len(truth.pa_settings) != 6:
        raise EndpointTruthError("pa_settings.csv must contain six rows")
    row_lines: list[str] = []
    for row in truth.pa_settings:
        if row.reg_pa_dac != 0x84:
            raise EndpointTruthError("RegPaDac must remain 0x84")
        if row.reg_ocp != 0x2B:
            raise EndpointTruthError("RegOcp must remain candidate 0x2B")
        row_lines.append(
            "    {"
            + str(row.pa_command_dbm)
            + ", "
            + f"0x{row.reg_pa_config:02X}U, "
            + f"0x{row.reg_pa_dac:02X}U, "
            + f"0x{row.reg_ocp:02X}U"
            + "},"
        )
    lines = [
        "#ifndef SX1278_GENERATED_PA_TABLE_H",
        "#define SX1278_GENERATED_PA_TABLE_H",
        "#include <stdint.h>",
        "#ifdef __AVR__",
        "#include <avr/pgmspace.h>",
        "#else",
        "#define PROGMEM",
        "#endif",
        "namespace sx1278 {",
        "namespace generated {",
        "struct PaSetting {",
        "  int8_t command_dbm;",
        "  uint8_t reg_pa_config;",
        "  uint8_t reg_pa_dac;",
        "  uint8_t reg_ocp;",
        "};",
        "static const uint8_t kPaSettingCount = 6U;",
        "static const uint8_t kRegOcpCandidateNeedsStage0 = 1U;",
        "static const PaSetting kPaSettings[6] PROGMEM = {",
    ]
    lines.extend(row_lines)
    lines.extend(
        [
            "};",
            "/** Read one bounded PA setting from native memory or AVR flash.",
            " * Processing flow: index -> bounds check -> platform copy -> result.",
            " */",
            "inline bool read_pa_setting(uint8_t index, PaSetting* output) {",
            "  if (output == 0) {",
            "    return false;",
            "  }",
            "  if (index >= kPaSettingCount) {",
            "    return false;",
            "  }",
            "#ifdef __AVR__",
            "  memcpy_P(output, &kPaSettings[index], sizeof(PaSetting));",
            "#else",
            "  *output = kPaSettings[index];",
            "#endif",
            "  return true;",
            "}",
            "/** Find one approved PA command without allocating memory.",
            " * Processing flow: command -> scan six flash rows -> copy match or fail.",
            " */",
            "inline bool find_pa_setting(int8_t command_dbm, PaSetting* output) {",
            "  if (output == 0) {",
            "    return false;",
            "  }",
            "  for (uint8_t index = 0U; index < kPaSettingCount; ++index) {",
            "    PaSetting candidate;",
            "    bool read_ok = read_pa_setting(index, &candidate);",
            "    if (!read_ok) {",
            "      return false;",
            "    }",
            "    if (candidate.command_dbm == command_dbm) {",
            "      *output = candidate;",
            "      return true;",
            "    }",
            "  }",
            "  return false;",
            "}",
            "}",
            "}",
            "#endif",
        ]
    )
    return "\n".join(lines) + "\n"


def emit_endpoint_header(endpoint_truth: EndpointTruth) -> str:
    """Serialize reviewed endpoint rows or an explicit zero-count pending gate.

            Processing flow:
                A/B records -> pending or reviewed branch -> bounded table/accessor

    Direct call tree (static source order):
        emit_endpoint_header
        +-- EndpointTruthError
        +-- bytes.fromhex
        +-- hex_bytes
        +-- rows.append
        +-- str
        +-- lines.extend
        `-- <str literal>.join
    """
    complete_value = 0
    count_value = 0
    rows: list[str] = []
    if endpoint_truth.production_ready:
        complete_value = 1
        count_value = 2
        for record in endpoint_truth.records:
            if record.endpoint_id is None:
                raise EndpointTruthError("reviewed endpoint id is missing")
            if record.nss_pin is None:
                raise EndpointTruthError("reviewed NSS pin is missing")
            if record.reset_pin is None:
                raise EndpointTruthError("reviewed reset pin is missing")
            if record.dio0_pin is None:
                raise EndpointTruthError("reviewed DIO0 pin is missing")
            if record.board_identity_sha256 is None:
                raise EndpointTruthError("reviewed board hash is missing")
            if record.pin_map_record_sha256 is None:
                raise EndpointTruthError("reviewed pin-map hash is missing")
            board_bytes = bytes.fromhex(record.board_identity_sha256)
            board_text = hex_bytes(board_bytes)
            pin_map_bytes = bytes.fromhex(record.pin_map_record_sha256)
            pin_map_text = hex_bytes(pin_map_bytes)
            role_code = 0
            if record.role == "B":
                role_code = 1
            rows.append(
                "    {"
                + str(role_code)
                + "U, "
                + str(record.endpoint_id)
                + "UL, "
                + str(record.nss_pin)
                + "U, "
                + str(record.reset_pin)
                + "U, "
                + str(record.dio0_pin)
                + "U, {"
                + board_text
                + "}, {"
                + pin_map_text
                + "}},"
            )
    if not endpoint_truth.production_ready:
        rows.append("    {0U, 0UL, 0U, 0U, 0U, {0U}, {0U}},")
        rows.append("    {1U, 0UL, 0U, 0U, 0U, {0U}, {0U}},")

    lines = [
        "#ifndef SX1278_GENERATED_ENDPOINT_CONFIG_H",
        "#define SX1278_GENERATED_ENDPOINT_CONFIG_H",
        "#include <stdint.h>",
        "#ifdef __AVR__",
        "#include <avr/pgmspace.h>",
        "#else",
        "#define PROGMEM",
        "#endif",
        "namespace sx1278 {",
        "namespace generated {",
        "struct EndpointConfig {",
        "  uint8_t role;",
        "  uint32_t endpoint_id;",
        "  uint8_t nss_pin;",
        "  uint8_t reset_pin;",
        "  uint8_t dio0_pin;",
        "  uint8_t board_sha256[32];",
        "  uint8_t pin_map_sha256[32];",
        "};",
        f"static const uint8_t kEndpointReviewComplete = {complete_value}U;",
        f"static const uint8_t kEndpointConfigCount = {count_value}U;",
        "static const EndpointConfig kEndpointConfigs[2] PROGMEM = {",
    ]
    lines.extend(rows)
    lines.extend(
        [
            "};",
            "/** Read one endpoint only after the physical record is complete.",
            " * Processing flow: index -> review/count checks -> copy reviewed row.",
            " */",
            "inline bool read_endpoint_config(uint8_t index, EndpointConfig* output) {",
            "  if (output == 0) {",
            "    return false;",
            "  }",
            "  if (kEndpointReviewComplete == 0U) {",
            "    return false;",
            "  }",
            "  if (index >= 2U) {",
            "    return false;",
            "  }",
            "#ifdef __AVR__",
            "  memcpy_P(output, &kEndpointConfigs[index], sizeof(EndpointConfig));",
            "#else",
            "  *output = kEndpointConfigs[index];",
            "#endif",
            "  return true;",
            "}",
            "}",
            "}",
            "#endif",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_or_check(path: Path, content: str, check: bool) -> None:
    """Write deterministic ASCII or reject a missing/stale generated file.

    Processing flow:
        Generated table text -> deterministic ASCII bytes
        -> check mode: require identical existing bytes; write mode: create the output file.

    Direct call tree (static source order):
        _write_or_check
        +-- content.encode
        +-- path.is_file
        +-- EndpointTruthError
        +-- str
        +-- path.read_bytes
        +-- path.parent.mkdir
        `-- path.write_bytes
    """
    encoded = content.encode("ascii")
    if check:
        if not path.is_file():
            raise EndpointTruthError("generated file is missing: " + str(path))
        existing = path.read_bytes()
        if existing != encoded:
            raise EndpointTruthError("generated file is stale: " + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def generate_tables(
    config_dir: Path,
    output_dir: Path,
    check: bool = False,
    require_production: bool = False,
) -> dict[str, bytes]:
    """Generate the three AVR truth headers from reviewed source files.

    Processing flow:
        shared truth + review + endpoints -> validate all gates
                                          |
                                          v
        emit profile/PA/endpoint headers -> check or write exact bytes

    Direct call tree (static source order):
        generate_tables
        +-- load_profile_truth
        +-- load_register_review
        +-- read_endpoints
        +-- EndpointTruthError
        +-- emit_profile_header
        +-- emit_pa_header
        +-- emit_endpoint_header
        +-- sorted
        +-- _write_or_check
        `-- content.encode
    """
    truth = load_profile_truth(config_dir)
    review_path = config_dir / "profile_registers.review.json"
    review = load_register_review(review_path, truth.profile_registers_sha256)
    endpoint_path = config_dir / "firmware_endpoints.csv"
    endpoint_truth = read_endpoints(endpoint_path)
    if require_production:
        if not review.human_approval_complete:
            raise EndpointTruthError("hardware review is pending: human approval")
        if not endpoint_truth.production_ready:
            raise EndpointTruthError("hardware review is pending: endpoint identity and pins")

    outputs: dict[str, str] = {}
    outputs["profile_table.h"] = emit_profile_header(truth, review)
    outputs["pa_table.h"] = emit_pa_header(truth)
    outputs["endpoint_config.h"] = emit_endpoint_header(endpoint_truth)
    returned: dict[str, bytes] = {}
    for name in sorted(outputs):
        content = outputs[name]
        path = output_dir / name
        _write_or_check(path, content, check)
        returned[name] = content.encode("ascii")
    return returned


def main(arguments: list[str] | None = None) -> int:
    """Run deterministic table generation or its fail-closed check mode.

    Processing flow:
        CLI paths/flags -> generate_tables -> concise gate result

    Direct call tree (static source order):
        main
        +-- argparse.ArgumentParser
        +-- parser.add_argument
        +-- parse_configured_args
        +-- generate_tables
        +-- SystemExit
        +-- str
        +-- print
        `-- len
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-production", action="store_true")
    parsed = parse_configured_args(parser, arguments, "firmware_tables")
    try:
        generated = generate_tables(
            parsed.config,
            parsed.output,
            check=parsed.check,
            require_production=parsed.require_production,
        )
    except (EndpointTruthError, ProfileTruthError) as error:
        raise SystemExit(str(error)) from error
    mode = "generated"
    if parsed.check:
        mode = "checked"
    print("firmware tables PASS: " + mode + " files=" + str(len(generated)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
