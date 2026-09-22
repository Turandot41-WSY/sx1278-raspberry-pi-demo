"""Load and validate the shared SX1278 profile, PA, and register truth."""

import csv
from dataclasses import dataclass
from pathlib import Path

from host.common.canonical import (
    canonical_json_bytes,
    format_float,
    parse_decimal,
    sha256_bytes,
    sha256_file,
)
from host.common.schema_definitions import (
    PA_SETTING_COLUMNS,
    PROFILE_COLUMNS,
    PROFILE_REGISTER_COLUMNS,
    SCHEMA_VERSION,
)


# Project choice: keep six modulation identities in a stable order so the
# host and firmware agree on profile codes. Summary values are model inputs.
PROFILE_ORDER = ("LoRa", "FSK", "GFSK", "MSK", "GMSK", "OOK")

# RegPaConfig, RegOcp and RegPaDac are controlled by each run's PA setting,
# never by a modulation profile.  The addresses are identified in Semtech,
# ``SX1276/77/78/79 Datasheet``, Rev. 7 (May 2020), Section 4.1, Table 41,
# ``Registers Summary``, and Section 4.2, Table 42, ``Register Map``.  The
# project keeps power independent so changing modulation cannot reset power.
FORBIDDEN_PROFILE_REGISTER_ADDRESSES = (0x09, 0x0B, 0x4D)


class ProfileTruthError(ValueError):
    """Report one strict profile-truth contract violation."""


@dataclass(frozen=True)
class Profile:
    """Hold one validated radio-profile summary row."""

    profile_id: str
    profile_code: int
    family: str
    modulation: str
    carrier_hz: int
    allocated_bandwidth_hz: int
    reg_bit_rate: int | None
    reg_fdev: int | None
    spreading_factor: int | None
    coding_rate_denominator: int | None
    implicit_header: bool
    preamble_units: int
    preamble_unit: str
    sync_word_hex: str
    whitening: bool
    phy_crc: bool
    gaussian_bt: float | None
    rx_bw_register: int | None
    nominal_airtime_ms: float
    ideal_application_goodput_kbps: float


@dataclass(frozen=True)
class PaSetting:
    """Hold one validated PA command and its three hardware register bytes."""

    pa_command_dbm: int
    reg_pa_config: int
    reg_pa_dac: int
    reg_ocp: int


@dataclass(frozen=True)
class RegisterRow:
    """Hold one ordered, auditable SX1278 profile-register write."""

    profile_id: str
    bank: str
    address: int
    write_value: int
    readback_mask: int
    expected_readback: int
    write_order: int
    datasheet_revision: str
    source_section_or_table: str
    project_reason: str


@dataclass(frozen=True)
class ProfileTruth:
    """Hold the complete validated source of truth and its byte hashes."""

    profiles: tuple[Profile, ...]
    pa_settings: tuple[PaSetting, ...]
    register_rows: tuple[RegisterRow, ...]
    profiles_sha256: str
    pa_settings_sha256: str
    profile_registers_sha256: str
    aggregate_sha256: str

    @property
    def production_ready(self) -> bool:
        """Return whether every register row cites a non-synthetic source.

        Processing flow:
            Register rows -> inspect DatasheetRevision in file order
                          -> synthetic row means False
                          -> no synthetic row means True

        Direct call tree (static source order):
            production_ready
            `-- [no direct function calls; local state/return only]
        """
        for register_row in self.register_rows:
            if register_row.datasheet_revision == "SYNTHETIC-TEST":
                return False
        return True


