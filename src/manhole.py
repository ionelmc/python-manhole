from __future__ import print_function
from logging import getLogger
logger = getLogger(__name__)

import traceback
import socket
import struct
import sys
import os
import atexit
import code
import signal
import errno
import platform

__version__ = '0.6.2'

try:
    import signalfd
except ImportError:
    signalfd = None
try:
    string = basestring
except NameError:  # python 3
    string = str
try:
    InterruptedError = InterruptedError
except NameError:  # python <= 3.2
    InterruptedError = OSError
if hasattr(sys, 'setswitchinterval'):
    setinterval = sys.setswitchinterval
    getinterval = sys.getswitchinterval
else:
    setinterval = sys.setcheckinterval
    getinterval = sys.getcheckinterval


def _get_original(qual_name):
    mod, name = qual_name.split('.')
    original = getattr(__import__(mod), name)

    try:
        from gevent.monkey import get_original
        original = get_original(mod, name)
    except (ImportError, SyntaxError):
        pass

    try:
        from eventlet.patcher import original
        original = getattr(original(mod), name)
    except (ImportError, SyntaxError):
        pass

    return original
_ORIGINAL_SOCKET = _get_original('socket.socket')
_ORIGINAL_FDOPEN = _get_original('os.fdopen')
try:
    _ORIGINAL_ALLOCATE_LOCK = _get_original('thread.allocate_lock')
except ImportError:  # python 3
    _ORIGINAL_ALLOCATE_LOCK = _get_original('_thread.allocate_lock')
_ORIGINAL_THREAD = _get_original('threading.Thread')
_ORIGINAL_EVENT = _get_original('threading.Event')
_ORIGINAL__ACTIVE = _get_original('threading._active')
_ORIGINAL_SLEEP = _get_original('time.sleep')

PY3 = sys.version_info[0] == 3
PY26 = sys.version_info[:2] == (2, 6)
VERBOSE = True
START_TIMEOUT = None
SOCKET_PATH = None
REINSTALL_DELAY = None

try:
    import ctypes
    import ctypes.util
    libpthread_path = ctypes.util.find_library("pthread")
    if not libpthread_path:
        raise ImportError
    libpthread = ctypes.CDLL(libpthread_path)
    if not hasattr(libpthread, "pthread_setname_np"):
        raise ImportError
    _pthread_setname_np = libpthread.pthread_setname_np
    _pthread_setname_np.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    _pthread_setname_np.restype = ctypes.c_int
    pthread_setname_np = lambda ident, name: _pthread_setname_np(ident, name[:15].encode('utf8'))
except ImportError:
    pthread_setname_np = lambda ident, name: None

# OS X getsockopt(2) defines (may work for BSD too?)
SOL_LOCAL = 0
LOCAL_PEERCRED = 1

SO_PEERCRED = 17


def cry(message):
    """
    Fail-ignorant logging function.
    """
    if VERBOSE:
        try:
            _STDERR.write("Manhole: %s\n" % message)
        except:  # pylint: disable=W0702
            pass


def get_peercred(sock):
    """Gets the (pid, uid, gid) for the client on the given *connected* socket."""

    if platform.system() == 'Darwin':
        return struct.unpack('3i', sock.getsockopt(
            SOL_LOCAL, LOCAL_PEERCRED, struct.calcsize('3i')
        ))
    else:
        return struct.unpack('3i', sock.getsockopt(
            socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize('3i')
        ))


class SuspiciousClient(Exception):
    pass


