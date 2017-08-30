#!/usr/bin/env python
from __future__ import print_function

import argparse
import errno
import os
import re
import readline
import select
import signal
import socket
import sys
import threading
import time

try:
    input = raw_input
except NameError:
    pass

SIG_NAMES = {}
SIG_NUMBERS = set()
for sig, num in vars(signal).items():
    if sig.startswith('SIG') and '_' not in sig:
        SIG_NAMES[sig] = num
        SIG_NAMES[sig[3:]] = num
        SIG_NUMBERS.add(num)


def parse_pid(value, regex=re.compile(r'^(/tmp/manhole-)?(?P<pid>\d+)$')):
    match = regex.match(value)
    if not match:
        raise argparse.ArgumentTypeError("PID must be in one of these forms: 1234 or /tmp/manhole-1234")

    return int(match.group('pid'))


def parse_signal(value):
    try:
        value = int(value)
    except ValueError:
        pass
    else:
        if value in SIG_NUMBERS:
            return value
        else:
            raise argparse.ArgumentTypeError("Invalid signal number %s. Expected one of: %s" % (
                value, ', '.join(str(i) for i in SIG_NUMBERS)
            ))
    value = value.upper()
    if value in SIG_NAMES:
        return SIG_NAMES[value]
    else:
        raise argparse.ArgumentTypeError("Invalid signal name %r." % value)


parser = argparse.ArgumentParser(description='Connect to a manhole.')
parser.add_argument('pid', metavar='PID', type=parse_pid,  # nargs='?',
                    help='A numerical process id, or a path in the form: /tmp/manhole-1234')
parser.add_argument('-t', '--timeout', dest='timeout', default=1, type=float,
                    help='Timeout to use. Default: %(default)s seconds.')
group = parser.add_mutually_exclusive_group()
group.add_argument('-1', '-USR1', dest='signal', action='store_const', const=int(signal.SIGUSR1),
                   help='Send USR1 (%(const)s) to the process before connecting.')
group.add_argument('-2', '-USR2', dest='signal', action='store_const', const=int(signal.SIGUSR2),
                   help='Send USR2 (%(const)s) to the process before connecting.')
group.add_argument('-s', '--signal', dest='signal', type=parse_signal, metavar="SIGNAL",
                   help='Send the given SIGNAL to the process before connecting.')


class ConnectionHandler(threading.Thread):
    def __init__(self, timeout, sock, read_fd=None, wait_the_end=True):
        super(ConnectionHandler, self).__init__()
        self.sock = sock
        self.read_fd = read_fd
        self.conn_fd = sock.fileno()
        self.timeout = timeout
        self.should_run = True
        self._poller = select.poll()
        self.wait_the_end = wait_the_end

    def run(self):
        if self.read_fd is not None:
            self._poller.register(self.read_fd, select.POLLIN | select.POLLPRI | select.POLLERR | select.POLLHUP)
        self._poller.register(self.conn_fd, select.POLLIN | select.POLLPRI | select.POLLERR | select.POLLHUP)

        while self.should_run:
            self.poll()
        if self.wait_the_end:
            t = time.time()
            while time.time() - t < self.timeout:
                self.poll()

    def poll(self):
        for fd, _ in self._poller.poll(self.timeout):
            if fd == self.conn_fd:
                data = self.sock.recv(1024*1024)
                sys.stdout.write(data.decode('utf8'))
                sys.stdout.flush()
                readline.redisplay()
            elif fd == self.read_fd:
                data = os.read(self.read_fd, 1024)
                self.sock.sendall(data)
            else:
                raise RuntimeError("Unknown FD %s" % fd)


def main():
    args = parser.parse_args()

    histfile = os.path.join(os.path.expanduser("~"), ".manhole_history")
    try:
        readline.read_history_file(histfile)
    except IOError:
        pass
    import atexit

    atexit.register(readline.write_history_file, histfile)
    del histfile

    if args.signal:
        os.kill(args.pid, args.signal)

    start = time.time()
    uds_path = '/tmp/manhole-%s' % args.pid
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(args.timeout)
    while time.time() - start < args.timeout:
        try:
            sock.connect(uds_path)
        except Exception as exc:
            if exc.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                print("Failed to connect to %r: %r" % (uds_path, exc), file=sys.stderr)
        else:
            break
    else:
        print("Failed to connect to %r: Timeout" % uds_path, file=sys.stderr)
        sys.exit(5)

    read_fd, write_fd = os.pipe()

    thread = ConnectionHandler(args.timeout, sock, read_fd, not sys.stdin.isatty())
    thread.start()

    try:
        while thread.is_alive():
            try:
                data = input()
            except EOFError:
                break
            os.write(write_fd, data.encode('utf8'))
            os.write(write_fd, b'\n')
    except KeyboardInterrupt:
        pass
    finally:
        thread.should_run = False
        thread.join()
