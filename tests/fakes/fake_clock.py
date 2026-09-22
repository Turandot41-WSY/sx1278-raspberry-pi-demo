"""A manually advanced clock for deterministic runner tests."""


class FakeClock:
    """Expose monotonic and UTC nanoseconds without reading the real clock."""

    def __init__(
        self,
        monotonic_ns: int = 0,
        utc_ns: int = 1_788_480_000_000_000_000,
    ) -> None:
        """Initialize FakeClock with the supplied dependencies and state.

        Inputs: monotonic_ns, utc_ns.
        Returns: None.

        Direct call tree (static source order):
            __init__
            `-- [no direct function calls; local state/return only]
        """
        self._monotonic_ns = monotonic_ns
        self._utc_ns = utc_ns

    def monotonic_ns(self) -> int:
        """Return the manually controlled monotonic time.

        Direct call tree (static source order):
            monotonic_ns
            `-- [no direct function calls; local state/return only]
        """
        return self._monotonic_ns

    def utc_ns(self) -> int:
        """Return UTC time advanced by the same elapsed duration.

        Direct call tree (static source order):
            utc_ns
            `-- [no direct function calls; local state/return only]
        """
        return self._utc_ns + self._monotonic_ns

    def sleep_ms(self, milliseconds: int) -> None:
        """Advance both clock views instead of blocking the test process.

        Direct call tree (static source order):
            sleep_ms
            `-- [no direct function calls; local state/return only]
        """
        self._monotonic_ns += milliseconds * 1_000_000
