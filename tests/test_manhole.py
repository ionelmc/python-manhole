from __future__ import print_function
import unittest
import os
import select
import sys
import traceback
import socket
import errno
import time
import logging
import re
import atexit
import signal
from contextlib import closing

from process_tests import ProcessTestCase, TestProcess, TestSocket, setup_coverage

TIMEOUT = int(os.getenv('MANHOLE_TEST_TIMEOUT', 10))

class ManholeTestCase(ProcessTestCase):
    def test_simple_r01(self):
        self.run_simple(1)
    def test_simple_r02(self):
        self.run_simple(2)
    def test_simple_r03(self):
        self.run_simple(3)
    def test_simple_r04(self):
        self.run_simple(4)
    def test_simple_r05(self):
        self.run_simple(5)
    def test_simple_r06(self):
        self.run_simple(6)
    def test_simple_r07(self):
        self.run_simple(7)
    def test_simple_r08(self):
        self.run_simple(8)
    def test_simple_r09(self):
        self.run_simple(9)
    def test_simple_r10(self):
        self.run_simple(10)

    def run_simple(self, count):
        with TestProcess(sys.executable, __file__, 'daemon', 'test_simple') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                for _ in range(count):
                    proc.reset()
                    self.assertManholeRunning(proc, uds_path)

    def assertManholeRunning(self, proc, uds_path, oneshot=False, extra=None):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        for i in range(TIMEOUT):
            try:
                sock.connect(uds_path)
                break
            except Exception as exc:
                print('Failed to connect to %s: %s' % (uds_path, exc))
                time.sleep(1)
                if i + 1 == TIMEOUT:
                    raise
        try:
            with TestSocket(sock) as client:
                with self.dump_on_error(client.read):
                    self.wait_for_strings(client.read, TIMEOUT,
                        "ProcessID",
                        "ThreadID",
                        ">>>",
                    )
                    sock.send(b"print('FOOBAR')\n")
                    self.wait_for_strings(client.read, TIMEOUT, "FOOBAR")

                    self.wait_for_strings(proc.read, TIMEOUT,
                        'from PID:%s UID:%s' % (os.getpid(), os.getuid()),
                    )
                    if extra:
                        extra(sock)
                    sock.shutdown(socket.SHUT_RDWR)
        finally:
            sock.close()
        self.wait_for_strings(proc.read, TIMEOUT,
            'Cleaned up.',
            *[] if oneshot else ['Waiting for new connection']
        )
    def test_exit_with_grace(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_simple') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')

                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(0.05)
                sock.connect(uds_path)
                with TestSocket(sock) as client:
                    with self.dump_on_error(client.read):
                        self.wait_for_strings(client.read, TIMEOUT,
                            "ThreadID",
                            "ProcessID",
                            ">>>",
                        )
                        sock.send(b"print('FOOBAR')\n")
                        self.wait_for_strings(client.read, TIMEOUT, "FOOBAR")

                        self.wait_for_strings(proc.read, TIMEOUT,
                            'from PID:%s UID:%s' % (os.getpid(), os.getuid()),
                        )
                        sock.shutdown(socket.SHUT_WR)
                        select.select([sock], [], [], 5)
                        sock.recv(1024)
                        sock.shutdown(socket.SHUT_RD)
                        sock.close()
                self.wait_for_strings(proc.read, TIMEOUT,
                    'DONE.',
                    'Cleaned up.',
                    'Waiting for new connection'
                )

    def test_with_fork(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_with_fork') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                for _ in range(2):
                    proc.reset()
                    self.assertManholeRunning(proc, uds_path)

                proc.reset()
                self.wait_for_strings(proc.read, TIMEOUT, 'Fork detected')
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                new_uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.assertNotEqual(uds_path, new_uds_path)

                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                for _ in range(2):
                    proc.reset()
                    self.assertManholeRunning(proc, new_uds_path)
    if not hasattr(sys, 'pypy_version_info'):
        def test_with_forkpty(self):
            with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_with_forkpty') as proc:
                with self.dump_on_error(proc.read):
                    self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                    uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                    self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                    for _ in range(2):
                        proc.reset()
                        self.assertManholeRunning(proc, uds_path)

                    proc.reset()
                    self.wait_for_strings(proc.read, TIMEOUT, 'Fork detected')
                    self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                    new_uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                    self.assertNotEqual(uds_path, new_uds_path)

                    self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                    for _ in range(2):
                        proc.reset()
                        self.assertManholeRunning(proc, new_uds_path)

    def test_auth_fail(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_auth_fail') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as sock:
                    sock.settimeout(1)
                    sock.connect(uds_path)
                    try:
                        self.assertEqual(b"", sock.recv(1024))
                    except socket.timeout:
                        pass
                    self.wait_for_strings(proc.read, TIMEOUT,
                        "SuspiciousClient: Can't accept client with PID:-1 UID:-1 GID:-1. It doesn't match the current EUID:",
                        'Waiting for new connection'
                    )
                    proc.proc.send_signal(signal.SIGINT)

    try:
        import signalfd
    except ImportError:
        pass
    else:
        def test_signalfd_weirdness(self):
            with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_signalfd_weirdness') as proc:
                with self.dump_on_error(proc.read):
                    self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                    uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                    self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                    self.wait_for_strings(proc.read, 25 * TIMEOUT, *[
                        '[%s] read from signalfd:' % j for j in range(200)
                    ])
                    self.assertManholeRunning(proc, uds_path)

        def test_signalfd_weirdness_negative(self):
            with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_signalfd_weirdness_negative') as proc:
                with self.dump_on_error(proc.read):
                    self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                    uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                    self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                    self.wait_for_strings(proc.read, TIMEOUT, 'reading from signalfd failed')
                    self.assertManholeRunning(proc, uds_path)


    def test_activate_on_usr2(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_activate_on_usr2') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Activation is done by signal 12')
                self.assertRaises(AssertionError, self.wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
                proc.signal(signal.SIGUSR2)
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                self.assertManholeRunning(proc, uds_path)

    def test_activate_on_with_oneshot_on(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_activate_on_with_oneshot_on') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, "RuntimeError('You cannot do activation of the Manhole thread on the same signal that you want to do oneshot activation !')")

    def test_oneshot_on_usr2(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_oneshot_on_usr2') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Oneshot activation is done by signal 12')
                self.assertRaises(AssertionError, self.wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
                proc.signal(signal.SIGUSR2)
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                self.assertManholeRunning(proc, uds_path, oneshot=True)

    def test_fail_to_cry(self):
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

    def test_oneshot_on_usr2_error(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_oneshot_on_usr2') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, 'Not patching os.fork and os.forkpty. Oneshot activation is done by signal 12')
                self.assertRaises(AssertionError, self.wait_for_strings, proc.read, TIMEOUT, '/tmp/manhole-')
                proc.signal(signal.SIGUSR2)
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                self.assertManholeRunning(proc, uds_path, oneshot=True, extra=lambda sock: sock.send(b"raise SystemExit()\n"))

                proc.reset()
                proc.signal(signal.SIGUSR2)
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection')
                self.assertManholeRunning(proc, uds_path, oneshot=True)

    def test_interrupt_on_accept(self):
        with TestProcess(sys.executable, '-u', __file__, 'daemon', 'test_interrupt_on_accept') as proc:
            with self.dump_on_error(proc.read):
                self.wait_for_strings(proc.read, TIMEOUT, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.wait_for_strings(proc.read, TIMEOUT, 'Waiting for new connection', 'Sending signal to manhole thread', 'Waiting for new connection')
                self.assertManholeRunning(proc, uds_path)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
        logging.basicConfig(
            level=logging.DEBUG,
            format='[pid=%(process)d - %(asctime)s]: %(name)s - %(levelname)s - %(message)s',
        )
        test_name = sys.argv[2]

        setup_coverage()

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

        import manhole

        if test_name == 'test_activate_on_usr2':
            manhole.install(activate_on='USR2')
            for i in range(TIMEOUT * 100):
                time.sleep(0.1)
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
                            time.sleep(TIMEOUT)
                        if errors:
                            raise RuntimeError("fd has error")
                else:
                    print(' - [%s/%s] exiting' % (i, pid))
                    os._exit(0)
            time.sleep(TIMEOUT)
        else:
            manhole.install()
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
            elif test_name == 'test_auth_fail':
                manhole.get_peercred = lambda _: (-1, -1, -1)
                time.sleep(TIMEOUT * 10)
            else:
                raise RuntimeError('Invalid test spec.')
        print('DIED.')
    else:
        unittest.main()
