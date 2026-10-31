#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ACTION=${1:-help}
if [[ "$ACTION" == help || "$ACTION" == --help ]]; then
    cat <<'EOF'
Usage: ./lgg8/build.sh {kernel|dtb|diag-ftrace|diag-pstore|initramfs|boot|test|verify} [OUT]
OUT defaults to <repository>/out/lgg8. No phone commands are executed.
kernel:    build Image + qcom/sm8150-lg-alphalm.dtb (JOBS defaults to 2)
dtb:       rebuild only the board device tree for a short local iteration
diag-ftrace: build Image + DTB with filtered persistent function tracing support
diag-pstore: build Image + DTB with the one-shot DPU ramoops recorder
initramfs: build a static diagnostic PID 1 with a 45-second reset deadline
boot:      package existing outputs; requires TEMPLATE_DIR and PARTITION_SIZE
           Optional INITRAMFS, CMDLINE_FILE, BOOT_OUTPUT override inputs/output.
verify:    verify BOOT_OUTPUT (default OUT/boot) against its manifest
test:      run local packaging and initramfs unit tests
EOF
    exit 0
fi
case "$ACTION" in kernel|dtb|diag-ftrace|diag-pstore|initramfs|boot|verify|test) ;; *) echo "Unknown action: $ACTION" >&2; exit 2;; esac
if [[ "$ACTION" == test ]]; then
    exec python3 -m unittest discover -s "$ROOT/lgg8/tests" -p 'test_*.py' -v
fi
OUT=$(realpath -m -- "${2:-$ROOT/out/lgg8}")
if [[ "$OUT" == / || "$OUT" == "$ROOT" || "$OUT" == "$ROOT/lgg8" ]]; then
    echo 'OUT must be a dedicated build directory.' >&2; exit 2
