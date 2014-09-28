from __future__ import print_function

import atexit
import errno
import logging
import os
import select
import signal
import sys
import time

from process_tests import setup_coverage

TIMEOUT = int(os.getenv('MANHOLE_TEST_TIMEOUT', 10))
SOCKET_PATH = '/tmp/manhole-socket'
OUTPUT = sys.__stdout__


def handle_sigterm(signo, _frame):
    # Simulate real termination
    print("Terminated", file=OUTPUT)
    sys.exit(128 + signo)

# Handling sigterm ensure that atexit functions are called, and we do not leave
# leftover /tmp/manhole-pid sockets.
signal.signal(signal.SIGTERM, handle_sigterm)


@atexit.register
def log_exit():
    print("In atexit handler.", file=OUTPUT)


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
    logging.basicConfig(
        level=logging.DEBUG,
        format='[pid=%(process)d - %(asctime)s]: %(name)s - %(levelname)s - %(message)s',
    )
    test_name = sys.argv[1]
    try:

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
                p = subprocess.Popen(['true'])
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
        elif test_name == 'test_daemon_connection':
            manhole.install(daemon_connection=True)
            time.sleep(TIMEOUT)
        elif test_name == 'test_socket_path_with_fork':
            manhole.install(socket_path=SOCKET_PATH)
            time.sleep(1)
            do_fork()
        elif test_name == 'test_locals':
            manhole.install(socket_path=SOCKET_PATH,
                            locals={'k1': 'v1', 'k2': 'v2'})
            time.sleep(1)
        elif test_name == 'test_locals_after_fork':
            manhole.install(locals={'k1': 'v1', 'k2': 'v2'})
            do_fork()
        elif test_name == 'test_redirect_stderr_default':
            manhole.install(socket_path=SOCKET_PATH)
            time.sleep(1)
        elif test_name == 'test_redirect_stderr_disabled':
            manhole.install(socket_path=SOCKET_PATH, redirect_stderr=False)
            time.sleep(1)
        elif test_name == 'test_sigmask':
            manhole.install(socket_path=SOCKET_PATH, sigmask=[signal.SIGUSR1])
            time.sleep(1)
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
    except:  # pylint: disable=W0702
        print('Died with %s.' % sys.exc_info()[0].__name__, file=OUTPUT)
        import traceback
        traceback.print_exc(file=OUTPUT)
    print('DIED.', file=OUTPUT)
