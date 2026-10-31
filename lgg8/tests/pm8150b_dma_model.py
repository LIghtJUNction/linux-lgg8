"""Offline-only Gen4 temperature transaction proposal; no hardware backend.

See PM8150B_DMA_DESIGN.md for pinned sources and deliberate deviations.
All addresses, timing and validity assertions describe simulated state only.
"""

from dataclasses import dataclass
from errno import EBUSY, EIO, ENODATA, EOPNOTSUPP, ETIMEDOUT
from threading import Lock


ARB = 0x4340
INTF = 0x4350
STATUS = 0x4310
PEEK = 0x41EF
TEMP = 0x4800 + 0x20 + (328 - 300) * 2
ARB_MASK = 0x01
ARB_CLEAR_LOG = 0x04
INTF_MASK = 0xA0
GRANT = 0x08


@dataclass(frozen=True)
class Error:
    stage: str
    code: int


@dataclass(frozen=True)
class Result:
    decicelsius: int | None
    errors: tuple[Error, ...] = ()
    # None means no request was attempted; True means fake readback verified.
    cleanup_verified: bool | None = None

    @property
    def rc(self):
        return -self.errors[0].code if self.errors else 0


@dataclass(frozen=True)
class Fault:
    code: int = EIO
    # A write can take effect even if the bus reports failure.
    applied: bool = False


class BusError(Exception):
    def __init__(self, stage, code):
        self.error = Error(stage, code)


class FakeRegmap:
    """In-memory register image with stage-based fault injection and trace.

    update_bits always models a bus attempt, including an already-clear bit.
    A real regmap implementation may elide such writes; this is not its driver.
    Every transaction sharing this image uses the same lock and quarantine.
    """

    def __init__(self, *, raw=100, grant_after=0, alg_inactive_after=0,
                 stale_grant=False,
                 faults=None, short_data=False):
        self.registers = {ARB: 0x02, INTF: 0x04, TEMP: raw & 0xFF,
                          TEMP + 1: (raw >> 8) & 0xFF}
        self.grant_after = grant_after
        self.stale_grant = stale_grant
        self.alg_inactive_after = alg_inactive_after
        self.faults = dict(faults or {})
        self.short_data = short_data
        self.trace = []
        self.elapsed_us = 0
        self.polls = 0
        self.alg_polls = 0
        self.lock = Lock()
        self.quarantined = False

    def _check(self, stage):
        fault = self.faults.get(stage)
        if fault:
            raise BusError(stage, fault.code)

    def update_bits(self, stage, address, mask, value):
        assert (address, mask) in ((ARB, ARB_MASK), (INTF, INTF_MASK))
        self.trace.append((stage, "update_bits", address, mask, value))
        fault = self.faults.get(stage)
        if fault is None or fault.applied:
            old = self.registers[address]
            self.registers[address] = (old & ~mask) | (value & mask)
        self._check(stage)

    def read(self, stage, address, length=1):
        assert (address, length) in ((ARB, 1), (INTF, 1), (STATUS, 1),
                                     (PEEK, 1), (TEMP, 2))
        self.trace.append((stage, "read", address, length))
        self._check(stage)
        if address == STATUS:
            if stage == "preflight_grant":
                return bytes([GRANT if self.stale_grant else 0])
            granted = (self.grant_after is not None
                       and self.polls >= self.grant_after)
            self.polls += 1
            return bytes([GRANT if granted else 0])
        if address == PEEK:
            inactive = (self.alg_inactive_after is not None
                        and self.alg_polls >= self.alg_inactive_after)
            self.alg_polls += 1
            return bytes([0 if inactive else 0x08])
        data = bytes(self.registers[address + i] for i in range(length))
        return data[:1] if address == TEMP and self.short_data else data

    def delay(self, microseconds):
        self.trace.append(("delay", microseconds))
        self.elapsed_us += microseconds


def decode_temperature(data):
    """Little endian, sign extend bit 9, C integer division toward zero."""
    if len(data) != 2:
        raise BusError("data_length", EIO)
    raw = int.from_bytes(data, "little") & 0x3FF
    signed = raw - 0x400 if raw & 0x200 else raw
    magnitude = abs(signed) * 100 // 40
    return -magnitude if signed < 0 else magnitude


def read_temperature(regmap, *, revision="v2", peek_configured=False,
                     initialized=False, battery_present=False,
                     sample_fresh=False):
    """Run only on an exact FakeRegmap; prerequisites are synthetic assertions.

    No object exposing hardware methods can be supplied as a backend.
    No automatic retry or recovery after uncertain release is provided.
    """
    if type(regmap) is not FakeRegmap:
        raise TypeError("offline model requires an exact FakeRegmap")
    with regmap.lock:
        if revision not in ("v1", "v2") or not initialized:
            return Result(None, (Error("unsupported_or_uninitialized", EOPNOTSUPP),))
        if not peek_configured:
            return Result(None, (Error("peek_unverified", EOPNOTSUPP),))
        if not battery_present or not sample_fresh:
            return Result(None, (Error("missing_or_stale_sample", ENODATA),))
        if regmap.quarantined:
            return Result(None, (Error("quarantined", EBUSY),))

        errors = []
        requested = False
        temperature = None
        try:
            # Proposal: refuse to clear requests potentially owned by a peer.
            for stage, address, mask in (("preflight_dma", INTF, INTF_MASK),
                                         ("preflight_arb", ARB,
                                          ARB_MASK | ARB_CLEAR_LOG)):
                if regmap.read(stage, address)[0] & mask:
                    raise BusError(stage, EBUSY)
            if regmap.read("preflight_grant", STATUS)[0] & GRANT:
                raise BusError("preflight_grant", EBUSY)
            if revision == "v1":
                for _ in range(35):
                    if not regmap.read("alg_status", PEEK)[0] & 0x08:
                        regmap.delay(1000)
                        break
                    regmap.delay(10000)
                else:
                    raise BusError("alg_timeout", ETIMEDOUT)

            # Mark before the first write: its failure may still change state.
            requested = True
            regmap.update_bits("request_arb", ARB, ARB_MASK, ARB_MASK)
            regmap.update_bits("request_dma", INTF, INTF_MASK, 0x80)
            regmap.delay(40)
            for _ in range(50):
                if regmap.read("grant_status", STATUS)[0] & GRANT:
                    if revision == "v1":
                        regmap.delay(1000)
                    break
                regmap.delay(10000)
            else:
                raise BusError("grant_timeout", ETIMEDOUT)
            temperature = decode_temperature(regmap.read("data", TEMP, 2))
        except BusError as exc:
            errors.append(exc.error)
        finally:
            if requested:
                # Both releases run even if the first fails. No retry loops.
                for stage, address, mask in (("release_dma", INTF, INTF_MASK),
                                             ("release_arb", ARB, ARB_MASK)):
                    try:
                        regmap.update_bits(stage, address, mask, 0)
                    except BusError as exc:
                        errors.append(exc.error)
                # Verify independently, never erase an earlier write error.
                for stage, address, mask in (("verify_dma", INTF, INTF_MASK),
                                             ("verify_arb", ARB, ARB_MASK)):
                    try:
                        if regmap.read(stage, address)[0] & mask:
                            raise BusError(stage, EIO)
                    except BusError as exc:
                        errors.append(exc.error)

        cleanup_errors = any(e.stage.startswith(("release_", "verify_"))
                             for e in errors)
        if requested and errors:
            regmap.quarantined = True
        verified = not cleanup_errors if requested else None
        return Result(None if errors else temperature, tuple(errors), verified)
