from __future__ import print_function

import imp
import os
import re
import select
import signal
import socket
import sys
import time
from contextlib import closing

from process_tests import dump_on_error
from process_tests import TestProcess
from process_tests import TestSocket
from process_tests import wait_for_strings
from pytest import mark
from pytest import raises

TIMEOUT = int(os.getenv('MANHOLE_TEST_TIMEOUT', 10))
SOCKET_PATH = '/tmp/manhole-socket'
HELPER = os.path.join(os.path.dirname(__file__), 'helper.py')


def is_module_available(mod):
    try:
        return imp.find_module(mod)
    except ImportError:
        return False


def connect_to_manhole(uds_path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    for i in range(TIMEOUT):
        try:
            sock.connect(uds_path)
            return sock
        except Exception as exc:
            print('Failed to connect to %s: %s' % (uds_path, exc))
            if i + 1 == TIMEOUT:
                sock.close()
                raise
            time.sleep(1)


def assert_manhole_running(proc, uds_path, oneshot=False, extra=None):
    sock = connect_to_manhole(uds_path)
    with TestSocket(sock) as client:
        with dump_on_error(client.read):
            wait_for_strings(client.read, TIMEOUT, "ProcessID", "ThreadID", ">>>")
            sock.send(b"print('FOOBAR')\n")
            wait_for_strings(client.read, TIMEOUT, "FOOBAR")
            wait_for_strings(proc.read, TIMEOUT, 'UID:%s' % os.getuid())
            if extra:
                extra(client)
    wait_for_strings(proc.read, TIMEOUT, 'Cleaned up.', *[] if oneshot else ['Waiting for new connection'])


def test_simple():
    with TestProcess(sys.executable, HELPER, 'test_simple') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            for _ in range(20):
                proc.reset()
                assert_manhole_running(proc, uds_path)

@mark.skipif(is_module_available('eventlet'), reason="evenlet can't deal with extra threads at process exit")
def test_daemon_connection():
    with TestProcess(sys.executable, HELPER, 'test_daemon_connection') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')

            def terminate_and_read(client):
                proc.proc.send_signal(signal.SIGINT)
                wait_for_strings(proc.read, TIMEOUT, 'Died with KeyboardInterrupt')
                client.sock.send(b'bogus()\n')
                client.sock.send(b'bogus()\n')
            raises((socket.error, OSError), assert_manhole_running, proc, uds_path, extra=terminate_and_read)
            wait_for_strings(proc.read, TIMEOUT, 'In atexit handler')


@mark.skipif(is_module_available('eventlet'), reason="evenlet can't deal with extra threads at process exit")
def test_non_daemon_connection():
    with TestProcess(sys.executable, HELPER, 'test_simple') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')

            def terminate_and_read(client):
                proc.proc.send_signal(signal.SIGINT)
                wait_for_strings(proc.read, TIMEOUT, 'Died with KeyboardInterrupt')
                client.sock.send(b'bogus()\n')
                wait_for_strings(client.read, TIMEOUT, 'bogus')
                client.sock.send(b'doofus()\n')
                wait_for_strings(client.read, TIMEOUT, 'doofus')
            assert_manhole_running(proc, uds_path, extra=terminate_and_read, oneshot=True)
            wait_for_strings(proc.read, TIMEOUT, 'In atexit handler')


def test_locals():
    with TestProcess(sys.executable, HELPER, 'test_locals') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            check_locals(SOCKET_PATH)


def test_locals_after_fork():
    with TestProcess(sys.executable, HELPER, 'test_locals_after_fork') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Fork detected')
            proc.reset()
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            child_uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            check_locals(child_uds_path)


def check_locals(uds_path):
    sock = connect_to_manhole(uds_path)
    with TestSocket(sock) as client:
        with dump_on_error(client.read):
            wait_for_strings(client.read, 1, ">>>")
            sock.send(b"from __future__ import print_function\n"
                      b"print(k1, k2)\n")
            wait_for_strings(client.read, 1, "v1 v2")


def test_fork_exec():
    with TestProcess(sys.executable, HELPER, 'test_fork_exec') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'SUCCESS')


def test_socket_path():
    with TestProcess(sys.executable, HELPER, 'test_socket_path') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            proc.reset()
            assert_manhole_running(proc, SOCKET_PATH)


