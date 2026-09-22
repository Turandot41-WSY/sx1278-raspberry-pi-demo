"""Read received frames for the browser without owning a radio or serial port."""

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading

from astropy import units as u
from astropy.coordinates import EarthLocation, angular_separation, offset_by

from host.dataset.ccsds_tm import build_tm_frame, decode_tm_and_space_headers, validate_tm_frame
from host.dataset.orbit_record import unpack_mission_record, validation_pattern
from host.dataset.orbit_trace import load_frozen_orbit_dataset


class OrbitReference:
    """Associate received bytes with the archived orbit and its ground station."""

    def __init__(self, archive):
        """Load the archive identities and calculate a regional display window.

        References:
            Astropy 8.0.1 API, EarthLocation.from_geocentric and to_geodetic;
            angular_separation and offset_by, Parameters and Returns sections:
            https://docs.astropy.org/en/stable/api/astropy.coordinates.EarthLocation.html
            https://docs.astropy.org/en/stable/api/astropy.coordinates.angular_separation.html
            https://docs.astropy.org/en/stable/api/astropy.coordinates.offset_by.html

        Processing flow:
            Load source metadata -> associate exact frames -> convert positions
            -> find maximum ground angle -> add display margin -> set bounds.

        Direct call tree (static source order):
            __init__
            +-- Path
            +-- <BinOp expression>.is_dir
            +-- load_frozen_orbit_dataset
            +-- json.loads
            +-- <BinOp expression>.read_text
            +-- str
            +-- orbit_root.resolve
            +-- bytearray
            +-- len
            +-- frames.extend
            +-- build_tm_frame
            +-- bytes
            +-- <BinOp expression>.open
            +-- csv.DictReader
            +-- int
            +-- self.rows.values
            +-- x.append
            +-- float
            +-- y.append
            +-- z.append
            +-- EarthLocation.from_geocentric
            +-- locations.to_geodetic
            +-- angular_separation
            +-- angles.max
            +-- angles.max(...).to_value
            +-- range
            +-- offset_by
            +-- ring_lon.to_value
            +-- ring.append
            +-- ring_lat.to_value
            +-- longitudes.append
            +-- latitudes.append
            +-- min
            +-- max
            +-- self.passes.values
            `-- slant_ranges.append
        """
        archive = Path(archive)
        orbit_root = archive
        if (archive / "orbit").is_dir():
            orbit_root = archive / "orbit"
        dataset = load_frozen_orbit_dataset(orbit_root)
        metadata = json.loads((orbit_root / "provenance.json").read_text())
        self.station = metadata["station"]
        self.metadata = {"datasetId": dataset.dataset_id,
                         "epoch": metadata["orbit"]["epoch_utc"],
                         "omm": metadata["orbit"]["omm_fields"],
                         "station": self.station, "directory": str(orbit_root.resolve())}
        # Match the production transmitter's sequence counters for each global sample.
        frames = bytearray()
        for orbit_pass in dataset.passes:
            for sample in orbit_pass.schedule.samples:
                index = len(frames) // 64
                frames.extend(build_tm_frame(sample.mission_record, index % 16384,
                                             index % 256, index % 256))
        self.frames = bytes(frames)
        self.rows = {}
        with (orbit_root / "samples.csv").open() as handle:
            for row in csv.DictReader(handle):
                self.rows[int(row["trace_sample_id"])] = row
        self.passes = {}
        with (orbit_root / "passes.csv").open() as handle:
            for row in csv.DictReader(handle):
                self.passes[int(row["pass_id"])] = row
        x, y, z = [], [], []
        for row in self.rows.values():
            x.append(float(row["position_x_m"]))
            y.append(float(row["position_y_m"]))
            z.append(float(row["position_z_m"]))
        locations = EarthLocation.from_geocentric(x, y, z, unit=u.m)
        lon, lat, unused_height = locations.to_geodetic("WGS84")
        station_lon = self.station["longitude_deg"] * u.deg
        station_lat = self.station["latitude_deg"] * u.deg
        angles = angular_separation(station_lon, station_lat, lon, lat)
        maximum = float(angles.max().to_value(u.deg))
        # A 10% angular margin is a display choice, not an RF coverage claim.
        radius = maximum * 1.10
        ring = []
        for bearing in range(0, 361, 2):
            ring_lon, ring_lat = offset_by(station_lon, station_lat, bearing * u.deg, radius * u.deg)
            longitude = (ring_lon.to_value(u.deg) + 180) % 360 - 180
            ring.append([float(longitude), float(ring_lat.to_value(u.deg))])
        longitudes, latitudes = [], []
        for point in ring:
            longitudes.append(point[0])
            latitudes.append(point[1])
        west, east = min(longitudes), max(longitudes)
        south, north = min(latitudes), max(latitudes)
        slant_ranges = []
        for row in self.passes.values():
            slant_ranges.append(float(row["max_slant_range_m"]))
        self.region = {
            "station": self.station, "bounds": [west, east, south, north],
            "maximumGroundAngleDeg": maximum, "marginFraction": 0.10,
            "displayRadiusDeg": radius, "boundary": ring,
            "minimumElevationDeg": self.station["elevation_mask_deg"],
            "maximumSlantRangeKm": max(slant_ranges) / 1000,
            "satellite": metadata["orbit"]["omm_fields"]["OBJECT_NAME"],
            "norad": int(metadata["orbit"]["omm_fields"]["NORAD_CAT_ID"]),
            "epoch": self.metadata["epoch"], "datasetId": dataset.dataset_id,
        }

    def decode(self, event):
        """Validate one received frame and return its geographic telemetry.

        References:
            Astropy 8.0.1 API, EarthLocation.from_geocentric and to_geodetic,
            Parameters and Returns; https://docs.astropy.org/en/stable/api/astropy.coordinates.EarthLocation.html
            Protocol checks are delegated to the production CCSDS decoder.

        Processing flow:
            Check PHY and frame -> validate headers and diagnostic bytes
            -> decode record -> convert ECEF -> associate exact archive bytes.

        Direct call tree (static source order):
            decode
            +-- bytes.fromhex
            +-- event.get
            +-- ValueError
            +-- validate_tm_frame
            +-- decode_tm_and_space_headers
            +-- unpack_mission_record
            +-- validation_pattern
            +-- any
            +-- EarthLocation.from_geocentric
            +-- location.to_geodetic
            +-- self.rows.get
            +-- int
            +-- float
            +-- lat.to_value
            +-- lon.to_value
            +-- height.to_value
            +-- frame.hex
            `-- math.isfinite
        """
        frame = bytes.fromhex(event["packet_hex"])
        if event.get("phy_crc_ok") != 1 or event.get("received_length") != 64:
            raise ValueError("PHY CRC or received length failed")
        if not validate_tm_frame(frame).valid:
            raise ValueError("Frame length or FECF failed")
        decode_tm_and_space_headers(frame)
        record = unpack_mission_record(frame[12:62])
        if frame[56:62] != validation_pattern(record.trace_sample_id):
            raise ValueError("Diagnostic pattern failed")
        if not any((record.position_x_m, record.position_y_m, record.position_z_m)):
            raise ValueError("Zero ECEF position has no geographic direction")
        location = EarthLocation.from_geocentric(record.position_x_m, record.position_y_m, record.position_z_m, unit=u.m)
        lon, lat, height = location.to_geodetic("WGS84")
        identifier = record.trace_sample_id
        row = self.rows.get(identifier)
        matched = row is not None and frame == self.frames[identifier * 64:(identifier + 1) * 64]
        pass_id = None
        if matched:
            pass_id = int(row["pass_id"])
        result = {
            "sample": identifier, "time": record.trace_time_ms / 1000,
            "range": record.slant_range_m / 1000, "doppler": record.doppler_millihz / 1000,
            "latitude": float(lat.to_value(u.deg)), "longitude": float(lon.to_value(u.deg)),
            "altitude": float(height.to_value(u.km)),
            "position": [record.position_x_m / 1000, record.position_y_m / 1000, record.position_z_m / 1000],
            "velocity": [record.velocity_x_mmps / 1e6, record.velocity_y_mmps / 1e6, record.velocity_z_mmps / 1e6],
            "rangeRate": record.range_rate_mmps / 1000,
            "passId": pass_id,
            "sourceMatched": matched,
            "frameHex": frame.hex(),
            "rssiRaw": event.get("rssi_raw"), "snrRaw": event.get("snr_raw"),
        }
        for name in ("latitude", "longitude", "altitude"):
            if not math.isfinite(result[name]):
                raise ValueError("Non-finite geographic coordinates")
        return result