class Manhole(_ORIGINAL_THREAD):
    """
    Thread that runs the infamous "Manhole". This thread is a `daemon` thread - it will exit if the main thread
    exits.

    On connect, a different, non-daemon thread will be started - so that the process won't exit while there's a
    connection to the manole.

    Args:
        sigmask (list of singal numbers): Signals to block in this thread.
        start_timeout (float): Seconds to wait for the thread to start. Emits a message if the thread is not running
            when calling ``start()``.
        setup_delay (float): Seconds to delay manhole thread before setting up the manhole. Default: `no delay`.
    """

    def __init__(self, sigmask, start_timeout, setup_delay=None):
        super(Manhole, self).__init__()
        self.daemon = True
        self.name = "Manhole"
        self.sigmask = sigmask
        self.serious = _ORIGINAL_EVENT()
        # time to wait for the manhole to get serious (to have a complete start)
        # see: http://emptysqua.re/blog/dawn-of-the-thread/
        self.start_timeout = start_timeout
        self.setup_delay = setup_delay

    def start(self):
        super(Manhole, self).start()
        if not self.serious.wait(self.start_timeout) and not PY26:
            cry("WARNING: Waited %s seconds but Manhole thread didn't start yet :(" % self.start_timeout)

    @staticmethod
    def get_socket():
        sock = _ORIGINAL_SOCKET(socket.AF_UNIX, socket.SOCK_STREAM)
        name = _manhole_uds_name()
        if os.path.exists(name):
            os.unlink(name)
        sock.bind(name)
        sock.listen(5)
        cry("Manhole UDS path: "+name)
        return sock

    def run(self):
        """
        Runs the manhole loop. Only accepts one connection at a time because:

        * This thread is a daemon thread (exits when main thread exists).
        * The connection need exclusive access to stdin, stderr and stdout so it can redirect inputs and outputs.
        """
        self.serious.set()

        # When called in fork+exec flow, we should not do anything so we do not
        # change the environment inherited by the new process.
        if self.setup_delay:
            cry("Delaying manhole setup %s seconds ..." % self.setup_delay)
            _ORIGINAL_SLEEP(self.setup_delay)

        if signalfd and self.sigmask:
            signalfd.sigprocmask(signalfd.SIG_BLOCK, self.sigmask)
        pthread_setname_np(self.ident, self.name)
        sock = self.get_socket()
        while True:
            cry("Waiting for new connection (in pid:%s) ..." % os.getpid())
            try:
                client = ManholeConnection(sock.accept()[0], self.sigmask)
                client.start()
                client.join()
            except (InterruptedError, socket.error) as e:
                if e.errno != errno.EINTR:
                    raise
                continue
            finally:
                client = None


class ManholeConnection(_ORIGINAL_THREAD):
    """
    Manhole thread that handles the connection. This thread is a normal thread (non-daemon) - it won't exit if the
    main thread exits.
    """
    def __init__(self, client, sigmask):
        super(ManholeConnection, self).__init__()
        self.daemon = False
        self.client = client
        self.name = "ManholeConnection"
        self.sigmask = sigmask

    def run(self):
        cry('Started ManholeConnection thread. Checking credentials ...')
        if signalfd and self.sigmask:
            signalfd.sigprocmask(signalfd.SIG_BLOCK, self.sigmask)
        pthread_setname_np(self.ident, "Manhole ----")

        pid, _, _ = self.check_credentials(self.client)
        pthread_setname_np(self.ident, "Manhole %s" % pid)
        self.handle(self.client)

    @staticmethod
    def check_credentials(client):
        """
        Checks credentials for given socket.
        """
        pid, uid, gid = get_peercred(client)

        euid = os.geteuid()
        client_name = "PID:%s UID:%s GID:%s" % (pid, uid, gid)
        if uid not in (0, euid):
            raise SuspiciousClient("Can't accept client with %s. It doesn't match the current EUID:%s or ROOT." % (
                client_name, euid
            ))

        cry("Accepted connection %s from %s" % (client, client_name))
        return pid, uid, gid

    @staticmethod
    def handle(client):
        """
        Handles connection. This is a static method so it can be used without a thread (eg: from a signal handler -
        `oneshot_on`).
        """
        client.settimeout(None)

        # # disable this till we have evidence that it's needed
        # client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
        # # Note: setting SO_RCVBUF on UDS has no effect, see: http://man7.org/linux/man-pages/man7/unix.7.html

        backup = []
        old_interval = getinterval()
        try:
            try:
                client_fd = client.fileno()
                for mode, names in (
                    ('w', (
                        'stderr',
                        'stdout',
                        '__stderr__',
                        '__stdout__'
                    )),
                    ('r', (
                        'stdin',
                        '__stdin__'
                    ))
                ):
                    for name in names:
                        backup.append((name, getattr(sys, name)))
                        setattr(sys, name, _ORIGINAL_FDOPEN(client_fd, mode, 1 if PY3 else 0))
                run_repl()
                cry("DONE.")
            finally:
                try:
                    # Change the switch/check interval to something ridiculous. We don't want to have other thread try
                    # to write to the redirected sys.__std*/sys.std* - it would fail horribly.
                    setinterval(2147483647)

                    client.close()  # close before it's too late. it may already be dead
                    junk = []  # keep the old file objects alive for a bit
                    for name, fh in backup:
                        junk.append(getattr(sys, name))
                        setattr(sys, name, fh)
                    del backup
                    for fh in junk:
                        try:
                            fh.close()
                        except IOError:
                            pass
                        del fh
                    del junk
                finally:
                    setinterval(old_interval)
                    cry("Cleaned up.")
        except Exception:
            cry("ManholeConnection thread failed:")
            cry(traceback.format_exc())