def test_socket_path_with_fork():
    with TestProcess(sys.executable, '-u', HELPER, 'test_socket_path_with_fork') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Using user socket path')
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            sock = connect_to_manhole(SOCKET_PATH)
            with TestSocket(sock) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, "ProcessID", "ThreadID", ">>>")
                    sock.send(b"print('BEFORE FORK')\n")
                    wait_for_strings(client.read, TIMEOUT, "BEFORE FORK")
                    time.sleep(2)
                    sock.send(b"print('AFTER FORK')\n")
                    wait_for_strings(client.read, TIMEOUT, "AFTER FORK")


def test_redirect_stderr_default():
    with TestProcess(sys.executable, HELPER, 'test_redirect_stderr_default') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            sock = connect_to_manhole(SOCKET_PATH)
            with TestSocket(sock) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, 1, ">>>")
                    client.reset()
                    sock.send(b"import sys\n"
                              b"sys.stderr.write('OK')\n")
                    wait_for_strings(client.read, 1, "OK")


def test_redirect_stderr_default_dump_stacktraces():
    with TestProcess(sys.executable, HELPER, 'test_redirect_stderr_default') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            check_dump_stacktraces(SOCKET_PATH)


def test_redirect_stderr_default_print_tracebacks():
    with TestProcess(sys.executable, HELPER, 'test_redirect_stderr_default') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            check_print_tracebacks(SOCKET_PATH)


def test_redirect_stderr_disabled():
    with TestProcess(sys.executable, HELPER, 'test_redirect_stderr_disabled') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            sock = connect_to_manhole(SOCKET_PATH)
            with TestSocket(sock) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, 1, ">>>")
                    client.reset()
                    sock.send(b"import sys\n"
                              b"sys.stderr.write('STDERR')\n"
                              b"sys.stdout.write('STDOUT')\n")
                    wait_for_strings(client.read, 1, "STDOUT")
                    assert 'STDERR' not in client.read()


def test_redirect_stderr_disabled_dump_stacktraces():
    with TestProcess(sys.executable, HELPER, 'test_redirect_stderr_disabled') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            check_dump_stacktraces(SOCKET_PATH)


def test_redirect_stderr_disabled_print_tracebacks():
    with TestProcess(sys.executable, HELPER, 'test_redirect_stderr_disabled') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            check_print_tracebacks(SOCKET_PATH)


def check_dump_stacktraces(uds_path):
    sock = connect_to_manhole(uds_path)
    with TestSocket(sock) as client:
        with dump_on_error(client.read):
            wait_for_strings(client.read, 1, ">>>")
            sock.send(b"dump_stacktraces()\n")
            # Start of dump
            wait_for_strings(client.read, 1, "#########", "ThreadID=", "#########")
            # End of dump
            wait_for_strings(client.read, 1, "#############################################", ">>>")


def check_print_tracebacks(uds_path):
    sock = connect_to_manhole(uds_path)
    with TestSocket(sock) as client:
        with dump_on_error(client.read):
            wait_for_strings(client.read, 1, ">>>")
            sock.send(b"NO_SUCH_NAME\n")
            wait_for_strings(client.read, 1, "NameError:", "name 'NO_SUCH_NAME' is not defined", ">>>")


def test_exit_with_grace():
    with TestProcess(sys.executable, '-u', HELPER, 'test_simple') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.05)
            sock.connect(uds_path)
            with TestSocket(sock) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, TIMEOUT, "ThreadID", "ProcessID", ">>>")
                    sock.send(b"print('FOOBAR')\n")
                    wait_for_strings(client.read, TIMEOUT, "FOOBAR")

                    wait_for_strings(proc.read, TIMEOUT, 'UID:%s' % os.getuid())
                    sock.shutdown(socket.SHUT_WR)
                    select.select([sock], [], [], 5)
                    sock.recv(1024)
                    try:
                        sock.shutdown(socket.SHUT_RD)
                    except Exception as exc:
                        print("Failed to SHUT_RD: %s" % exc)
                    try:
                        sock.close()
                    except Exception as exc:
                        print("Failed to close socket: %s" % exc)
            wait_for_strings(proc.read, TIMEOUT, 'DONE.', 'Cleaned up.', 'Waiting for new connection')


def test_with_fork():
    with TestProcess(sys.executable, '-u', HELPER, 'test_with_fork') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            for _ in range(2):
                proc.reset()
                assert_manhole_running(proc, uds_path)

            proc.reset()
            wait_for_strings(proc.read, TIMEOUT, 'Fork detected')
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            new_uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            assert uds_path != new_uds_path

            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            for _ in range(2):
                proc.reset()
                assert_manhole_running(proc, new_uds_path)


