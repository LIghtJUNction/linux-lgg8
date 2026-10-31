"""Pure unittest suite: no network, subprocess, temporary files or devices."""

from errno import EBUSY, EIO, ENODATA, ENXIO, EOPNOTSUPP, ETIMEDOUT
import unittest

from pm8150b_dma_model import (
    ARB, INTF, TEMP, FakeRegmap, Fault, decode_temperature, read_temperature,
)


def run(regmap, **kwargs):
    options = dict(initialized=True, battery_present=True, sample_fresh=True,
                   peek_configured=True)
    options.update(kwargs)
    return read_temperature(regmap, **options)


def stages(regmap):
    return [event[0] for event in regmap.trace]


class TemperatureTransactionTest(unittest.TestCase):
    def assert_released(self, regmap):
        events = stages(regmap)
        self.assertEqual(events[-4:], ["release_dma", "release_arb",
                                       "verify_dma", "verify_arb"])
        for name in events[-4:]:
            self.assertEqual(events.count(name), 1)

    def test_success_exact_bus_sequence_and_preserved_bits(self):
        regmap = FakeRegmap()
        result = run(regmap)
        self.assertEqual((result.rc, result.decicelsius, result.cleanup_verified),
                         (0, 250, True))
        self.assertEqual(regmap.trace, [
            ("preflight_dma", "read", 0x4350, 1),
            ("preflight_arb", "read", 0x4340, 1),
            ("preflight_grant", "read", 0x4310, 1),
            ("request_arb", "update_bits", 0x4340, 0x01, 0x01),
            ("request_dma", "update_bits", 0x4350, 0xA0, 0x80),
            ("delay", 40),
            ("grant_status", "read", 0x4310, 1),
            ("data", "read", 0x4858, 2),
            ("release_dma", "update_bits", 0x4350, 0xA0, 0),
            ("release_arb", "update_bits", 0x4340, 0x01, 0),
            ("verify_dma", "read", 0x4350, 1),
            ("verify_arb", "read", 0x4340, 1),
        ])
        self.assertEqual((regmap.registers[ARB], regmap.registers[INTF]), (2, 4))
        self.assertEqual(TEMP, 0x4858)

    def test_all_ten_bit_values_and_c_negative_rounding(self):
        for raw in range(1024):
            signed = raw if raw < 512 else raw - 1024
            expected = int(signed * 2.5)
            self.assertEqual(decode_temperature(raw.to_bytes(2, "little")), expected)
            self.assertEqual(decode_temperature((raw | 0xFC00).to_bytes(2, "little")),
                             expected)
        self.assertEqual(decode_temperature(b"\xff\x03"), -2)
        self.assertEqual(decode_temperature(b"\x00\x02"), -1280)
        self.assertEqual(decode_temperature(b"\xff\x01"), 1277)

    def test_each_request_failure_before_and_after_application(self):
        for stage in ("request_arb", "request_dma"):
            for applied in (False, True):
                with self.subTest(stage=stage, applied=applied):
                    regmap = FakeRegmap(faults={stage: Fault(ENXIO, applied)})
                    result = run(regmap)
                    self.assertEqual(result.rc, -ENXIO)
                    self.assertEqual(result.errors[0].stage, stage)
                    self.assertIsNone(result.decicelsius)
                    self.assertTrue(result.cleanup_verified)
                    self.assertNotIn("data", stages(regmap))
                    if stage == "request_arb":
                        self.assertNotIn("request_dma", stages(regmap))
                    self.assert_released(regmap)
                    self.assertEqual((regmap.registers[ARB], regmap.registers[INTF]),
                                     (2, 4))

    def test_grant_timeout_is_bounded_and_does_not_read_data(self):
        regmap = FakeRegmap(grant_after=None)
        result = run(regmap)
        self.assertEqual(result.rc, -ETIMEDOUT)
        self.assertEqual(regmap.polls, 50)
        self.assertEqual(regmap.elapsed_us, 500040)
        self.assertNotIn("data", stages(regmap))
        self.assertTrue(result.cleanup_verified)
        self.assert_released(regmap)

    def test_grant_on_final_poll(self):
        regmap = FakeRegmap(grant_after=49)
        self.assertEqual(run(regmap).rc, 0)
        self.assertEqual(regmap.polls, 50)
        self.assertEqual(regmap.elapsed_us, 490040)

    def test_grant_read_and_data_read_failures(self):
        for stage in ("grant_status", "data"):
            with self.subTest(stage=stage):
                regmap = FakeRegmap(faults={stage: Fault(ENXIO)})
                result = run(regmap)
                self.assertEqual(result.rc, -ENXIO)
                self.assertIsNone(result.decicelsius)
                self.assertTrue(result.cleanup_verified)
                self.assert_released(regmap)

    def test_short_data_is_not_published(self):
        regmap = FakeRegmap(short_data=True)
        result = run(regmap)
        self.assertEqual(result.rc, -EIO)
        self.assertEqual(result.errors[0].stage, "data_length")
        self.assertIsNone(result.decicelsius)
        self.assert_released(regmap)

    def test_cleanup_failure_matrix_preserves_primary_and_both_releases(self):
        for primary in (None, "request_arb", "request_dma", "grant_status", "data"):
            for failed in (("release_dma",), ("release_arb",),
                           ("release_dma", "release_arb")):
                for applied in (False, True):
                    with self.subTest(primary=primary, failed=failed, applied=applied):
                        faults = {stage: Fault(EIO, applied) for stage in failed}
                        if primary:
                            faults[primary] = Fault(ENXIO, True)
                        regmap = FakeRegmap(faults=faults)
                        result = run(regmap)
                        self.assertEqual(result.rc, -ENXIO if primary else -EIO)
                        self.assertIsNone(result.decicelsius)
                        self.assertFalse(result.cleanup_verified)
                        self.assertTrue(regmap.quarantined)
                        for stage in failed:
                            self.assertIn(stage, [e.stage for e in result.errors])
                        self.assert_released(regmap)
                        trace = list(regmap.trace)
                        self.assertEqual(run(regmap).rc, -EBUSY)
                        self.assertEqual(regmap.trace, trace)

    def test_timeout_and_both_cleanup_failures_remain_visible(self):
        regmap = FakeRegmap(grant_after=None, faults={
            "release_dma": Fault(), "release_arb": Fault(),
        })
        result = run(regmap)
        self.assertEqual(result.rc, -ETIMEDOUT)
        self.assertEqual([e.stage for e in result.errors], [
            "grant_timeout", "release_dma", "release_arb", "verify_dma", "verify_arb",
        ])
        self.assertIsNone(result.decicelsius)
        self.assert_released(regmap)

    def test_each_readback_failure_and_both(self):
        for failed in (("verify_dma",), ("verify_arb",),
                       ("verify_dma", "verify_arb")):
            with self.subTest(failed=failed):
                regmap = FakeRegmap(faults={stage: Fault(ENXIO) for stage in failed})
                result = run(regmap)
                self.assertEqual(result.rc, -ENXIO)
                self.assertFalse(result.cleanup_verified)
                self.assertIsNone(result.decicelsius)
                self.assertTrue(regmap.quarantined)
                self.assert_released(regmap)

    def test_prerequisites_reject_without_any_bus_operation(self):
        for options, code in [
            ({"initialized": False}, EOPNOTSUPP),
            ({"revision": "unknown"}, EOPNOTSUPP),
            ({"revision": "v1", "peek_configured": False}, EOPNOTSUPP),
            ({"revision": "v2", "peek_configured": False}, EOPNOTSUPP),
            ({"battery_present": False}, ENODATA),
            ({"sample_fresh": False}, ENODATA),
        ]:
            with self.subTest(options=options):
                regmap = FakeRegmap()
                result = run(regmap, **options)
                self.assertEqual(result.rc, -code)
                self.assertIsNone(result.cleanup_verified)
                self.assertEqual(regmap.trace, [])
        regmap = FakeRegmap()
        self.assertNotEqual(read_temperature(regmap).rc, 0)
        self.assertEqual(regmap.trace, [])

    def test_busy_peer_and_preflight_read_error_do_not_clear_requests(self):
        for address, bit in ((ARB, 1), (ARB, 0x04), (INTF, 0x80), (INTF, 0x20)):
            regmap = FakeRegmap()
            regmap.registers[address] |= bit
            before = dict(regmap.registers)
            self.assertEqual(run(regmap).rc, -EBUSY)
            self.assertEqual(regmap.registers, before)
            self.assertTrue(all(event[1] == "read" for event in regmap.trace))
        regmap = FakeRegmap(stale_grant=True)
        self.assertEqual(run(regmap).rc, -EBUSY)
        self.assertTrue(all(event[1] == "read" for event in regmap.trace))
        for stage in ("preflight_dma", "preflight_arb", "preflight_grant"):
            regmap = FakeRegmap(faults={stage: Fault()})
            self.assertEqual(run(regmap).rc, -EIO)
            self.assertNotIn("release_dma", stages(regmap))

    def test_v1_simulated_workaround_delays_and_order(self):
        regmap = FakeRegmap(alg_inactive_after=1)
        result = run(regmap, revision="v1", peek_configured=True)
        self.assertIn(("alg_status", "read", 0x41EF, 1), regmap.trace)
        self.assertEqual(result.rc, 0)
        self.assertEqual(regmap.alg_polls, 2)
        self.assertEqual(regmap.elapsed_us, 12040)
        events = stages(regmap)
        self.assertLess(events.index("alg_status"), events.index("request_arb"))
        data_index = events.index("data")
        self.assertEqual(regmap.trace[data_index - 1], ("delay", 1000))

    def test_v1_alg_timeout_or_read_failure_never_requests_or_cleans(self):
        for faults, expected in (({}, ETIMEDOUT), ({"alg_status": Fault()}, EIO)):
            regmap = FakeRegmap(alg_inactive_after=None, faults=faults)
            result = run(regmap, revision="v1", peek_configured=True)
            self.assertEqual(result.rc, -expected)
            self.assertIsNone(result.cleanup_verified)
            self.assertNotIn("request_arb", stages(regmap))
            self.assertNotIn("release_dma", stages(regmap))
            if not faults:
                self.assertEqual(regmap.alg_polls, 35)
                self.assertEqual(regmap.elapsed_us, 350000)

    def test_no_cached_temperature_after_previous_success(self):
        regmap = FakeRegmap()
        self.assertEqual(run(regmap).decicelsius, 250)
        regmap.faults["data"] = Fault()
        self.assertIsNone(run(regmap).decicelsius)
        trace = list(regmap.trace)
        self.assertEqual(run(regmap).rc, -EBUSY)
        self.assertEqual(regmap.trace, trace)

    def test_hardware_like_backend_and_subclass_are_rejected(self):
        class Backend(FakeRegmap):
            pass

        for backend in (object(), Backend()):
            with self.assertRaisesRegex(TypeError, "exact FakeRegmap"):
                run(backend)


if __name__ == "__main__":
    unittest.main()