def load_profile_truth(
    config_dir: Path = Path("config"),
    *,
    register_path: Path | None = None,
) -> ProfileTruth:
    """Load and strictly validate the profile, PA, and register truth files.

    Processing flow:
        Config directory + optional explicit register file
                          |
                          v
        Read exact CSV headers and canonical scalar text
                          |
                          v
        Validate six profiles, six PA rows, and every register row
                          |
                          v
        Hash original files and normalized truth
                          |
                          v
                  Immutable ProfileTruth

    Direct call tree (static source order):
        load_profile_truth
        +-- Path
        +-- selected_register_path.is_file
        +-- str
        +-- ProfileTruthError
        +-- _read_exact_csv
        +-- _parse_profiles
        +-- _parse_pa_settings
        +-- _parse_registers
        +-- _validate_profile_order
        +-- _validate_pa_order
        +-- _validate_register_groups
        +-- sha256_file
        +-- _normalized_truth
        +-- sha256_bytes
        +-- canonical_json_bytes
        `-- ProfileTruth
    """
    directory = Path(config_dir)
    profiles_path = directory / "profiles.csv"
    pa_settings_path = directory / "pa_settings.csv"
    selected_register_path = register_path
    if selected_register_path is None:
        selected_register_path = directory / "profile_registers.csv"
        if not selected_register_path.is_file():
            message = "production register truth missing: " + str(selected_register_path)
            raise ProfileTruthError(message)

    profile_rows = _read_exact_csv(profiles_path, PROFILE_COLUMNS)
    pa_rows = _read_exact_csv(pa_settings_path, PA_SETTING_COLUMNS)
    register_rows = _read_exact_csv(
        Path(selected_register_path),
        PROFILE_REGISTER_COLUMNS,
    )

    profiles = _parse_profiles(profile_rows)
    pa_settings = _parse_pa_settings(pa_rows)
    registers = _parse_registers(register_rows)
    _validate_profile_order(profiles)
    _validate_pa_order(pa_settings)
    _validate_register_groups(registers)

    try:
        profiles_hash = sha256_file(profiles_path)
        pa_settings_hash = sha256_file(pa_settings_path)
        profile_registers_hash = sha256_file(selected_register_path)
    except OSError as error:
        raise ProfileTruthError("cannot hash profile truth files") from error
    normalized_truth = _normalized_truth(
        profiles,
        pa_settings,
        registers,
        profiles_hash,
        pa_settings_hash,
        profile_registers_hash,
    )
    aggregate_hash = sha256_bytes(canonical_json_bytes(normalized_truth))
    return ProfileTruth(
        profiles=profiles,
        pa_settings=pa_settings,
        register_rows=registers,
        profiles_sha256=profiles_hash,
        pa_settings_sha256=pa_settings_hash,
        profile_registers_sha256=profile_registers_hash,
        aggregate_sha256=aggregate_hash,
    )


def _read_exact_csv(
    path: Path,
    expected_columns: tuple[str, ...],
) -> list[dict[str, str]]:
    """Read one CSV into string dictionaries after exact structural checks.

    Provide one reader for all three tables and reject changed headers, missing columns or extra columns.
    Inputs: path is the CSV path; expected_columns contains the ordered column names.
    Return one dictionary per record; numeric and Boolean fields remain strings at this stage.
    Preserve empty fields as "", reject missing fields, and report read/format failures as ProfileTruthError.

    Processing flow:
        CSV source -> ordered header check -> complete string rows -> returned list.

    Direct call tree (static source order):
        _read_exact_csv
        +-- path.open
        +-- csv.DictReader
        +-- tuple
        +-- ProfileTruthError
        +-- enumerate
        +-- row.get
        +-- rows.append
        `-- str
    """
    rows: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            actual_columns = tuple(reader.fieldnames or ())
            if actual_columns != expected_columns:
                raise ProfileTruthError(
                    f"{path.name} header does not match the frozen column order"
                )
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ProfileTruthError(
                        f"{path.name} row {row_number} has extra columns"
                    )
                converted: dict[str, str] = {}
                for column in expected_columns:
                    value = row.get(column)
                    if value is None:
                        raise ProfileTruthError(
                            f"{path.name} row {row_number} is missing column {column}"
                        )
                    converted[column] = value
                rows.append(converted)
    except ProfileTruthError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        message = "cannot read profile truth file " + str(path)
        raise ProfileTruthError(message) from error
    return rows