def run_repl():
    """
    Dumps stacktraces and runs an interactive prompt (REPL).
    """
    dump_stacktraces()
    code.InteractiveConsole({
        'dump_stacktraces': dump_stacktraces,
        'sys': sys,
        'os': os,
        'socket': socket,
        'traceback': traceback,
    }).interact()


def _handle_oneshot(_signum, _frame):
    try:
        sock = Manhole.get_socket()
        cry("Waiting for new connection (in pid:%s) ..." % os.getpid())
        client, _ = sock.accept()
        ManholeConnection.check_credentials(client)
        ManholeConnection.handle(client)
    except:  # pylint: disable=W0702
        # we don't want to let any exception out, it might make the application missbehave
        cry("Manhole oneshot connection failed:")
        cry(traceback.format_exc())
    finally:
        _remove_manhole_uds()


def _remove_manhole_uds():
    name = _manhole_uds_name()
    if os.path.exists(name):
        os.unlink(name)


def _manhole_uds_name():
    if SOCKET_PATH is None:
        return "/tmp/manhole-%s" % os.getpid()
    return SOCKET_PATH


_INST_LOCK = _ORIGINAL_ALLOCATE_LOCK()
_STDERR = _INST = _ORIGINAL_OS_FORK = _ORIGINAL_OS_FORKPTY = _SHOULD_RESTART = None


def _patched_fork():
    """Fork a child process."""
    pid = _ORIGINAL_OS_FORK()
    if not pid:
        cry('Fork detected. Reinstalling Manhole.')
        reinstall()
    return pid


def _patched_forkpty():
    """Fork a new process with a new pseudo-terminal as controlling tty."""
    pid, master_fd = _ORIGINAL_OS_FORKPTY()
    if not pid:
        cry('Fork detected. Reinstalling Manhole.')
        reinstall()
    return pid, master_fd


def _patch_os_fork_functions():
    global _ORIGINAL_OS_FORK, _ORIGINAL_OS_FORKPTY  # pylint: disable=W0603
    if not _ORIGINAL_OS_FORK:
        _ORIGINAL_OS_FORK, os.fork = os.fork, _patched_fork
    if not _ORIGINAL_OS_FORKPTY:
        _ORIGINAL_OS_FORKPTY, os.forkpty = os.forkpty, _patched_forkpty
    cry("Patched %s and %s." % (_ORIGINAL_OS_FORK, _ORIGINAL_OS_FORKPTY))


def _activate_on_signal(_signum, _frame):
    assert _INST, "Manhole wasn't installed !"
    _INST.start()

ALL_SIGNALS = [
    getattr(signal, sig) for sig in dir(signal)
    if sig.startswith('SIG') and '_' not in sig
]


