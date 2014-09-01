from __future__ import print_function

import atexit
import errno
import imp
import logging
import os
import re
import select
import signal
import socket
import sys
import time
import unittest
from contextlib import closing

from process_tests import dump_on_error
from process_tests import setup_coverage
from process_tests import TestProcess
from process_tests import TestSocket
from process_tests import wait_for_strings
from pytest import mark
from pytest import raises

TIMEOUT = int(os.getenv('MANHOLE_TEST_TIMEOUT', 10))
SOCKET_PATH = '/tmp/manhole-socket'


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
                extra(sock)
    wait_for_strings(proc.read, TIMEOUT, 'Cleaned up.', *[] if oneshot else ['Waiting for new connection'])


@mark.parametrize("count", range(1, 21))
def test_simple(count):
    with TestProcess(sys.executable, __file__, 'daemon', 'test_simple') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            for _ in range(count):
                proc.reset()
                assert_manhole_running(proc, uds_path)


def test_fork_exec():
    with TestProcess(sys.executable, __file__, 'daemon', 'test_fork_exec') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'SUCCESS')


def test_socket_path():
    with TestProcess(sys.executable, __file__, 'daemon', 'test_socket_path') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            proc.reset()
            assert_manhole_running(proc, SOCKET_PATH)


def test_socket_path_with_fork():
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_socket_path_with_fork') as proc:
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


def test_exit_with_grace():
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_simple') as proc:
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
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_with_fork') as proc:
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


if not hasattr(sys, 'pypy_version_info'):
    def test_with_forkpty():
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_with_forkpty') as proc:
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
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_auth_fail') as proc:
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

try:
    import signalfd
except ImportError:
    pass
else:
    def test_signalfd_weirdness():
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_signalfd_weirdness') as proc:
            with dump_on_error(proc.read):
                wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
                wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                wait_for_strings(proc.read, 25 * TIMEOUT, *[
                    '[%s] read from signalfd:' % j for j in range(200)
                ])
                assert_manhole_running(proc, uds_path)

    if not is_module_available('gevent') and not is_module_available('eventlet'):
        def test_signalfd_weirdness_negative():
            with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_signalfd_weirdness_negative') as proc:
                with dump_on_error(proc.read):
                    wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                    uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
                    wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                    wait_for_strings(proc.read, TIMEOUT, 'reading from signalfd failed')
                    assert_manhole_running(proc, uds_path)


def test_activate_on_usr2():
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_activate_on_usr2') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Activation is done by signal')
            raises(AssertionError, wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path)


def test_activate_on_with_oneshot_on():
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_activate_on_with_oneshot_on') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, "You cannot do activation of the Manhole thread on the same signal that you want to do oneshot activation !")


def test_oneshot_on_usr2():
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_oneshot_on_usr2') as proc:
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
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_oneshot_on_usr2') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Oneshot activation is done by signal')
            raises(AssertionError, wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path, oneshot=True, extra=lambda sock: sock.send(b"raise SystemExit()\n"))

            proc.reset()
            proc.signal(signal.SIGUSR2)
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
            assert_manhole_running(proc, uds_path, oneshot=True)


def test_interrupt_on_accept():
    with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_interrupt_on_accept') as proc:
        with dump_on_error(proc.read):
            wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
            uds_path = re.findall(r"(/tmp/manhole-\d+)", proc.read())[0]
            wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection', 'Sending signal to manhole thread', 'Waiting for new connection')
            assert_manhole_running(proc, uds_path)


def setup_greenthreads(patch_threads=False):
    try:
        from gevent import monkey
        monkey.patch_all(thread=False)
    except (ImportError, SyntaxError):
        pass

    try:
        import eventlet
        eventlet.monkey_patch(thread=False)
    except (ImportError, SyntaxError):
        pass