def _parse_profiles(rows: list[dict[str, str]]) -> tuple[Profile, ...]:
    """Convert CSV profile rows into validated typed Profile objects.

    Convert CSV strings to the field types used when selecting a modulation profile.
    Input rows are profiles.csv dictionaries keyed by column name.
    Return a tuple of Profile objects with int/float numbers, bool switches and None for inapplicable optional fields.
    Validate individual field formats and ranges here; later checks validate all six profiles and their fixed values.
    Report invalid fields immediately with the CSV record number and column name in ProfileTruthError.

    Processing flow:
        String profile rows -> field parsing and range checks -> Profile objects
        -> immutable tuple for subsequent cross-row validation.

    Direct call tree (static source order):
        _parse_profiles
        +-- enumerate
        +-- Profile
        +-- _required_text
        +-- _bounded_integer
        +-- _optional_bounded_integer
        +-- _parse_boolean
        +-- _parse_hex_text
        +-- _optional_float
        +-- _positive_float
        +-- profiles.append
        `-- tuple
    """
    profiles: list[Profile] = []
    for row_number, row in enumerate(rows, start=2):
        profile = Profile(
            profile_id=_required_text(row["ProfileId"], "ProfileId", row_number),
            profile_code=_bounded_integer(row["ProfileCode"], "ProfileCode", row_number, 0, 5),
            family=_required_text(row["Family"], "Family", row_number),
            modulation=_required_text(row["Modulation"], "Modulation", row_number),
            carrier_hz=_bounded_integer(
                row["CarrierHz"], "CarrierHz", row_number, 137_000_000, 1_020_000_000
            ),
            allocated_bandwidth_hz=_bounded_integer(
                row["AllocatedBandwidthHz"],
                "AllocatedBandwidthHz",
                row_number,
                1,
                500_000,
            ),
            reg_bit_rate=_optional_bounded_integer(
                row["RegBitRate"], "RegBitRate", row_number, 0, 0xFFFF
            ),
            reg_fdev=_optional_bounded_integer(
                row["RegFdev"], "RegFdev", row_number, 0, 0xFFFF
            ),
            spreading_factor=_optional_bounded_integer(
                row["SpreadingFactor"], "SpreadingFactor", row_number, 6, 12
            ),
            coding_rate_denominator=_optional_bounded_integer(
                row["CodingRateDenominator"],
                "CodingRateDenominator",
                row_number,
                5,
                8,
            ),
            implicit_header=_parse_boolean(
                row["ImplicitHeader"], "ImplicitHeader", row_number
            ),
            preamble_units=_bounded_integer(
                row["PreambleUnits"], "PreambleUnits", row_number, 1, 0xFFFF
            ),
            preamble_unit=_required_text(
                row["PreambleUnit"], "PreambleUnit", row_number
            ),
            sync_word_hex=_parse_hex_text(row["SyncWordHex"], row_number),
            whitening=_parse_boolean(row["Whitening"], "Whitening", row_number),
            phy_crc=_parse_boolean(row["PhyCrc"], "PhyCrc", row_number),
            gaussian_bt=_optional_float(row["GaussianBt"], "GaussianBt", row_number),
            rx_bw_register=_optional_bounded_integer(
                row["RxBwRegister"], "RxBwRegister", row_number, 0, 0xFF
            ),
            nominal_airtime_ms=_positive_float(
                row["NominalAirtimeMs"], "NominalAirtimeMs", row_number
            ),
            ideal_application_goodput_kbps=_positive_float(
                row["IdealApplicationGoodputKbps"],
                "IdealApplicationGoodputKbps",
                row_number,
            ),
        )
        profiles.append(profile)
    return tuple(profiles)