@mark.skipif(hasattr(sys, 'pypy_version_info'), reason="pypy doesn't support forkpty")
def test_with_forkpty():
    with TestProcess(sys.executable, '-u', HELPER, 'test_with_forkpty') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            for _ in range(2):
                proc.reset()
                assert_manhole_running(proc, uds_path)

            proc.reset()
            wait_for_strings(proc.read, TIMEOUT, 'Fork detected')
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            new_uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            assert uds_path != new_uds_path

            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            for _ in range(2):
                proc.reset()
                assert_manhole_running(proc, new_uds_path)


def test_auth_fail():
    with TestProcess(sys.executable, '-u', HELPER, 'test_auth_fail') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as sock:
                sock.settimeout(1)
                sock.connect(uds_path)
                try:
                    assert b"" == sock.recv(1024)
                except socket.timeout:
                    pass
                wait_for_strings(
                    proc.read, TIMEOUT,
                    "SuspiciousClient: Can't accept client with PID:-1 UID:-1 GID:-1. It doesn't match the current EUID:",
                    'Waiting for new connection'
                )
                proc.proc.send_signal(signal.SIGINT)


@mark.skipif(not is_module_available('signalfd'), reason="signalfd not available")
def test_signalfd_weirdness():
    with TestProcess(sys.executable, '-u', HELPER, 'test_signalfd_weirdness') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            wait_for_strings(proc.read, 25 * TIMEOUT, *[
                '[%s] read from signalfd:' % j for j in range(200)
            ])
            assert_manhole_running(proc, uds_path)


@mark.skipif(not is_module_available('signalfd') or
             is_module_available('gevent') or
             is_module_available('eventlet'),
             reason="signalfd doesn't play well with gevent/eventlet")
def test_signalfd_weirdness_negative():
    with TestProcess(sys.executable, '-u', HELPER, 'test_signalfd_weirdness_negative') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            wait_for_strings(proc.read, TIMEOUT, 'reading from signalfd failed')
            assert_manhole_running(proc, uds_path)


def test_activate_on_usr2():
    with TestProcess(sys.executable, '-u', HELPER, 'test_activate_on_usr2') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Activation is done by signal')
            raises(AssertionError, wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path)


def test_activate_on_with_oneshot_on():
    with TestProcess(sys.executable, '-u', HELPER, 'test_activate_on_with_oneshot_on') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, "You cannot do activation of the Manhole thread on the same signal that you want to do oneshot activation !")


def test_oneshot_on_usr2():
    with TestProcess(sys.executable, '-u', HELPER, 'test_oneshot_on_usr2') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            raises(AssertionError, wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path, oneshot=True)


def test_fail_to_cry():
    import manhole
    verbose = manhole.VERBOSE
    out = manhole._STDERR
    try:
        manhole.VERBOSE = True
        fh = os.fdopen(os.dup(2), 'w')
        fh.close()
        manhole._STDERR = fh
        manhole.cry('stuff')
    finally:
        manhole.VERBOSE = verbose
        manhole._STDERR = out


def test_oneshot_on_usr2_error():
    with TestProcess(sys.executable, '-u', HELPER, 'test_oneshot_on_usr2') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            raises(AssertionError, wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path, oneshot=True,
                                   extra=lambda client: client.sock.send(b"raise SystemExit()\n"))

            proc.reset()
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path, oneshot=True)


def test_interrupt_on_accept():
    with TestProcess(sys.executable, '-u', HELPER, 'test_interrupt_on_accept') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection', 'Sending signal to manhole thread', 'Waiting for new connection')
            assert_manhole_running(proc, uds_path)


@mark.skipif(not is_module_available('signalfd'), reason="signalfd not available")
def test_sigmask():
    with TestProcess(sys.executable, HELPER, 'test_sigmask') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            sock = connect_to_manhole(SOCKET_PATH)
            with TestSocket(sock) as client:
                with dump_on_error(client.read):
                    wait_for_strings(client.read, 1, ">>>")
                    client.reset()
                    # Python 2.7 returns [10L], Python 3 returns [10]
                    sock.send(b"from __future__ import print_function\n"
                              b"import signalfd\n"
                              b"mask = signalfd.sigprocmask(signalfd.SIG_BLOCK, [])\n"
                              b"print([int(n) for n in mask])\n")
                    wait_for_strings(client.read, 1, '%s' % [signal.SIGUSR1])