fi
mkdir -p -- "$OUT"
if [[ ! -e "$OUT/.lgg8-build" ]]; then
    if [[ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        echo 'Refusing to use a nonempty directory without .lgg8-build marker.' >&2; exit 2
    fi
    : > "$OUT/.lgg8-build"
fi
# Commit timestamp of the pinned v7.3 base; also works from a source archive.
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1792365298}
[[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || { echo 'Invalid SOURCE_DATE_EPOCH' >&2; exit 2; }
KBUILD_BUILD_TIMESTAMP=$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S UTC')
export SOURCE_DATE_EPOCH KBUILD_BUILD_TIMESTAMP
export KBUILD_BUILD_USER=lgg8 KBUILD_BUILD_HOST=builder KBUILD_BUILD_VERSION=1
# Keep the release string independent of staged/dirty Git state.
export LOCALVERSION=${LOCALVERSION-}

case "$ACTION" in
kernel|dtb|diag-ftrace|diag-pstore)
    JOBS=${JOBS:-2}
    [[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo 'JOBS must be positive.' >&2; exit 2; }
    python3 - "$OUT" "$ACTION" <<'PY'
import shutil, sys
free = shutil.disk_usage(sys.argv[1]).free
needed = 4 * 1024**3 if sys.argv[2] in ('kernel', 'diag-pstore') else 256 * 1024**2
if free < needed:
    raise SystemExit(f'Build requires at least {needed} bytes free space.')
PY
    mkdir -p -- "$OUT/kernel"
    CONFIG_INPUTS=("$ROOT/lgg8/configs/lgg8.config")
    CONFIG_PROFILE="base"
    if [[ "$ACTION" == diag-ftrace ]]; then
        CONFIG_INPUTS+=("$ROOT/lgg8/configs/pstore-ftrace-diagnostic.config")
        CONFIG_PROFILE="diag-ftrace"
    elif [[ "$ACTION" == diag-pstore ]]; then
        CONFIG_INPUTS+=("$ROOT/lgg8/configs/dpu-pstore-diagnostic.config")
        CONFIG_PROFILE="diag-pstore"
    fi
    CONFIG_PROFILE="$CONFIG_PROFILE:$(sha256sum "${CONFIG_INPUTS[@]}" | sha256sum | cut -d' ' -f1)"
    CONFIG_PROFILE_FILE="$OUT/kernel/.lgg8-config-profile"
    if [[ ! -f "$CONFIG_PROFILE_FILE" ||
          "$(cat "$CONFIG_PROFILE_FILE")" != "$CONFIG_PROFILE" ]]; then
        cp -- "$ROOT/lgg8/configs/lgg8.config" "$OUT/kernel/.config"
        if [[ "$ACTION" == diag-ftrace ]]; then
            "$ROOT/scripts/kconfig/merge_config.sh" -m -O "$OUT/kernel" \
                "$OUT/kernel/.config" "$ROOT/lgg8/configs/pstore-ftrace-diagnostic.config"
        elif [[ "$ACTION" == diag-pstore ]]; then
            "$ROOT/scripts/kconfig/merge_config.sh" -m -O "$OUT/kernel" \
                "$OUT/kernel/.config" "$ROOT/lgg8/configs/dpu-pstore-diagnostic.config"
        fi
    fi
    make -C "$ROOT" O="$OUT/kernel" ARCH=arm64 LLVM=1 olddefconfig
    printf '%s\n' "$CONFIG_PROFILE" > "$CONFIG_PROFILE_FILE"
    TARGETS=(qcom/sm8150-lg-alphalm.dtb)
    [[ "$ACTION" == dtb ]] || TARGETS=(Image "${TARGETS[@]}")
    make -C "$ROOT" O="$OUT/kernel" ARCH=arm64 LLVM=1 -j"$JOBS" "${TARGETS[@]}"
    if [[ "$ACTION" != dtb ]]; then
        python3 "$ROOT/lgg8/tools/bootimg.py" record-kernel-build \
            --kernel "$OUT/kernel/arch/arm64/boot/Image" \
            --dtb "$OUT/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb" \
            --config "$OUT/kernel/.config" --profile "$ACTION" \
            --output "$OUT/kernel/build-provenance.json"
    fi
    ;;
initramfs)
    mkdir -p -- "$OUT/initramfs"
    "${CROSS_COMPILE:-aarch64-linux-gnu-}gcc" -static -Os -Wall -Wextra -Werror \
        -ffile-prefix-map="$ROOT"=. -Wl,--build-id=none -s \
        "$ROOT/lgg8/initramfs/init.c" -o "$OUT/initramfs/init"
    python3 "$ROOT/lgg8/tools/mkinitramfs.py" \
        --init "$OUT/initramfs/init" --output "$OUT/initramfs/initramfs.cpio"
    ;;
boot)
    : "${TEMPLATE_DIR:?Set TEMPLATE_DIR to your private verified boot template directory}"
    : "${PARTITION_SIZE:?Set PARTITION_SIZE to the measured boot partition size in bytes}"
    python3 "$ROOT/lgg8/tools/bootimg.py" build \
        --kernel "$OUT/kernel/arch/arm64/boot/Image" \
        --dtb "$OUT/kernel/arch/arm64/boot/dts/qcom/sm8150-lg-alphalm.dtb" \
        --config "$OUT/kernel/.config" \
        --build-provenance "$OUT/kernel/build-provenance.json" \
        --initramfs "${INITRAMFS:-$OUT/initramfs/initramfs.cpio}" \
        --template "$TEMPLATE_DIR" \
        --cmdline-file "${CMDLINE_FILE:-$ROOT/lgg8/boot/cmdline.txt}" \
        --partition-size "$PARTITION_SIZE" \
        --output "${BOOT_OUTPUT:-$OUT/boot}"
    ;;
verify)
    python3 "$ROOT/lgg8/tools/bootimg.py" verify \
        --image "${BOOT_OUTPUT:-$OUT/boot}/boot.img" \
        --manifest "${BOOT_OUTPUT:-$OUT/boot}/manifest.json"
    ;;
esac