def _parse_pa_settings(rows: list[dict[str, str]]) -> tuple[PaSetting, ...]:
    """Convert PA table rows into typed power-command register settings.

    Map each power command to three register bytes for configuration and readback checks.
    Input: string records from pa_settings.csv. Output: a tuple of PaSetting objects.
    Check field ranges here; _validate_pa_order checks the six project-selected mappings.
    The power field specifies a command setting, not measured RF output power.

    Processing flow:
        PA text rows -> command and byte validation -> PaSetting tuple.

    Direct call tree (static source order):
        _parse_pa_settings
        +-- enumerate
        +-- PaSetting
        +-- _bounded_integer
        +-- settings.append
        `-- tuple
    """
    settings: list[PaSetting] = []
    for row_number, row in enumerate(rows, start=2):
        setting = PaSetting(
            pa_command_dbm=_bounded_integer(
                row["PaCommandDbm"], "PaCommandDbm", row_number, 2, 17
            ),
            reg_pa_config=_bounded_integer(
                row["RegPaConfig"], "RegPaConfig", row_number, 0, 0xFF
            ),
            reg_pa_dac=_bounded_integer(
                row["RegPaDac"], "RegPaDac", row_number, 0, 0xFF
            ),
            reg_ocp=_bounded_integer(row["RegOcp"], "RegOcp", row_number, 0, 0xFF),
        )
        settings.append(setting)
    return tuple(settings)


def _parse_registers(rows: list[dict[str, str]]) -> tuple[RegisterRow, ...]:
    """Convert register table rows into ordered typed write/readback records.

    Prepare the same register records for firmware generation and host readback checks.
    Input: string records from profile_registers.csv. Output: a tuple of RegisterRow objects.
    Reject power-control addresses in modulation tables and validate byte ranges, banks and readback masks.
    expected_readback may set only bits covered by readback_mask so every expected bit can be checked.

    Processing flow:
        Register text rows -> address and field checks -> masked expectation checks
        -> RegisterRow tuple for group validation.

    Direct call tree (static source order):
        _parse_registers
        +-- enumerate
        +-- _bounded_integer
        +-- ProfileTruthError
        +-- RegisterRow
        +-- _required_text
        +-- registers.append
        `-- tuple
    """
    registers: list[RegisterRow] = []
    for row_number, row in enumerate(rows, start=2):
        address = _bounded_integer(row["Address"], "Address", row_number, 0, 0x7F)
        if address in FORBIDDEN_PROFILE_REGISTER_ADDRESSES:
            raise ProfileTruthError(
                f"profile register row {row_number} uses forbidden PA/OCP address {address}"
            )
        register = RegisterRow(
            profile_id=_required_text(row["ProfileId"], "ProfileId", row_number),
            bank=_required_text(row["Bank"], "Bank", row_number),
            address=address,
            write_value=_bounded_integer(
                row["WriteValue"], "WriteValue", row_number, 0, 0xFF
            ),
            readback_mask=_bounded_integer(
                row["ReadbackMask"], "ReadbackMask", row_number, 0, 0xFF
            ),
            expected_readback=_bounded_integer(
                row["ExpectedReadback"], "ExpectedReadback", row_number, 0, 0xFF
            ),
            write_order=_bounded_integer(
                row["WriteOrder"], "WriteOrder", row_number, 1, 55
            ),
            datasheet_revision=_required_text(
                row["DatasheetRevision"], "DatasheetRevision", row_number
            ),
            source_section_or_table=_required_text(
                row["SourceSectionOrTable"], "SourceSectionOrTable", row_number
            ),
            project_reason=_required_text(
                row["ProjectReason"], "ProjectReason", row_number
            ),
        )
        if register.bank not in ("LoRa", "FSK"):
            raise ProfileTruthError(
                f"register row {row_number} Bank must be LoRa or FSK"
            )
        bits_outside_mask = (~register.readback_mask) & 0xFF
        unexpected_bits = register.expected_readback & bits_outside_mask
        if unexpected_bits != 0:
            raise ProfileTruthError(
                f"register row {row_number} ExpectedReadback sets bits outside mask"
            )
        registers.append(register)
    return tuple(registers)


