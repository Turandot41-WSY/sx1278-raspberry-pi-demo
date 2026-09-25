"""Convert orbital geometry results into deterministic radio settings.

This module is the numerical boundary between the continuous physical model and the discrete values used by the benchmark.

The orbit model produces a physical Doppler shift in hertz, but an SX1278 can
only tune in fixed synthesizer steps.  :func:`quantize_sx1278_doppler` keeps
both values visible: the requested physical shift and the nearest setting the
radio can actually program.  Keeping them separate lets the dataset preserve
the physical result while also reproducing the exact hardware register word.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import (
    atan2,
    ceil,
    cos,
    degrees,
    floor,
    hypot,
    isfinite,
    radians,
    sin,
    sqrt,
)
from typing import cast

import numpy as np
import astropy.units as u
from astropy.units import Quantity
from astropy.coordinates import (
    CartesianDifferential,
    CartesianRepresentation,
    ITRS,
    TEME,
)
from astropy.time import Time
from astropy.utils import iers
from sgp4.api import SGP4_ERRORS, Satrec

from firmware.host.runtime_config import load_settings

_ORBIT_MODEL = load_settings("main_dataset")["orbit_model"]


# Semtech SX1276/77/78/79 data sheet, Rev. 7 (May 2020), section 3.3.3,
# "PLL," page 82: FSTEP = FXOSC / 2**19 = 61.03515625 Hz at 32 MHz.
SX1278_FSTEP_HZ = 61.03515625

# RegFrf = carrier_hz / FSTEP.  The approved 437.5 MHz nominal carrier therefore maps to 7_168_000, written as the SX1278's three-byte word 0x6D6000.
SX1278_NOMINAL_FRF_WORD = round(float(_ORBIT_MODEL["radio"]["nominal_carrier_hz"]) / SX1278_FSTEP_HZ)

# This carrier is a project-selected operating point
NOMINAL_CARRIER_HZ = float(_ORBIT_MODEL["radio"]["nominal_carrier_hz"])

# This is the exact SI value of the speed of light in vacuum Source: BIPM, "The International System of Units (SI)," 9th edition, version 3.02, Section 2.2, Table 1.
SPEED_OF_LIGHT_MPS = 299_792_458.0

# WGS 84 is an Earth-centered, Earth-fixed geodetic reference system
# These are WGS 84 defining parameters:
# semi-major axis a = 6_378_137.0 m and inverse flattening 1/f = 298.257223563. Source: NGA.STND.0036_1.0.0_WGS84 (2014), Chapter 3, Section 3.2, Table 3.1, "WGS 84 Defining Parameters."

# Do not replace the later SGP4 propagator's WGS-72 gravity constants with these WGS 84 ellipsoid values.  SGP4 uses WGS-72 to remain compatible with
# the General Perturbations mean elements that it propagates.  Algorithm basis: Vallado et al., AIAA 2006-6753, "Revisiting Spacetrack Report #3," Section VI.B, "Constants," Table 2.
WGS84_SEMIMAJOR_AXIS_M = 6_378_137.0
WGS84_FLATTENING = 1.0 / 298.257223563


@dataclass(frozen=True, slots=True)
class GroundStation:
    """Hold the fixed station inputs needed for reproducible pass geometry.

    ``latitude_deg`` and ``longitude_deg`` are WGS 84 geodetic angles, while
    ``height_m`` is height above the WGS 84 ellipsoid rather than height above
    mean sea level.  ``elevation_mask_deg`` is an operational visibility rule,
    not part of WGS 84: later code will declare the satellite visible only at
    or above that elevation.

    The Linz values below are project planning inputs
    """

    latitude_deg: float
    longitude_deg: float
    height_m: float
    elevation_mask_deg: float


# 244 m value is a DEM-derived ellipsoidal-height proxy; 10 degrees is the project's uniform preliminary elevation mask.
LINZ_GROUND_STATION = GroundStation(
    latitude_deg=float(_ORBIT_MODEL["station"]["latitude_deg"]),
    longitude_deg=float(_ORBIT_MODEL["station"]["longitude_deg"]),
    height_m=float(_ORBIT_MODEL["station"]["height_m"]),
    elevation_mask_deg=float(_ORBIT_MODEL["station"]["elevation_mask_deg"]),
)


@dataclass(frozen=True, slots=True)
class GeometrySample:
    """Store one unquantized station-to-satellite geometry result.

    The ECEF state is retained with the derived look angles, range, range rate, and physical Doppler so pass selection and telemetry quantization do not need to repeat or hide the geometry calculation.
    """

    timestamp_utc: datetime
    position_ecef_m: tuple[float, float, float]
    velocity_ecef_mps: tuple[float, float, float]
    azimuth_deg: float
    elevation_deg: float
    slant_range_m: float
    range_rate_mps: float
    doppler_hz: float


@dataclass(frozen=True, slots=True)
class Sx1278Tuning:
    """Describe how one physical Doppler value maps to the SX1278.

    Instances are immutable so the requested-to-programmed mapping cannot be
    changed after it has been calculated and written into a trace dataset.
    """

    doppler_steps: int
    reg_frf_word: int
    programmed_doppler_hz: float
    quantization_error_hz: float


def round_half_away_from_zero(value: float) -> int:
    """Round a finite value to the nearest integer with half ties away from zero.

    Processing flow:
        Input -> reject nonfinite values -> choose sign
            -> nonnegative: floor(value + 0.5) -> integer
            -> negative: ceil(value - 0.5) -> integer.

    Direct call tree (static source order):
        round_half_away_from_zero
        +-- isfinite
        +-- ValueError
        +-- floor
        `-- ceil
    """
    if not isfinite(value):
        raise ValueError("value must be finite")

    # Unlike Python's ties-to-even round, this mirrored rule preserves sign.
    if value >= 0.0:
        return floor(value + 0.5)
    return ceil(value - 0.5)


def geodetic_to_ecef(station: GroundStation) -> np.ndarray:
    """Convert WGS 84 geodetic coordinates to an ECEF position in metres.

    References:
        IOGP Publication 373-7-2, ``Geomatics Guidance Note 7, Part 2``
        (December 2024), section 4.1.1, "Geographic/Geocentric
        conversions," EPSG coordinate-operation method 9602.

    Processing flow:
        WGS 84 latitude, longitude, and ellipsoidal height
                            |
                            v
              Convert angles from degrees to radians
                            |
                            v
          Derive eccentricity and prime-vertical radius
                            |
                            v
                 Compute ECEF X, Y, and Z
                            |
                            v
                   ECEF position vector

    Direct call tree (static source order):
        geodetic_to_ecef
        +-- radians
        +-- sin
        +-- sqrt
        +-- cos
        `-- np.array
    """
    latitude_rad = radians(station.latitude_deg)
    longitude_rad = radians(station.longitude_deg)

    # EPSG 9602: e^2 = 2f - f^2 and nu = a / sqrt(1 - e^2 sin^2(latitude)).
    eccentricity_squared = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    sin_latitude = sin(latitude_rad)
    prime_vertical_radius_m = WGS84_SEMIMAJOR_AXIS_M / sqrt(
        1.0 - eccentricity_squared * sin_latitude**2
    )

    radial_distance_m = prime_vertical_radius_m + station.height_m
    x_m = radial_distance_m * cos(latitude_rad) * cos(longitude_rad)
    y_m = radial_distance_m * cos(latitude_rad) * sin(longitude_rad)
    z_m = (
        prime_vertical_radius_m * (1.0 - eccentricity_squared)
        + station.height_m
    ) * sin_latitude

    return np.array([x_m, y_m, z_m], dtype=float)


def propagate_itrs(
    *,
    satellite: Satrec,
    timestamps_utc: Sequence[datetime],
    earth_orientation_table: iers.IERS | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate SGP4 TEME states into ITRS/ECEF positions and velocities.

    References:
        Vallado et al., AIAA 2006-6753, ``Revisiting Spacetrack Report #3``;
        ``python-sgp4`` 2.27 ``Satrec.sgp4_array``; Astropy 8.0.1,
        ``Working with Earth Satellites Using Astropy Coordinates``,
        sections "Satellite data" and "Transforming TEME to other coordinate
        systems".

    Pipeline context:
               One OMM + one element epoch
                            |
                            v
                 Initialize one Satrec model
                            |
              +-------------+-------------+
              |                           |
              v                           v
        Target UTC time 0       Target UTC time 1 ... N-1
              |                           |
              v                           v
         SGP4 TEME state 0       SGP4 TEME state 1 ... N-1
              |                           |
              v                           v
         ITRS/ECEF row 0         ITRS/ECEF row 1 ... N-1

    Processing flow:
        Validated Satrec + UTC timestamps
                       |
                       v
             Split UTC Julian dates
                       |
                       v
             Vectorized SGP4 propagation
                       |
                       v
          TEME position and velocity states
                       |
                       v
        Apply Earth orientation and TEME -> ITRS
                       |
                       v
        ECEF position (m) and velocity (m/s)

    Direct call tree (static source order):
        propagate_itrs
        +-- list
        +-- ValueError
        +-- timestamp.utcoffset
        +-- timedelta
        +-- Time
        +-- satellite.sgp4_array
        +-- np.flatnonzero
        +-- int
        +-- SGP4_ERRORS.get
        +-- timestamps[...].isoformat
        +-- CartesianRepresentation
        +-- CartesianDifferential
        +-- TEME
        +-- position.with_differentials
        +-- teme.transform_to
        +-- ITRS
        +-- iers.earth_orientation_table.set
        +-- cast
        +-- itrs_position.get_xyz
        +-- itrs_velocity.get_d_xyz
        +-- np.asarray
        +-- position_xyz.to_value
        +-- velocity_xyz.to_value
        +-- np.isfinite
        `-- np.isfinite(...).all
    """
    timestamps = list(timestamps_utc)
    if not timestamps:
        raise ValueError("timestamps_utc must contain at least one timestamp")
    for timestamp in timestamps:
        if timestamp.tzinfo is None:
            raise ValueError("timestamps_utc must contain timezone-aware UTC datetimes")
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("timestamps_utc must contain timezone-aware UTC datetimes")

    times = Time(timestamps, scale="utc")
    errors, position_teme_km, velocity_teme_kmps = satellite.sgp4_array(
        times.jd1,
        times.jd2,
    )

    failed_indices = np.flatnonzero(errors)
    if failed_indices.size:
        index = int(failed_indices[0])
        error = int(errors[index])
        message = SGP4_ERRORS.get(error, "unknown SGP4 error")
        raise ValueError(
            f"SGP4 propagation failed at index {index} "
            f"({timestamps[index].isoformat()}), error {error}: {message}"
        )

    position = CartesianRepresentation(position_teme_km * u.km, xyz_axis=1)
    velocity = CartesianDifferential(
        velocity_teme_kmps * u.km / u.s,
        xyz_axis=1,
    )
    teme = TEME(position.with_differentials(velocity), obstime=times)

    if earth_orientation_table is None:
        itrs = teme.transform_to(ITRS(obstime=times))
    else:
        with iers.earth_orientation_table.set(earth_orientation_table):
            itrs = teme.transform_to(ITRS(obstime=times))

    # Astropy exposes these concrete types through unannotated frame accessors.
    itrs_position = cast(CartesianRepresentation, itrs.cartesian)
    itrs_velocity = cast(
        CartesianDifferential,
        itrs_position.differentials["s"],
    )
    position_xyz = cast(Quantity, itrs_position.get_xyz())
    velocity_xyz = cast(Quantity, itrs_velocity.get_d_xyz())
    position_ecef_m = np.asarray(
        position_xyz.to_value(u.m),
        dtype=float,
    ).T
    velocity_ecef_mps = np.asarray(
        velocity_xyz.to_value(u.m / u.s),
        dtype=float,
    ).T

    if not (
        np.isfinite(position_ecef_m).all()
        and np.isfinite(velocity_ecef_mps).all()
    ):
        raise ValueError("ITRS transformation produced non-finite states")

    return position_ecef_m, velocity_ecef_mps


