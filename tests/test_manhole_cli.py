from __future__ import print_function

import os
import signal
import sys

import pytest
from process_tests import TestProcess
from process_tests import dump_on_error
from process_tests import wait_for_strings

try:
    import subprocess32 as subprocess
except ImportError:
    import subprocess

TIMEOUT = int(os.getenv('MANHOLE_TEST_TIMEOUT', 10))
HELPER = os.path.join(os.path.dirname(__file__), 'helper.py')

pytest_plugins = 'pytester',


def test_pid_validation():
    exc = pytest.raises(subprocess.CalledProcessError, subprocess.check_output, ['manhole-cli', 'asdfasdf'],
                        stderr=subprocess.STDOUT)
    assert exc.value.output == b"""usage: manhole-cli [-h] [-t TIMEOUT] [-1 | -2 | -s SIGNAL] PID
manhole-cli: error: argument PID: PID must be in one of these forms: 1234 or /tmp/manhole-1234
"""


def test_sig_number_validation():
    exc = pytest.raises(subprocess.CalledProcessError, subprocess.check_output,
                        ['manhole-cli', '-s', '12341234', '12341234'], stderr=subprocess.STDOUT)
    assert exc.value.output.startswith(b"""usage: manhole-cli [-h] [-t TIMEOUT] [-1 | -2 | -s SIGNAL] PID
manhole-cli: error: argument -s/--signal: Invalid signal number 12341234. Expected one of: """)


def test_help(testdir):
    result = testdir.run('manhole-cli', '--help')
    result.stdout.fnmatch_lines([
        'usage: manhole-cli [-h] [-t TIMEOUT] [-1 | -2 | -s SIGNAL] PID',
        'Connect to a manhole.',
        'positional arguments:',
        '  PID                   A numerical process id, or a path in the form:',
        '                        /tmp/manhole-1234',
        'optional arguments:',
        '  -h, --help            show this help message and exit',
        '  -t TIMEOUT, --timeout TIMEOUT',
        '                        Timeout to use. Default: 1 seconds.',
        '  -1, -USR1             Send USR1 (*) to the process before connecting.',
        '  -2, -USR2             Send USR2 (*) to the process before connecting.',
        '  -s SIGNAL, --signal SIGNAL',
        '                        Send the given SIGNAL to the process before',
        '                        connecting.',
    ])


def test_usr2():
    with TestProcess(sys.executable, '-u', HELPER, 'test_oneshot_on_usr2') as service:
        with dump_on_error(service.read):
            wait_for_strings(service.read, TIMEOUT,
                             'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            with TestProcess('manhole-cli', '-USR2', str(service.proc.pid), bufsize=0, stdin=subprocess.PIPE) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, '(ManholeConsole)', '>>>')
                    client.proc.stdin.write(b"1234+2345\n")
                    wait_for_strings(client.read, TIMEOUT, '3579')


def test_pid():
    with TestProcess(sys.executable, HELPER, 'test_simple') as service:
        with dump_on_error(service.read):
            wait_for_strings(service.read, TIMEOUT, '/tmp/manhole-')
            with TestProcess('manhole-cli', str(service.proc.pid), bufsize=0, stdin=subprocess.PIPE) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, '(ManholeConsole)', '>>>')
                    client.proc.stdin.write(b"1234+2345\n")
                    wait_for_strings(client.read, TIMEOUT, '3579')


def test_path():
    with TestProcess(sys.executable, HELPER, 'test_simple') as service:
        with dump_on_error(service.read):
            wait_for_strings(service.read, TIMEOUT, '/tmp/manhole-')
            with TestProcess('manhole-cli', '/tmp/manhole-%s' % service.proc.pid, bufsize=0,
                             stdin=subprocess.PIPE) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, '(ManholeConsole)', '>>>')
                    client.proc.stdin.write(b"1234+2345\n")
                    wait_for_strings(client.read, TIMEOUT, '3579')


def test_sig_usr2():
    with TestProcess(sys.executable, '-u', HELPER, 'test_oneshot_on_usr2') as service:
        with dump_on_error(service.read):
            wait_for_strings(service.read, TIMEOUT,
                             'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            with TestProcess('manhole-cli', '--signal=USR2', str(service.proc.pid), bufsize=0,
                             stdin=subprocess.PIPE) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, '(ManholeConsole)', '>>>')
                    client.proc.stdin.write(b"1234+2345\n")
                    wait_for_strings(client.read, TIMEOUT, '3579')


def test_sig_usr2_full():
    with TestProcess(sys.executable, '-u', HELPER, 'test_oneshot_on_usr2') as service:
        with dump_on_error(service.read):
            wait_for_strings(service.read, TIMEOUT,
                             'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            with TestProcess('manhole-cli', '-s', 'SIGUSR2', str(service.proc.pid), bufsize=0,
                             stdin=subprocess.PIPE) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, '(ManholeConsole)', '>>>')
                    client.proc.stdin.write(b"1234+2345\n")
                    wait_for_strings(client.read, TIMEOUT, '3579')


def test_sig_usr2_number():
    with TestProcess(sys.executable, '-u', HELPER, 'test_oneshot_on_usr2') as service:
        with dump_on_error(service.read):
            wait_for_strings(service.read, TIMEOUT,
                             'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            with TestProcess('manhole-cli', '-s', str(int(signal.SIGUSR2)), str(service.proc.pid), bufsize=0,
                             stdin=subprocess.PIPE) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, '(ManholeConsole)', '>>>')
                    client.proc.stdin.write(b"1234+2345\n")
                    wait_for_strings(client.read, TIMEOUT, '3579')