def _validate_profile_order(profiles: tuple[Profile, ...]) -> None:
    """Require the six project profiles to retain their identities and order.

    Keep CSV profile names in one-to-one correspondence with firmware codes 0 through 5.
    Input: parsed Profile objects. Return None on success; reject reordering, duplicates or changed fixed values.
    The six combinations, shared carrier and allocated bandwidth are fixed project experiment conditions.

    Processing flow:
        Typed profiles -> identity/order checks -> family and shared-value checks
        -> detailed frozen-parameter validation.

    Direct call tree (static source order):
        _validate_profile_order
        +-- len
        +-- ProfileTruthError
        +-- actual_ids.append
        +-- actual_codes.append
        +-- tuple
        +-- range
        +-- set
        +-- enumerate
        `-- _validate_frozen_profile_parameters
    """
    if len(profiles) != 6:
        raise ProfileTruthError("profiles.csv must contain exactly six profiles in frozen order")
    actual_ids: list[str] = []
    actual_codes: list[int] = []
    for profile in profiles:
        actual_ids.append(profile.profile_id)
        actual_codes.append(profile.profile_code)
    if tuple(actual_ids) != PROFILE_ORDER:
        raise ProfileTruthError("profiles.csv must use the frozen six profiles and order")
    if tuple(actual_codes) != tuple(range(6)):
        raise ProfileTruthError("ProfileCode values must be unique and ordered 0 through 5")
    if len(set(actual_ids)) != 6 or len(set(actual_codes)) != 6:
        raise ProfileTruthError("ProfileId and ProfileCode values must be unique")

    expected_families = ("LoRa", "FSK", "FSK", "FSK", "FSK", "FSK")
    for index, profile in enumerate(profiles):
        if profile.family != expected_families[index]:
            raise ProfileTruthError(f"{profile.profile_id} has the wrong Family")
        if profile.modulation != profile.profile_id:
            raise ProfileTruthError(f"{profile.profile_id} has the wrong Modulation")
        if profile.carrier_hz != 437_500_000:
            raise ProfileTruthError("CarrierHz must be the frozen 437500000 Hz")
        if profile.allocated_bandwidth_hz != 125_000:
            raise ProfileTruthError("AllocatedBandwidthHz must be the frozen 125000 Hz")
    _validate_frozen_profile_parameters(profiles)


def _validate_frozen_profile_parameters(profiles: tuple[Profile, ...]) -> None:
    """Compare each profile against the project's frozen parameter combination.

    Reject partial CSV changes that would otherwise retain an existing experiment identity.
    Input: Profile objects. Normalize floating-point text before comparing complete field combinations.
    Return None on success or raise ProfileTruthError; table airtime and goodput are model values, not measurements.

    Processing flow:
        Typed profiles -> normalized parameter tuples -> frozen combination comparison.

    Direct call tree (static source order):
        _validate_frozen_profile_parameters
        +-- format_float
        +-- normalized_rows.append
        `-- ProfileTruthError
    """
    normalized_rows: list[tuple[object, ...]] = []
    for profile in profiles:
        row = (
            profile.reg_bit_rate,
            profile.reg_fdev,
            profile.spreading_factor,
            profile.coding_rate_denominator,
            profile.implicit_header,
            profile.preamble_units,
            profile.preamble_unit,
            profile.sync_word_hex,
            profile.whitening,
            profile.phy_crc,
            profile.gaussian_bt,
            profile.rx_bw_register,
            format_float(profile.nominal_airtime_ms),
            format_float(profile.ideal_application_goodput_kbps),
        )
        normalized_rows.append(row)

    # Project choice: retain these parameter combinations for repeatable
    # comparisons. Airtime and goodput are model values, not measurements.
    expected_rows = [
        (None, None, 6, 5, True, 8, "symbol", "12", False, True, None, None, "66.688", "5.998"),
        (512, 512, None, None, False, 8, "byte", "1ACFFC1D", True, True, None, 3, "9.984", "40.064"),
        (512, 512, None, None, False, 8, "byte", "1ACFFC1D", True, True, 0.5, 3, "9.984", "40.064"),
        (400, 328, None, None, False, 8, "byte", "1ACFFC1D", True, True, None, 3, "7.8", "51.282"),
        (400, 328, None, None, False, 8, "byte", "1ACFFC1D", True, True, 0.5, 3, "7.8", "51.282"),
        (977, None, None, None, False, 8, "byte", "1ACFFC1D", True, True, None, 3, "19.0515", "20.996"),
    ]
    if normalized_rows != expected_rows:
        raise ProfileTruthError("profiles.csv does not match the frozen profile parameters")