def compute_geometry_sample(
    *,
    timestamp_utc: datetime,
    position_ecef_m: np.ndarray,
    velocity_ecef_mps: np.ndarray,
    station: GroundStation,
) -> GeometrySample:
    """Derive one ground-station link sample from an ECEF satellite state.

    References:
        ESA TM-23/1, ``GNSS Data Processing, Volume I`` (2013), appendix B,
        sections B.2-B.3, equations (B.11)-(B.16); EPSG method 9836.
        Davis, ``Lunar Gravitational Field Estimation and the Effects of
        Mismodeling upon Lunar Satellite Orbit Prediction`` (1993), section
        4.3.7, equation (4.3.7-1).

    Processing flow:
        Satellite ECEF position and velocity
        + station geodetic coordinates
                        |
                        v
           Validate both ECEF vectors as shape (3,)
                        |
                        v
           Station geodetic coordinates -> station ECEF
                        |
                        v
              Satellite ECEF - station ECEF
                        |
                        v
             Line-of-sight vector and slant range
                        |
                 +------+------+
                 |             |
                 v             v
            ECEF -> ENU    rho . velocity / |rho|
                 |             |
                 v             v
        Azimuth/elevation   range rate
                               |
                               v
                        physical Doppler
                               |
                               v
                        GeometrySample

    Direct call tree (static source order):
        compute_geometry_sample
        +-- np.asarray
        +-- ValueError
        +-- geodetic_to_ecef
        +-- float
        +-- np.linalg.norm
        +-- radians
        +-- sin
        +-- cos
        +-- degrees
        +-- atan2
        +-- hypot
        +-- np.dot
        `-- GeometrySample
    """
    position = np.asarray(position_ecef_m, dtype=float)
    velocity = np.asarray(velocity_ecef_mps, dtype=float)

    if position.shape != (3,):
        raise ValueError(
            "position_ecef_m must have shape (3,), "
            f"received {position.shape}"
        )
    if velocity.shape != (3,):
        raise ValueError(
            "velocity_ecef_mps must have shape (3,), "
            f"received {velocity.shape}"
        )

    station_ecef_m = geodetic_to_ecef(station)

    # rho is the station-to-satellite line of sight in ECEF.
    relative_position_m = position - station_ecef_m
    slant_range_m = float(np.linalg.norm(relative_position_m))

    latitude_rad = radians(station.latitude_deg)
    longitude_rad = radians(station.longitude_deg)
    delta_x_m, delta_y_m, delta_z_m = relative_position_m

    # ESA TM-23/1 equation (B.11): ECEF-to-ENU rotation at the station.
    east_m = -sin(longitude_rad) * delta_x_m + cos(longitude_rad) * delta_y_m
    north_m = (
        -sin(latitude_rad) * cos(longitude_rad) * delta_x_m
        - sin(latitude_rad) * sin(longitude_rad) * delta_y_m
        + cos(latitude_rad) * delta_z_m
    )
    up_m = (
        cos(latitude_rad) * cos(longitude_rad) * delta_x_m
        + cos(latitude_rad) * sin(longitude_rad) * delta_y_m
        + sin(latitude_rad) * delta_z_m
    )

    # Azimuth is clockwise from North; elevation is above the local horizon.
    azimuth_deg = degrees(atan2(east_m, north_m)) % 360.0
    elevation_deg = degrees(atan2(up_m, hypot(east_m, north_m)))

    # In ECEF the fixed station velocity is zero; negative range rate approaches.
    range_rate_mps = float(
        np.dot(relative_position_m, velocity) / slant_range_m
    )

    # Equation (4.3.7-1): negative range rate gives positive Doppler.
    doppler_hz = -(
        range_rate_mps / SPEED_OF_LIGHT_MPS
    ) * NOMINAL_CARRIER_HZ

    return GeometrySample(
        timestamp_utc=timestamp_utc,

        position_ecef_m=(
            float(position[0]),
            float(position[1]),
            float(position[2]),
        ),
        velocity_ecef_mps=(
            float(velocity[0]),
            float(velocity[1]),
            float(velocity[2]),
        ),
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        slant_range_m=slant_range_m,
        range_rate_mps=range_rate_mps,
        doppler_hz=doppler_hz,
    )