class ReceivedSession:
    """Retain valid positions and separate pass occurrences within one log."""

    def __init__(self, path, reference):
        """Initialize a log cursor without altering its source file.

        Direct call tree (static source order):
            __init__
            `-- Path
        """
        self.path = Path(path)
        self.reference = reference
        self.offset = 0
        self.identity = None
        self.generation = 0
        self.samples = []
        self.tracks = []
        self.invalid = 0
        self.malformed = 0
        self.windows = 0
        self.total = 0
        self.state = "Waiting for receiver log"
        self.warning = ""
        self.last = None
        self.data_origin = "unknown"
        self.last_wire_utc_ns = None
        self.last_received_utc_ns = None

    def read_new(self):
        """Read complete new JSONL records while retaining earlier pass tracks.

        Processing flow:
            Check file identity -> handle reset as a new segment -> read complete
            lines -> validate packets -> retain positions or record diagnostics.

        Direct call tree (static source order):
            read_new
            +-- self.path.stat
            +-- self.path.open
            +-- handle.seek
            +-- handle.readline
            +-- line.endswith
            +-- handle.tell
            +-- json.loads
            +-- isinstance
            +-- ValueError
            `-- self._consume
        """
        try:
            info = self.path.stat()
            identity = (info.st_dev, info.st_ino)
            if self.identity is not None and (identity != self.identity or info.st_size < self.offset):
                self.offset = 0
                self.generation += 1
                self.last = None
                self.warning = "Log replaced or truncated; earlier tracks retained"
            self.identity = identity
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                while True:
                    line = handle.readline()
                    if not line or not line.endswith(b"\n"):
                        break
                    self.offset = handle.tell()
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError("Event must be an object")
                    except (ValueError, UnicodeDecodeError):
                        self.malformed += 1
                        continue
                    self._consume(event)
        except OSError as error:
            self.warning = f"Log unavailable: {error.strerror}"

    def _consume(self, event):
        """Apply a complete event to receiver status and validated pass history.

        Processing flow:
            Identify event -> update status or validate packet -> separate pass
            occurrence -> retain timestamp, raw bytes and received position.

        Direct call tree (static source order):
            _consume
            +-- event.get
            +-- str
            +-- self.reference.decode
            +-- len
            +-- self.tracks.append
            +-- isinstance
            `-- self.samples.append
        """
        kind = event.get("event")
        if kind == "wire" and event.get("direction") == 1:
            self.last_wire_utc_ns = event.get("utc_ns")
        elif kind == "run_start":
            self.data_origin = event.get("data_origin", "unknown")
            self.last = None
            self.last_wire_utc_ns = None
            self.last_received_utc_ns = None
            self.state = "Configuring receiver"
        elif kind in ("rx_armed", "rx_timeout"):
            self.state = "Waiting for valid frames"
            if kind == "rx_timeout":
                self.windows += 1
        elif kind == "summary":
            self.state = "Receiver stopped: " + str(event.get("status", "unknown"))
        elif kind == "error":
            self.state = "Receiver error"
        elif kind == "rx_packet":
            self.total += 1
            try:
                sample = self.reference.decode(event)
            except (ValueError, TypeError, KeyError, OverflowError):
                self.invalid += 1
                return
            previous = self.last
            new_track = previous is None
            if previous is not None:
                new_track = (sample["passId"] != previous["passId"] or
                             sample["time"] < previous["time"] or
                             sample["sample"] < previous["sample"])
            if new_track:
                key = f"{self.path.parent.name}:g{self.generation}:t{len(self.tracks) + 1}"
                label = "Unverified segment"
                if sample["sourceMatched"]:
                    label = f"Pass {sample['passId'] + 1}"
                self.tracks.append({"key": key, "label": label, "passId": sample["passId"],
                                    "session": self.path.parent.name, "count": 0})
            track = self.tracks[-1]
            sample["track"] = track["key"]
            sample["trackLabel"] = track["label"]
            sample["session"] = self.path.parent.name
            sample["duplicate"] = (previous is not None and sample["sample"] == previous["sample"] and sample["time"] == previous["time"])
            sample["eventIndex"] = event.get("index")
            # This timestamps host log processing, not the over-the-air arrival.
            timestamp = event.get("host_received_utc_ns", self.last_wire_utc_ns)
            self.last_received_utc_ns = None
            if isinstance(timestamp, int):
                self.last_received_utc_ns = timestamp
            sample["receivedUtcNs"] = self.last_received_utc_ns
            self.samples.append(sample)
            track["count"] += 1
            self.last = sample
            self.state = "Valid frame received; waiting for next frame"
            if not sample["sourceMatched"]:
                self.warning = "Received frame does not match the local reference dataset"
            elif self.warning == "Received frame does not match the local reference dataset":
                self.warning = ""