def _validate_pa_order(settings: tuple[PaSetting, ...]) -> None:
    """Require the project-selected power commands and register bytes in order.

    Check that six power commands retain the register combinations shared by sending and readback.
    Input: PaSetting objects. Return None on success; reject any row or ordering difference with ProfileTruthError.
    This checks configuration consistency, not actual output power.

    Processing flow:
        PA settings -> ordered command/register tuples -> frozen mapping comparison.

    Direct call tree (static source order):
        _validate_pa_order
        +-- actual_rows.append
        `-- ProfileTruthError
    """
    actual_rows: list[tuple[int, int, int, int]] = []
    for setting in settings:
        actual_rows.append(
            (
                setting.pa_command_dbm,
                setting.reg_pa_config,
                setting.reg_pa_dac,
                setting.reg_ocp,
            )
        )
    # Semtech ``SX1276/77/78/79 Datasheet``, Rev. 7 (May 2020),
    # Section 3.4.2, Table 33 defines PA_BOOST +2..+17 dBm and its Pout equation;
    # Section 3.4.3, Table 34 identifies RegPaDac=0x84 outside +20 dBm mode;
    # Section 3.4.4, Table 37 gives the OCP trim equation; and Section 4.2,
    # Table 42 defines the RegPaConfig/RegOcp fields.  The choice to use these
    # six powers provides 3 dB comparison steps. RegOcp=0x2B selects the
    # 100 mA PA current limit. Actual RF power still requires measurement.
    expected_rows = [
        (2, 0x80, 0x84, 0x2B),
        (5, 0x83, 0x84, 0x2B),
        (8, 0x86, 0x84, 0x2B),
        (11, 0x89, 0x84, 0x2B),
        (14, 0x8C, 0x84, 0x2B),
        (17, 0x8F, 0x84, 0x2B),
    ]
    if actual_rows != expected_rows:
        raise ProfileTruthError("pa_settings.csv must match the frozen six-row PA mapping")


def _validate_register_groups(registers: tuple[RegisterRow, ...]) -> None:
    """Require complete profile groups with contiguous register write order.

    Require records for every profile, correct banks and consecutive write order starting at 1 in file order.
    Input: RegisterRow objects. Return None on success; reject unknown groups, missing groups or incorrect order.
    The maximum of 55 rows per group is a project protocol/firmware configuration-report capacity limit.

    Processing flow:
        Register rows -> six profile groups -> bank and write-order checks
        -> original flat-order comparison.

    Direct call tree (static source order):
        _validate_register_groups
        +-- ProfileTruthError
        +-- grouped[...].append
        +-- len
        +-- enumerate
        +-- expected_flat_order.append
        `-- actual_flat_order.append
    """
    grouped: dict[str, list[RegisterRow]] = {}
    for profile_id in PROFILE_ORDER:
        grouped[profile_id] = []
    for register in registers:
        if register.profile_id not in grouped:
            raise ProfileTruthError(f"unknown profile register group {register.profile_id}")
        grouped[register.profile_id].append(register)

    expected_flat_order: list[tuple[str, int]] = []
    for profile_id in PROFILE_ORDER:
        group = grouped[profile_id]
        if not group:
            raise ProfileTruthError(f"profile_registers.csv is missing profile {profile_id}")
        if len(group) > 55:
            raise ProfileTruthError(f"profile {profile_id} has more than 55 register rows")
        if profile_id == "LoRa":
            expected_bank = "LoRa"
        else:
            expected_bank = "FSK"
        for index, register in enumerate(group, start=1):
            if register.write_order != index:
                raise ProfileTruthError(
                    f"profile {profile_id} WriteOrder must be contiguous from 1"
                )
            if register.bank != expected_bank:
                raise ProfileTruthError(f"profile {profile_id} uses the wrong register Bank")
            expected_flat_order.append((profile_id, index))

    actual_flat_order: list[tuple[str, int]] = []
    for register in registers:
        actual_flat_order.append((register.profile_id, register.write_order))
    if actual_flat_order != expected_flat_order:
        raise ProfileTruthError("profile register rows must follow profile and WriteOrder order")