def quantize_sx1278_doppler(doppler_hz: float) -> Sx1278Tuning:
    """Map a physical Doppler shift to the nearest SX1278 frequency setting.

    References:
        Semtech, ``SX1276/77/78/79 Low Power Long Range Transceiver``,
        Rev. 7 (May 2020), section 3.3.3, "PLL," page 82: FSTEP = FXOSC /
        2**19, FRF = FSTEP * Frf(23,0), with RegFrf split across three bytes.

    Processing flow:
        Physical Doppler shift
                  |
                  v
        Divide by the SX1278 frequency step
                  |
                  v
        Round to a signed integer step count
                  |
                  v
        Offset and validate the 24-bit RegFrf word
                  |
                  v
        Reconstruct programmed Doppler and error
                  |
                  v
                Sx1278Tuning

    Direct call tree (static source order):
        quantize_sx1278_doppler
        +-- round_half_away_from_zero
        +-- ValueError
        `-- Sx1278Tuning
    """
    steps = round_half_away_from_zero(doppler_hz / SX1278_FSTEP_HZ)

    word = SX1278_NOMINAL_FRF_WORD + steps

    # The SX1278 exposes three RegFrf bytes, so the complete value must remain
    if not 0 <= word <= 0xFFFFFF:
        raise ValueError("SX1278 RegFrf word must fit in uint24")

    # Reconstruct the offset the hardware will actually generate.
    programmed = steps * SX1278_FSTEP_HZ
    return Sx1278Tuning(
        doppler_steps=steps,
        reg_frf_word=word,
        programmed_doppler_hz=programmed,
        quantization_error_hz=programmed - doppler_hz,
    )
