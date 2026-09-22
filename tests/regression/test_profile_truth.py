"""Tests for the six-profile and six-PA shared source of truth."""

import csv
import shutil
from dataclasses import fields
from pathlib import Path

import pytest

from host.radio.profile_truth import ProfileTruth, ProfileTruthError, load_profile_truth


ROOT = Path(__file__).parents[2]
CONFIG = ROOT / "config"
SYNTHETIC_REGISTERS = ROOT / "tests/fixtures/profile_registers.complete.synthetic.csv"
PROFILE_IDS = ("LoRa", "FSK", "GFSK", "MSK", "GMSK", "OOK")
PROFILES_SHA256 = "23e186ed0229fd0e396d56e39be441f9394cf9fe86b22cf8e913ce9ec6c96871"
PA_SETTINGS_SHA256 = "fde7202823ea0348dbdc671714119cf8e1113575aaa345af0dc74503a51fa6af"
SYNTHETIC_REGISTERS_SHA256 = (
    "91819276a419b19414c1db0a67410b70553a2117bdde89ce34815b52e0702dd6"
)
SYNTHETIC_AGGREGATE_SHA256 = (
    "7ee95927a956a564315dd75577d575e647ccfd0b5453360fdf26e09e5d1d2724"
)


def _copy_config(tmp_path: Path) -> Path:
    """Copy profile and PA configuration into an isolated directory for mutation tests.

    Inputs: tmp_path.
    Returns: Path.

    Direct call tree (static source order):
        _copy_config
        +-- config.mkdir
        `-- shutil.copy2
    """
    config = tmp_path / "config"
    config.mkdir(parents=True)
    shutil.copy2(CONFIG / "profiles.csv", config / "profiles.csv")
    shutil.copy2(CONFIG / "pa_settings.csv", config / "pa_settings.csv")
    return config


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read CSV fixture rows together with their original ordered field names.

    Inputs: path.
    Returns: tuple[list[dict[str, str]], list[str]].

    Direct call tree (static source order):
        _read_csv
        +-- path.open
        +-- csv.DictReader
        `-- list
    """
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    return rows, fieldnames


def _rewrite_csv(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    """Rewrite profile configuration rows while preserving the selected header order.

    Inputs: path, rows, fieldnames.
    Returns: None.

    Direct call tree (static source order):
        _rewrite_csv
        +-- path.open
        +-- csv.DictWriter
        +-- writer.writeheader
        `-- writer.writerows
    """
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _copy_registers(tmp_path: Path) -> Path:
    """Copy synthetic register truth into the test's isolated configuration path.

    Inputs: tmp_path.
    Returns: Path.

    Direct call tree (static source order):
        _copy_registers
        +-- path.parent.mkdir
        `-- shutil.copy2
    """
    path = tmp_path / "profile_registers.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SYNTHETIC_REGISTERS, path)
    return path


def test_production_default_reports_the_missing_reviewed_register_truth(
    tmp_path: Path,
) -> None:
    """Verify that production default reports the missing reviewed register truth.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_production_default_reports_the_missing_reviewed_register_truth
        +-- _copy_config
        +-- pytest.raises
        +-- load_profile_truth
        `-- str
    """
    missing_register_config = _copy_config(tmp_path)
    expected_path = missing_register_config / "profile_registers.csv"
    expected_message = f"production register truth missing: {expected_path}"

    with pytest.raises(ProfileTruthError, match="production register truth missing") as error:
        load_profile_truth(missing_register_config)

    assert str(error.value) == expected_message


def test_profile_truth_public_fields_are_exact_and_immutable() -> None:
    """Verify that profile truth public fields are exact and immutable.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_profile_truth_public_fields_are_exact_and_immutable
        +-- fields
        `-- truth_field_names.append
    """
    truth_field_names: list[str] = []
    for field in fields(ProfileTruth):
        truth_field_names.append(field.name)

    assert truth_field_names == [
        "profiles",
        "pa_settings",
        "register_rows",
        "profiles_sha256",
        "pa_settings_sha256",
        "profile_registers_sha256",
        "aggregate_sha256",
    ]


def test_explicit_synthetic_fixture_loads_but_is_not_production_ready() -> None:
    """Verify that explicit synthetic fixture loads but is not production ready.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_explicit_synthetic_fixture_loads_but_is_not_production_ready
        +-- load_profile_truth
        +-- profile_ids.append
        +-- profile_codes.append
        `-- tuple
    """
    truth = load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)

    profile_ids: list[str] = []
    profile_codes: list[int] = []
    for profile in truth.profiles:
        profile_ids.append(profile.profile_id)
        profile_codes.append(profile.profile_code)
    assert tuple(profile_ids) == PROFILE_IDS
    assert tuple(profile_codes) == (0, 1, 2, 3, 4, 5)
    assert truth.production_ready is False
    assert truth.aggregate_sha256 == SYNTHETIC_AGGREGATE_SHA256
    assert truth == load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)


def test_profiles_csv_matches_the_hard_coded_golden_hash() -> None:
    """Verify that profiles csv matches the hard coded golden hash.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_profiles_csv_matches_the_hard_coded_golden_hash
        `-- load_profile_truth
    """
    truth = load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)
    assert truth.profiles_sha256 == PROFILES_SHA256


def test_pa_settings_csv_matches_the_hard_coded_golden_hash() -> None:
    """Verify that pa settings csv matches the hard coded golden hash.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pa_settings_csv_matches_the_hard_coded_golden_hash
        `-- load_profile_truth
    """
    truth = load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)
    assert truth.pa_settings_sha256 == PA_SETTINGS_SHA256


def test_synthetic_register_fixture_matches_the_hard_coded_golden_hash() -> None:
    """Verify that synthetic register fixture matches the hard coded golden hash.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_synthetic_register_fixture_matches_the_hard_coded_golden_hash
        `-- load_profile_truth
    """
    truth = load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)
    assert truth.profile_registers_sha256 == SYNTHETIC_REGISTERS_SHA256


def test_non_synthetic_register_rows_are_production_ready(tmp_path: Path) -> None:
    """Verify that non synthetic register rows are production ready.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_non_synthetic_register_rows_are_production_ready
        +-- _copy_registers
        +-- _read_csv
        +-- _rewrite_csv
        `-- load_profile_truth
    """
    path = _copy_registers(tmp_path)
    rows, fieldnames = _read_csv(path)
    for row in rows:
        row["DatasheetRevision"] = "Rev. 7"
    _rewrite_csv(path, rows, fieldnames)

    truth = load_profile_truth(CONFIG, register_path=path)

    assert truth.production_ready is True


def test_profile_values_match_the_approved_table() -> None:
    """Verify that profile values match the approved table.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_profile_values_match_the_approved_table
        +-- load_profile_truth
        `-- hasattr
    """
    truth = load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)
    by_id = {}
    for profile in truth.profiles:
        by_id[profile.profile_id] = profile

    for profile in truth.profiles:
        assert profile.carrier_hz == 437_500_000
        assert profile.allocated_bandwidth_hz == 125_000
        assert not hasattr(profile, "sync_word")
        assert not hasattr(profile, "airtime_basis")
    assert by_id["LoRa"].sync_word_hex == "12"
    assert by_id["FSK"].sync_word_hex == "1ACFFC1D"
    assert by_id["LoRa"].spreading_factor == 6
    assert by_id["LoRa"].coding_rate_denominator == 5
    assert by_id["LoRa"].implicit_header is True
    assert by_id["GFSK"].gaussian_bt == 0.5
    assert by_id["GMSK"].gaussian_bt == 0.5
    assert by_id["OOK"].reg_bit_rate == 977


def test_pa_values_match_the_approved_table() -> None:
    """Verify that pa values match the approved table.

    Inputs: no explicit arguments; instance or module state where referenced.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_pa_values_match_the_approved_table
        +-- load_profile_truth
        `-- actual_rows.append
    """
    truth = load_profile_truth(CONFIG, register_path=SYNTHETIC_REGISTERS)
    actual_rows: list[tuple[int, int, int, int]] = []
    for setting in truth.pa_settings:
        actual_rows.append(
            (
                setting.pa_command_dbm,
                setting.reg_pa_config,
                setting.reg_pa_dac,
                setting.reg_ocp,
            )
        )
    assert actual_rows == [
        (2, 0x80, 0x84, 0x2B),
        (5, 0x83, 0x84, 0x2B),
        (8, 0x86, 0x84, 0x2B),
        (11, 0x89, 0x84, 0x2B),
        (14, 0x8C, 0x84, 0x2B),
        (17, 0x8F, 0x84, 0x2B),
    ]


def test_loader_rejects_wrong_profile_header_with_contract_error(tmp_path: Path) -> None:
    """Verify that loader rejects wrong profile header with contract error.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_loader_rejects_wrong_profile_header_with_contract_error
        +-- _copy_config
        +-- path.read_text
        +-- text.replace
        +-- path.write_text
        +-- pytest.raises
        `-- load_profile_truth
    """
    config = _copy_config(tmp_path)
    path = config / "profiles.csv"
    text = path.read_text(encoding="utf-8")
    text = text.replace("ProfileId", "profile_id", 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ProfileTruthError, match="header"):
        load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)


def test_loader_rejects_missing_profile_and_duplicate_code(tmp_path: Path) -> None:
    """Verify that loader rejects missing profile and duplicate code.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_loader_rejects_missing_profile_and_duplicate_code
        +-- _copy_config
        +-- _read_csv
        +-- rows.pop
        +-- _rewrite_csv
        +-- pytest.raises
        +-- load_profile_truth
        `-- shutil.copy2
    """
    config = _copy_config(tmp_path)
    path = config / "profiles.csv"
    rows, fieldnames = _read_csv(path)
    rows.pop()
    _rewrite_csv(path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="six profiles|order"):
        load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)

    shutil.copy2(CONFIG / "profiles.csv", path)
    rows, fieldnames = _read_csv(path)
    rows[1]["ProfileCode"] = "0"
    _rewrite_csv(path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="ProfileCode"):
        load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)


def test_loader_rejects_noncanonical_required_float_text(tmp_path: Path) -> None:
    """Verify that loader rejects noncanonical required float text.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_loader_rejects_noncanonical_required_float_text
        +-- enumerate
        +-- _copy_config
        +-- str
        +-- _read_csv
        +-- _rewrite_csv
        +-- pytest.raises
        `-- load_profile_truth
    """
    bad_values = ["", " 66.688", "66.688 ", "nan", "inf"]
    for index, bad_value in enumerate(bad_values):
        config = _copy_config(tmp_path / str(index))
        path = config / "profiles.csv"
        rows, fieldnames = _read_csv(path)
        rows[0]["NominalAirtimeMs"] = bad_value
        _rewrite_csv(path, rows, fieldnames)
        with pytest.raises(ProfileTruthError, match="NominalAirtimeMs"):
            load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)


def test_loader_rejects_noncanonical_optional_float_text(tmp_path: Path) -> None:
    """Verify that loader rejects noncanonical optional float text.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_loader_rejects_noncanonical_optional_float_text
        +-- _copy_config
        +-- _read_csv
        +-- _rewrite_csv
        +-- pytest.raises
        `-- load_profile_truth
    """
    config = _copy_config(tmp_path)
    path = config / "profiles.csv"
    rows, fieldnames = _read_csv(path)
    rows[2]["GaussianBt"] = " 0.5"
    _rewrite_csv(path, rows, fieldnames)

    with pytest.raises(ProfileTruthError, match="GaussianBt"):
        load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)


def test_loader_rejects_noncanonical_boolean_and_integer_text(tmp_path: Path) -> None:
    """Verify that loader rejects noncanonical boolean and integer text.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_loader_rejects_noncanonical_boolean_and_integer_text
        +-- _copy_config
        +-- _read_csv
        +-- _rewrite_csv
        +-- pytest.raises
        +-- load_profile_truth
        `-- shutil.copy2
    """
    config = _copy_config(tmp_path)
    path = config / "profiles.csv"
    rows, fieldnames = _read_csv(path)
    rows[0]["ImplicitHeader"] = "True"
    _rewrite_csv(path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="ImplicitHeader"):
        load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)

    shutil.copy2(CONFIG / "profiles.csv", path)
    rows, fieldnames = _read_csv(path)
    rows[0]["CarrierHz"] = " 437500000"
    _rewrite_csv(path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="CarrierHz"):
        load_profile_truth(config, register_path=SYNTHETIC_REGISTERS)


def test_register_address_is_seven_bit_and_pa_registers_are_forbidden(
    tmp_path: Path,
) -> None:
    """Verify that register address is seven bit and pa registers are forbidden.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_register_address_is_seven_bit_and_pa_registers_are_forbidden
        +-- enumerate
        +-- _copy_registers
        +-- str
        +-- _read_csv
        +-- _rewrite_csv
        +-- pytest.raises
        `-- load_profile_truth
    """
    bad_addresses = [128, 9, 11, 77]
    for index, address in enumerate(bad_addresses):
        path = _copy_registers(tmp_path / str(index))
        rows, fieldnames = _read_csv(path)
        rows[0]["Address"] = str(address)
        _rewrite_csv(path, rows, fieldnames)
        with pytest.raises(ProfileTruthError, match="Address|forbidden"):
            load_profile_truth(CONFIG, register_path=path)


def test_register_expected_readback_may_differ_but_must_fit_mask(
    tmp_path: Path,
) -> None:
    """Verify that register expected readback may differ but must fit mask.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_register_expected_readback_may_differ_but_must_fit_mask
        +-- _copy_registers
        +-- _read_csv
        +-- _rewrite_csv
        +-- load_profile_truth
        `-- pytest.raises
    """
    valid_path = _copy_registers(tmp_path / "valid")
    rows, fieldnames = _read_csv(valid_path)
    rows[0]["ExpectedReadback"] = "113"
    _rewrite_csv(valid_path, rows, fieldnames)
    truth = load_profile_truth(CONFIG, register_path=valid_path)
    assert truth.register_rows[0].expected_readback == 113

    invalid_path = _copy_registers(tmp_path / "invalid")
    rows, fieldnames = _read_csv(invalid_path)
    rows[0]["ReadbackMask"] = "15"
    rows[0]["ExpectedReadback"] = "16"
    _rewrite_csv(invalid_path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="ExpectedReadback"):
        load_profile_truth(CONFIG, register_path=invalid_path)


def test_register_rows_require_contiguous_order_and_nonempty_audit_text(
    tmp_path: Path,
) -> None:
    """Verify that register rows require contiguous order and nonempty audit text.

    Inputs: tmp_path.
    Returns: None; assertion or expected exception checks determine whether the tested contract holds.

    Direct call tree (static source order):
        test_register_rows_require_contiguous_order_and_nonempty_audit_text
        +-- _copy_registers
        +-- _read_csv
        +-- _rewrite_csv
        +-- pytest.raises
        `-- load_profile_truth
    """
    order_path = _copy_registers(tmp_path / "order")
    rows, fieldnames = _read_csv(order_path)
    rows[1]["WriteOrder"] = "2"
    _rewrite_csv(order_path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="WriteOrder"):
        load_profile_truth(CONFIG, register_path=order_path)

    audit_path = _copy_registers(tmp_path / "audit")
    rows, fieldnames = _read_csv(audit_path)
    rows[0]["SourceSectionOrTable"] = ""
    _rewrite_csv(audit_path, rows, fieldnames)
    with pytest.raises(ProfileTruthError, match="SourceSectionOrTable"):
        load_profile_truth(CONFIG, register_path=audit_path)