def _required_text(value: str, column: str, row_number: int) -> str:
    """Return required text only when it is nonempty and has no outer whitespace.

    Prevent empty names or surrounding whitespace from making subsequent configuration lookups ambiguous.
    value is the original field text; column and row_number locate errors.
    Return the original string without stripping whitespace or checking membership in an enumeration.

    Processing flow:
        Text field -> nonempty and boundary-whitespace checks -> unchanged text.

    Direct call tree (static source order):
        _required_text
        +-- value.strip
        `-- ProfileTruthError
    """
    if not value or value.strip() != value:
        raise ProfileTruthError(f"row {row_number} {column} must be non-empty canonical text")
    return value


def _bounded_integer(
    value: str,
    column: str,
    row_number: int,
    minimum: int,
    maximum: int,
) -> int:
    """Parse canonical decimal text and enforce inclusive integer bounds.

    Convert CSV text to a configuration/protocol integer and report errors at the source field.
    minimum and maximum define the inclusive range; column and row_number locate errors.
    Return int; invalid representations or out-of-range values raise ProfileTruthError without truncation or clamping.

    Processing flow:
        Decimal field -> canonical integer parse -> inclusive bounds -> integer value.

    Direct call tree (static source order):
        _bounded_integer
        +-- parse_decimal
        `-- ProfileTruthError
    """
    try:
        parsed = parse_decimal(value)
    except ValueError as error:
        raise ProfileTruthError(f"row {row_number} {column} must be canonical decimal") from error
    if parsed < minimum or parsed > maximum:
        raise ProfileTruthError(
            f"row {row_number} {column} must be in range {minimum}..{maximum}"
        )
    return parsed


def _optional_bounded_integer(
    value: str,
    column: str,
    row_number: int,
    minimum: int,
    maximum: int,
) -> int | None:
    """Map an empty field to None or validate a bounded decimal integer.

    Preserve fields that do not apply to a modulation profile instead of treating absence as zero.
    Only an empty string becomes None; nonempty values use _bounded_integer for format, range and error location.

    Processing flow:
        Optional field -> empty: None / present: bounded integer validation.

    Direct call tree (static source order):
        _optional_bounded_integer
        `-- _bounded_integer
    """
    if value == "":
        return None
    return _bounded_integer(value, column, row_number, minimum, maximum)


def _parse_boolean(value: str, column: str, row_number: int) -> bool:
    """Convert the exact CSV strings true and false into Python booleans.

    Require unambiguous switch text instead of incorrect conversions such as bool("false").
    value must be lowercase true or false; return bool or report the invalid value with its record location.

    Processing flow:
        Boolean text -> exact accepted spelling -> bool or field error.

    Direct call tree (static source order):
        _parse_boolean
        `-- ProfileTruthError
    """
    if value == "true":
        return True
    if value == "false":
        return False
    raise ProfileTruthError(f"row {row_number} {column} must be true or false")


def _parse_hex_text(value: str, row_number: int) -> str:
    """Validate a nonempty uppercase hexadecimal string of complete bytes.

    Validate SyncWordHex as whole bytes while preserving leading zeros.
    Input: value and record number. Return the original string without converting it to an integer or bytes.
    Reject odd lengths, empty text, lowercase letters and characters outside uppercase hexadecimal notation.

    Processing flow:
        Sync-word text -> byte-length check -> case/character checks -> original text.

    Direct call tree (static source order):
        _parse_hex_text
        +-- len
        +-- ProfileTruthError
        `-- value.upper
    """
    if not value or len(value) % 2 != 0:
        raise ProfileTruthError(f"row {row_number} SyncWordHex must contain whole bytes")
    if value.upper() != value:
        raise ProfileTruthError(f"row {row_number} SyncWordHex must use uppercase hexadecimal")
    allowed = "0123456789ABCDEF"
    for character in value:
        if character not in allowed:
            raise ProfileTruthError(f"row {row_number} SyncWordHex is not hexadecimal")
    return value


