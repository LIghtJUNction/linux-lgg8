#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
printf '\033]0;LG G8 Mainline Desktop\007'
printf '\nLG G8 MAINLINE LINUX\nAlpine 3.24 / Weston / Pixman\nNative AArch64 terminal in a RAM-only root.\n\n'
printf 'LGG8_TERMINAL_SHELL_EXECUTED pid=%s\n' "$$" >> /run/desktop-events.log
export PS1='lgg8-ram:/# '
exec /bin/sh
