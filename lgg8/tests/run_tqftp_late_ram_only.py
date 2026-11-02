#!/usr/bin/env python3
"""Same TFTP image, publish after MPSS ready and before RMTFS publication."""
import run_tqftp_ram_only as tq


def tasks(probe_path=None):
    original = tq.tasks(probe_path)
    start = next(row for row in original if row[0] == 'start')
    return [original[0], start, *(row for row in original[1:] if row[0] != 'start')]


def configure():
    tq.configure()
    tq.base.RECORD_PREFIX = 'tqftp-late'
    tq.base.REQUESTED_SCOPE = 'publish TFTP after MPSS ready; bounded RAM writes and private EFS shadow'
    tq.base.tasks = tasks


if __name__ == '__main__':
    configure()
    tq.base.main()