def _optional_float(
    value: str,
    column: str,
    row_number: int,
) -> float | None:
    """Map an empty field to None or parse a positive finite float.

    Distinguish inapplicable optional fields such as GaussianBt from actual numeric values.
    Input: field text and error location. Return None or the float validated by _positive_float.

    Processing flow:
        Optional text -> empty: None / present: positive finite float validation.

    Direct call tree (static source order):
        _optional_float
        `-- _positive_float
    """
    if value == "":
        return None
    return _positive_float(value, column, row_number)


def _positive_float(value: str, column: str, row_number: int) -> float:
    """Parse a nonempty field as a finite float strictly greater than zero.

    Reject NaN, infinity, zero and negatives in configuration/model fields that require positive values.
    Input: original text and record location. Return float; report errors as ProfileTruthError without automatic correction.

    Processing flow:
        Text field -> whitespace check -> float and finite-value checks -> positive value.

    Direct call tree (static source order):
        _positive_float
        +-- value.strip
        +-- ProfileTruthError
        +-- float
        `-- format_float
    """
    if value == "" or value.strip() != value:
        raise ProfileTruthError(
            f"row {row_number} {column} must be non-empty canonical float text"
        )
    try:
        parsed = float(value)
        format_float(parsed)
    except (TypeError, ValueError) as error:
        raise ProfileTruthError(
            f"row {row_number} {column} must be a finite number"
        ) from error
    if parsed <= 0:
        raise ProfileTruthError(f"row {row_number} {column} must be positive")
    return parsed


def _normalized_truth(
    profiles: tuple[Profile, ...],
    pa_settings: tuple[PaSetting, ...],
    registers: tuple[RegisterRow, ...],
    profiles_sha256: str,
    pa_settings_sha256: str,
    profile_registers_sha256: str,
) -> dict[str, object]:
    """Assemble a deterministic mapping of parsed settings and source hashes.

    Prepare canonical JSON input and aggregate-hash input identifying the complete selected configuration.
    Input: three validated object groups and three source-file hashes. Return a dictionary without writing files or computing the final hash.
    Convert floating-point model values to stable text; source hashes also bind original fields not expanded individually.

    Processing flow:
        Validated profiles/PA/registers -> normalized records -> source-hash binding
        -> mapping for canonical serialization.

    Direct call tree (static source order):
        _normalized_truth
        +-- profile_values.append
        +-- format_float
        +-- pa_values.append
        `-- register_values.append
    """
    profile_values: list[dict[str, object]] = []
    for profile in profiles:
        profile_values.append(
            {
                "ProfileId": profile.profile_id,
                "ProfileCode": profile.profile_code,
                "CarrierHz": profile.carrier_hz,
                "NominalAirtimeMs": format_float(profile.nominal_airtime_ms),
                "IdealApplicationGoodputKbps": format_float(
                    profile.ideal_application_goodput_kbps
                ),
            }
        )
    pa_values: list[dict[str, int]] = []
    for setting in pa_settings:
        pa_values.append(
            {
                "PaCommandDbm": setting.pa_command_dbm,
                "RegPaConfig": setting.reg_pa_config,
                "RegPaDac": setting.reg_pa_dac,
                "RegOcp": setting.reg_ocp,
            }
        )
    register_values: list[dict[str, object]] = []
    for register in registers:
        register_values.append(
            {
                "ProfileId": register.profile_id,
                "Bank": register.bank,
                "Address": register.address,
                "WriteValue": register.write_value,
                "ReadbackMask": register.readback_mask,
                "ExpectedReadback": register.expected_readback,
                "WriteOrder": register.write_order,
                "DatasheetRevision": register.datasheet_revision,
                "SourceSectionOrTable": register.source_section_or_table,
                "ProjectReason": register.project_reason,
            }
        )
    return {
        "SchemaVersion": SCHEMA_VERSION,
        "Profiles": profile_values,
        "PaSettings": pa_values,
        "Registers": register_values,
        "ProfilesSha256": profiles_sha256,
        "PaSettingsSha256": pa_settings_sha256,
        "ProfileRegistersSha256": profile_registers_sha256,
    }