def install(verbose=True, patch_fork=True, activate_on=None, sigmask=ALL_SIGNALS, oneshot_on=None, start_timeout=0.5,
            socket_path=None, reinstall_delay=0.5):
    """
    Installs the manhole.

    Args:
        verbose(bool): Set it to ``False`` to squelch the stderr ouput
        patch_fork(bool): set it to ``False`` if you don't want your ``os.fork`` and ``os.forkpy`` monkeypatched
        activate_on(int or signal name): set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you
            want the Manhole thread to start when this signal is sent. This is desireable in case you don't want the
            thread active all the time.
        oneshot_on(int or signal name): set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you want
            the Manhole to listen for connection in the signal handler. This is desireable in case you don't want
            threads at all.
        sigmask(list of ints or signal names): will set the signal mask to the given list (using
            ``signalfd.sigprocmask``). No action is done if ``signalfd`` is not importable.
            **NOTE**: This is done so that the Manhole thread doesn't *steal* any signals; Normally that is fine cause
            Python will force all the signal handling to be run in the main thread but signalfd doesn't.
        socket_path(str): Use a specifc path for the unix domain socket (instead of ``/tmp/manhole-<pid>``). This
            disables ``patch_fork`` as children cannot resuse the same path.
        reinstall_delay(float): Delay mahole reinstallation after fork *reinstall_delay* seconds. This alleviates
            cleanup failures when using fork+exec patterns.
    """
    global _STDERR, _INST, _SHOULD_RESTART  # pylint: disable=W0603
    global VERBOSE, START_TIMEOUT, SOCKET_PATH, REINSTALL_DELAY  # pylint: disable=W0603
    with _INST_LOCK:
        VERBOSE = verbose
        REINSTALL_DELAY = reinstall_delay
        START_TIMEOUT = start_timeout
        SOCKET_PATH = socket_path
        _STDERR = sys.__stderr__
        if not _INST:
            _INST = Manhole(sigmask, start_timeout)
            if oneshot_on is not None:
                oneshot_on = getattr(signal, 'SIG'+oneshot_on) if isinstance(oneshot_on, string) else oneshot_on
                signal.signal(oneshot_on, _handle_oneshot)

            if activate_on is None:
                if oneshot_on is None:
                    _INST.start()
                    _SHOULD_RESTART = True
            else:
                activate_on = getattr(signal, 'SIG'+activate_on) if isinstance(activate_on, string) else activate_on
                if activate_on == oneshot_on:
                    raise RuntimeError('You cannot do activation of the Manhole thread on the same signal '
                                       'that you want to do oneshot activation !')
                signal.signal(activate_on, _activate_on_signal)
        atexit.register(_remove_manhole_uds)
        if patch_fork:
            if activate_on is None and oneshot_on is None and socket_path is None:
                _patch_os_fork_functions()
            else:
                if activate_on:
                    cry("Not patching os.fork and os.forkpty. Activation is done by signal %s" % activate_on)
                elif oneshot_on:
                    cry("Not patching os.fork and os.forkpty. Oneshot activation is done by signal %s" % oneshot_on)
                elif socket_path:
                    cry("Not patching os.fork and os.forkpty. Using user socket path %s" % socket_path)


def reinstall():
    """
    Reinstalls the manhole. Checks if the thread is running. If not, it starts it again.
    """
    global _INST  # pylint: disable=W0603
    assert _INST
    with _INST_LOCK:
        if not (_INST.is_alive() and _INST in _ORIGINAL__ACTIVE):
            _INST = Manhole(_INST.sigmask, START_TIMEOUT, setup_delay=REINSTALL_DELAY)
            if _SHOULD_RESTART:
                _INST.start()


def dump_stacktraces():
    """
    Dumps thread ids and tracebacks to stdout.
    """
    lines = []
    for thread_id, stack in sys._current_frames().items():  # pylint: disable=W0212
        lines.append("\n######### ProcessID=%s, ThreadID=%s #########" % (
            os.getpid(), thread_id
        ))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            lines.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                lines.append("  %s" % (line.strip()))
    lines.append("#############################################\n\n")

    print('\n'.join(lines), file=sys.stderr)