def do_fork():
    pid = os.fork()
    if pid:
        @atexit.register
        def cleanup():
            try:
                os.kill(pid, signal.SIGINT)
                time.sleep(0.2)
                os.kill(pid, signal.SIGTERM)
            except OSError as e:
                if e.errno != errno.ESRCH:
                    raise
        os.waitpid(pid, 0)
    else:
        time.sleep(TIMEOUT * 10)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
        logging.basicConfig(
            level=logging.DEBUG,
            format='[pid=%(process)d - %(asctime)s]: %(name)s - %(levelname)s - %(message)s',
        )
        test_name = sys.argv[2]

        setup_coverage()

        if os.getenv('PATCH_THREAD', False):
            import manhole
            setup_greenthreads(True)
        else:
            setup_greenthreads(True)
            import manhole

        if test_name == 'test_activate_on_usr2':
            manhole.install(activate_on='USR2')
            for i in range(TIMEOUT * 100):
                time.sleep(0.1)
        elif test_name == 'test_fork_exec':
            import subprocess
            manhole.install()
            for i in range(500):
                p = subprocess.Popen(['sleep', '0'])
                p.wait()
                path = '/tmp/manhole-%d' % p.pid
                if os.path.exists(path):
                    os.unlink(path)
                    raise AssertionError(path + ' exists !')
            print('SUCCESS')
        elif test_name == 'test_activate_on_with_oneshot_on':
            manhole.install(activate_on='USR2', oneshot_on='USR2')
            for i in range(TIMEOUT * 100):
                time.sleep(0.1)
        elif test_name == 'test_interrupt_on_accept':
            def handle_usr2(_sig, _frame):
                print('Got USR2')
            signal.signal(signal.SIGUSR2, handle_usr2)

            import ctypes
            import ctypes.util
            libpthread_path = ctypes.util.find_library("pthread")
            if not libpthread_path:
                raise ImportError
            libpthread = ctypes.CDLL(libpthread_path)
            if not hasattr(libpthread, "pthread_setname_np"):
                raise ImportError
            pthread_kill = libpthread.pthread_kill
            pthread_kill.argtypes = [ctypes.c_void_p, ctypes.c_int]
            pthread_kill.restype = ctypes.c_int
            manhole.install(sigmask=None)
            for i in range(15):
                time.sleep(0.1)
            print("Sending signal to manhole thread ...")
            pthread_kill(manhole._INST.ident, signal.SIGUSR2)
            for i in range(TIMEOUT * 100):
                time.sleep(0.1)
        elif test_name == 'test_oneshot_on_usr2':
            manhole.install(oneshot_on='USR2')
            for i in range(TIMEOUT  * 100):
                time.sleep(0.1)
        elif test_name.startswith('test_signalfd_weirdness'):
            if 'negative' in test_name:
                manhole.install(sigmask=None)
            else:
                manhole.install(sigmask=[signal.SIGCHLD])
            time.sleep(0.3)  # give the manhole a bit enough time to start
            print('Starting ...')
            import signalfd
            signalfd.sigprocmask(signalfd.SIG_BLOCK, [signal.SIGCHLD])
            fd = signalfd.signalfd(0, [signal.SIGCHLD], signalfd.SFD_NONBLOCK|signalfd.SFD_CLOEXEC)
            for i in range(200):
                print('Forking %s:' % i)
                pid = os.fork()
                print(' - [%s/%s] forked' % (i, pid))
                if pid:
                    while 1:
                        print(' - [%s/%s] selecting on: %s' % (i, pid, [fd]))
                        read_ready, _, errors = select.select([fd], [], [fd], 1)
                        if read_ready:
                            try:
                                print(' - [%s/%s] reading from signalfd ...' % (i, pid))
                                print(' - [%s] read from signalfd: %r ' % (i, os.read(fd, 128)))
                                break
                            except OSError as exc:
                                print(' - [%s/%s] reading from signalfd failed with errno %s' % (i, pid, exc.errno))
                        else:
                            print(' - [%s/%s] reading from signalfd failed - not ready !' % (i, pid))
                            if 'negative' in test_name:
                                time.sleep(1)
                        if errors:
                            raise RuntimeError("fd has error")
                else:
                    print(' - [%s/%s] exiting' % (i, pid))
                    os._exit(0)
            time.sleep(TIMEOUT * 10)
        elif test_name == 'test_auth_fail':
            manhole.get_peercred = lambda _: (-1, -1, -1)
            manhole.install()
            time.sleep(TIMEOUT * 10)
        elif test_name == 'test_socket_path':
            manhole.install(socket_path=SOCKET_PATH)
            time.sleep(TIMEOUT * 10)
        elif test_name == 'test_socket_path_with_fork':
            manhole.install(socket_path=SOCKET_PATH)
            time.sleep(1)
            do_fork()
        else:
            manhole.install()
            time.sleep(0.3)  # give the manhole a bit enough time to start
            if test_name == 'test_simple':
                time.sleep(TIMEOUT * 10)
            elif test_name == 'test_with_forkpty':
                time.sleep(1)
                pid, masterfd = os.forkpty()
                if pid:
                    @atexit.register
                    def cleanup():
                        try:
                            os.kill(pid, signal.SIGINT)
                            time.sleep(0.2)
                            os.kill(pid, signal.SIGTERM)
                        except OSError as e:
                            if e.errno != errno.ESRCH:
                                raise
                    while not os.waitpid(pid, os.WNOHANG)[0]:
                        try:
                            os.write(2, os.read(masterfd, 1024))
                        except OSError as e:
                            print("Error while reading from masterfd:", e)
                else:
                    time.sleep(TIMEOUT * 10)
            elif test_name == 'test_with_fork':
                time.sleep(1)
                do_fork()
            else:
                raise RuntimeError('Invalid test spec.')
        print('DIED.')
    else:
        unittest.main()
