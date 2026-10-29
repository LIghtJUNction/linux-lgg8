#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check an LG G8 (lge,alphalm) DTB's static TLMM GPIO contract.

Only enabled consumers with enabled ancestors count. Follow direct GPIO
specifiers and referenced pinctrl states (including available mux/conf children),
not unused state definitions. All referenced states, including sleep, are checked;
this does not prove that a driver selects them, or cover runtime/IRQ-only uses.
This independent check does not change the generic bootimg parser or build flow.
"""
import argparse
from pathlib import Path
import re
import struct
import sys
import types


# Reuse the sibling parser, also under isolated/spec-based imports, without
# writing __pycache__ or changing sys.path.
_source = Path(__file__).resolve().with_name("bootimg.py")
_boot = types.ModuleType("_gpio_contract_bootimg")
_boot.__file__ = str(_source)
exec(compile(_source.read_bytes(), str(_source), "exec"), _boot.__dict__)
Fdt = _boot.Fdt
require = _boot.require

FIRMWARE_FORBIDDEN = frozenset((*range(92, 96), *range(98, 102)))
GPIO_COUNT = 176  # qcom,sm8150-pinctrl: GPIO0..174 and UFS_RESET=175.


def cells(value, where):
    require(len(value) % 4 == 0, f"{where}: truncated cell array")
    return struct.unpack(f">{len(value) // 4}I", value)


def strings(value, where):
    require(value.endswith(b"\0"), f"{where}: unterminated string list")
    return value[:-1].decode("ascii").split("\0")


def parent(path):
    return path.rsplit("/", 1)[0] or "/"


def available(props):
    # of_device_is_available(): absent status, "ok", or "okay".
    return props.get("status", b"okay\0").split(b"\0", 1)[0] in (b"ok", b"okay")


def enabled(tree, path):
    while True:
        if not available(tree.nodes[path]):
            return False
        if path == "/":
            return True
        path = parent(path)


def check(tree):
    """Return the checked TLMM uses, or raise ValueError with paths and pins."""
    root = strings(tree.nodes["/"].get("compatible", b""), "/ compatible")
    require({"lge,alphalm", "qcom,sm8150"} <= set(root),
            "requires the LG G8 lge,alphalm / qcom,sm8150 profile")
    controllers = [path for path, props in tree.nodes.items()
                   if "qcom,sm8150-pinctrl" in
                   strings(props.get("compatible", b"\0"), path + " compatible")]
    require(len(controllers) == 1, "expected exactly one qcom,sm8150-pinctrl TLMM")
    tlmm = controllers[0]
    props = tree.nodes[tlmm]
    require(enabled(tree, tlmm) and "gpio-controller" in props,
            f"{tlmm}: TLMM GPIO controller must be enabled")
    require(cells(props.get("#gpio-cells", b""), tlmm + " #gpio-cells") == (2,),
            f"{tlmm}: expected #gpio-cells = <2>")

    handles = {}
    for path, node in tree.nodes.items():
        values = [cells(node[key], path + " " + key)
                  for key in ("phandle", "linux,phandle") if key in node]
        if not values:
            continue
        require(all(len(v) == 1 and 0 < v[0] < 0xffffffff for v in values)
                and len(set(values)) == 1, f"{path}: invalid/conflicting phandle")
        handle = values[0][0]
        require(handle not in handles, f"{path}: duplicate phandle {handle:#x}")
        handles[handle] = path
    require(tlmm in handles.values(), f"{tlmm}: missing TLMM phandle")

    ranges = cells(props.get("gpio-reserved-ranges", b""), tlmm + " gpio-reserved-ranges")
    require(len(ranges) % 2 == 0, f"{tlmm}: gpio-reserved-ranges needs start/count pairs")
    reserved = set()
    for start, count in zip(ranges[::2], ranges[1::2]):
        require(count > 0 and start + count <= GPIO_COUNT,
                f"{tlmm}: invalid reserved GPIO range {start}+{count}")
        reserved.update(range(start, start + count))
    errors = [f"{tlmm} gpio-reserved-ranges: missing firmware-forbidden GPIO{pin}"
              for pin in sorted(FIRMWARE_FORBIDDEN - reserved)]
    uses = []

    def use(consumer, prop, target, pin):
        require(0 <= pin < GPIO_COUNT, f"{consumer} {prop}: invalid TLMM GPIO{pin}")
        uses.append((consumer, prop, target, pin))
        if pin in reserved:
            errors.append(f"{consumer} {prop} -> {target}: reserved TLMM GPIO{pin}")

    def resolve(handle, where):
        require(handle in handles, f"{where}: unresolved phandle {handle:#x}")
        return handles[handle]

    children = {}
    for path in tree.nodes:
        if path != "/":
            children.setdefault(parent(path), []).append(path)

    def state_pins(consumer, prop, state):
        node = tree.nodes[state]
        key = "pins" if "pins" in node else "groups"
        for name in strings(node.get(key, b"\0"), state + " " + key):
            match = re.fullmatch(r"gpio([0-9]+)", name)
            if match or name == "ufs_reset":
                use(consumer, prop, state, int(match[1]) if match else 175)
        for child in children.get(state, []):
            if available(tree.nodes[child]):
                state_pins(consumer, prop, child)

    for path, node in tree.nodes.items():
        if not enabled(tree, path):
            continue
        for prop, value in node.items():
            if prop not in ("gpio", "gpios") and not prop.endswith(("-gpio", "-gpios")):
                continue
            words = cells(value, path + " " + prop)
            cursor = 0
            while cursor < len(words):
                # GPIO hogs use parent-relative specifiers, not phandles.
                if prop == "gpios" and "gpio-hog" in node:
                    provider = parent(path)
                else:
                    handle = words[cursor]
                    cursor += 1
                    if handle == 0:  # Standard empty GPIO list entry.
                        continue
                    provider = resolve(handle, path + " " + prop)
                count = cells(tree.nodes[provider].get("#gpio-cells", b""),
                              provider + " #gpio-cells")
                require(len(count) == 1 and 0 < count[0] <= 16,
                        f"{provider}: invalid #gpio-cells")
                require(cursor + count[0] <= len(words), f"{path} {prop}: truncated GPIO specifier")
                if provider == tlmm:
                    use(path, prop, provider, words[cursor])
                cursor += count[0]

        # pinctrl_dt_to_map() stops at the first missing consecutive state ID.
        index = 0
        while f"pinctrl-{index}" in node:
            prop = f"pinctrl-{index}"
            for handle in cells(node[prop], path + " " + prop):
                state = resolve(handle, path + " " + prop)
                if state == tlmm or state.startswith(tlmm + "/"):
                    state_pins(path, prop, state)
            index += 1
    require(not errors, "\n".join(errors))
    return {"tlmm": tlmm, "reserved": sorted(reserved), "uses": uses}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dtb", required=True, type=Path, help="compiled LG G8 board DTB")
    args = parser.parse_args(argv)
    try:
        result = check(Fdt(args.dtb.read_bytes()))
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {args.dtb}: firmware pins covered; {len(result['reserved'])} reserved GPIOs, "
          f"{len(result['uses'])} TLMM uses checked (static contract only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
