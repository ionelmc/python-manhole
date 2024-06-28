#!/usr/bin/env python

import argparse
import errno
import os
import re
import readline
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


def parse_pid(value, regex=re.compile(r'^(.*/manhole-)?(?P<pid>\d+)$')):
    match = regex.match(value)
    if not match:
        raise argparse.ArgumentTypeError('PID must be in one of these forms: 1234 or /tmp/manhole-1234')

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
            raise argparse.ArgumentTypeError(
                'Invalid signal number {}. Expected one of: {}'.format(value, ', '.join(str(i) for i in SIG_NUMBERS))
            )
    value = value.upper()
    if value in SIG_NAMES:
        return SIG_NAMES[value]
    else:
        raise argparse.ArgumentTypeError(f'Invalid signal name {value!r}.')


parser = argparse.ArgumentParser(description='Connect to a manhole.')
parser.add_argument(
    'pid',
    metavar='PID',
    type=parse_pid,
    help='A numerical process id, or a path in the form: /tmp/manhole-1234',  # nargs='?',
)
parser.add_argument('-t', '--timeout', dest='timeout', default=1, type=float, help='Timeout to use. Default: %(default)s seconds.')
group = parser.add_mutually_exclusive_group()
group.add_argument(
    '-1',
    '-USR1',
    dest='signal',
    action='store_const',
    const=int(signal.SIGUSR1),
    help='Send USR1 (%(const)s) to the process before connecting.',
)
group.add_argument(
    '-2',
    '-USR2',
    dest='signal',
    action='store_const',
    const=int(signal.SIGUSR2),
    help='Send USR2 (%(const)s) to the process before connecting.',
)
group.add_argument(
    '-s', '--signal', dest='signal', type=parse_signal, metavar='SIGNAL', help='Send the given SIGNAL to the process before connecting.'
)


class ConnectionHandler(threading.Thread):
    def __init__(self, sock, is_closing):
        super().__init__()
        self.sock = sock
        self.is_closing = is_closing

    def run(self):
        while True:
            try:
                data = self.sock.recv(1024**2)
                if not data:
                    break
                sys.stdout.write(data.decode('utf8'))
                sys.stdout.flush()
                readline.redisplay()
            except socket.timeout:
                pass

        if not self.is_closing.is_set():
            # Break waiting for input()
            os.kill(os.getpid(), signal.SIGINT)


def main():
    args = parser.parse_args()

    histfile = os.path.join(os.path.expanduser('~'), '.manhole_history')
    try:
        readline.read_history_file(histfile)
    except OSError:
        pass
    import atexit

    atexit.register(readline.write_history_file, histfile)
    del histfile

    if args.signal:
        os.kill(args.pid, args.signal)

    start = time.time()
    uds_path = f'/tmp/manhole-{args.pid}'
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(args.timeout)
    while time.time() - start < args.timeout:
        try:
            sock.connect(uds_path)
        except Exception as exc:
            if exc.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                print(f'Failed to connect to {uds_path!r}: {exc!r}', file=sys.stderr)
        else:
            break
    else:
        print(f'Failed to connect to {uds_path!r}: Timeout', file=sys.stderr)
        sys.exit(5)

    is_closing = threading.Event()
    thread = ConnectionHandler(sock, is_closing)
    thread.start()

    try:
        while thread.is_alive():
            data = input()
            data += '\n'
            sock.sendall(data.encode('utf8'))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        is_closing.set()
        sock.shutdown(socket.SHUT_WR)
        thread.join()
        sock.close()