class ReceiverStore:
    """Poll chosen receive logs and preserve every visited session's tracks."""

    def __init__(self, receive_root, archive, fixed_events=None):
        """Configure the archive and the read-only log directory.

        Processing flow:
            Validate reference -> resolve an optional fixed log -> initialize store.

        Direct call tree (static source order):
            __init__
            +-- Path
            +-- OrbitReference
            `-- threading.Lock
        """
        self.root = Path(receive_root)
        self.reference = OrbitReference(archive)
        self.fixed_events = None
        if fixed_events:
            self.fixed_events = Path(fixed_events)
        self.sessions = {}
        self.lock = threading.Lock()

    def snapshot(self, selected="latest"):
        """Return newly validated data without advancing from archive-only points.

        Processing flow:
            Select an allowed source -> advance visited logs -> collect retained
            pass tracks -> report source status and validation counts.

        Direct call tree (static source order):
            snapshot
            +-- sorted
            +-- self.root.glob
            +-- str
            +-- chosen.resolve
            +-- ReceivedSession
            +-- self.sessions.values
            +-- session.read_new
            +-- sources.append
            +-- samples.extend
            +-- tracks.extend
            +-- self.sessions.get
            +-- len
            +-- datetime.now
            +-- datetime.now(...).isoformat
            `-- result.update
        """
        with self.lock:
            files = sorted(self.root.glob("*/events.jsonl"))
            if self.fixed_events is not None:
                files = [self.fixed_events]
            chosen = None
            if selected == "latest" and files:
                chosen = files[-1]
            else:
                for path in files:
                    if path.parent.name == selected:
                        chosen = path
                        break
            if chosen is not None:
                key = str(chosen.resolve())
                if key not in self.sessions:
                    self.sessions[key] = ReceivedSession(chosen, self.reference)
            for session in self.sessions.values():
                session.read_new()
            samples, tracks, sources = [], [], []
            invalid, malformed, received = 0, 0, 0
            for path in files:
                sources.append(path.parent.name)
            for session in self.sessions.values():
                samples.extend(session.samples)
                tracks.extend(session.tracks)
                invalid += session.invalid
                malformed += session.malformed
                received += session.total
            active = None
            source = None
            if chosen:
                source = chosen.parent.name
                active = self.sessions.get(str(chosen.resolve()))
            result = {
                "samples": samples, "tracks": tracks, "region": self.reference.region,
                "sources": sources, "source": source,
                "state": "Waiting for receiver log", "warning": "",
                "invalid": invalid, "malformed": malformed, "received": received,
                "valid": len(samples), "activeLatest": None, "dataOrigin": "unknown",
                "reference": self.reference.metadata, "lastReceivedUtcNs": None,
                "mode": "receiver_logs", "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            if active:
                result.update(state=active.state, warning=active.warning,
                              activeLatest=active.last, dataOrigin=active.data_origin,
                              lastReceivedUtcNs=active.last_received_utc_ns)
            return result
