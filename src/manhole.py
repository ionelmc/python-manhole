from __future__ import print_function
from logging import getLogger
logger = getLogger(__name__)

try:
    import thread
except ImportError: # python 3
    import _thread as thread
import threading
import traceback
import socket
import struct
import sys
import os
import atexit
import code
import signal
import errno
try:
    import signalfd
except ImportError:
    signalfd = None
try:
    string = basestring
except NameError: # python 3
    string = str
try:
    InterruptedError = InterruptedError
except NameError: # python <= 3.2
    InterruptedError = OSError
if hasattr(sys, 'setswitchinterval'):
    setinterval = sys.setswitchinterval
    getinterval = sys.getswitchinterval
else:
    setinterval = sys.setcheckinterval
    getinterval = sys.getcheckinterval
PY3 = sys.version_info[0] == 3
VERBOSE = True

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

SO_PEERCRED = 17

def cry(message):
    """
    Fail-ignorant logging function.
    """
    if VERBOSE:
        try:
            print("Manhole: "+message, file=_STDERR)
        except: #pylint: disable=W0702
            pass

def get_peercred(sock):
    """Gets the (pid, uid, gid) for the client on the given *connected* socket."""

    return struct.unpack('3i', sock.getsockopt(
        socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize('3i')
    ))

class SuspiciousClient(Exception):
    pass

class Manhole(threading.Thread):
    """
    Thread that runs the infamous "Manhole".
    """

    def __init__(self, sigmask):
        super(Manhole, self).__init__()
        self.daemon = True
        self.name = "Manhole"
        self.sigmask = sigmask

    @staticmethod
    def get_socket():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        pid = os.getpid()
        name = "/tmp/manhole-%s" % pid
        if os.path.exists(name):
            os.unlink(name)
        sock.bind(name)
        sock.listen(0)
        cry("Manhole UDS path: "+name)
        return sock, pid

    def run(self):
        if signalfd and self.sigmask:
            signalfd.sigprocmask(signalfd.SIG_BLOCK, self.sigmask)
        pthread_setname_np(self.ident, self.name)

        sock, pid = self.get_socket()
        while True:
            cry("Waiting for new connection (in pid:%s) ..." % pid)
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

class ManholeConnection(threading.Thread):
    def __init__(self, client, sigmask):
        super(ManholeConnection, self).__init__()
        self.daemon = False
        self.client = client
        self.name = "ManholeConnection"
        self.sigmask = sigmask

    def run(self):
        if signalfd and self.sigmask:
            signalfd.sigprocmask(signalfd.SIG_BLOCK, self.sigmask)
        pthread_setname_np(self.ident, "Manhole ----")

        pid, _, _ = self.check_credentials(self.client)
        pthread_setname_np(self.ident, "Manhole %s" % pid)
        self.handle(self.client)

    @staticmethod
    def check_credentials(client):
        pid, uid, gid = get_peercred(client)
        euid = os.geteuid()
        client_name = "PID:%s UID:%s GID:%s" % (pid, uid, gid)
        if uid not in (0, euid):
            raise SuspiciousClient(
                "Can't accept client with %s. "
                "It doesn't match the current EUID:%s or ROOT." % (
                    client_name, euid
            ))

        cry("Accepted connection %s from %s" % (client, client_name))
        return pid, uid, gid

    @staticmethod
    def handle(client):
        client.settimeout(None)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 0)
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
                        setattr(sys, name, os.fdopen(client_fd, mode, 1 if PY3 else 0))
                run_repl()
                cry("DONE.")
            finally:
                try:
                    setinterval(2147483647) # change the switch/check interval to something ridiculous
                                            # we don't want to have other thread try to write to the
                                            # redirected sys.__std*/sys.std* - it would fail horribly
                    client.close() # close before it's too late. it may already be dead
                    junk = [] # keep the old file objects alive for a bit
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
        sock, pid = Manhole.get_socket()
        cry("Waiting for new connection (in pid:%s) ..." % pid)
        client, _ = sock.accept()
        ManholeConnection.check_credentials(client)
        ManholeConnection.handle(client)
    except: # pylint: disable=W0702
        # we don't want to let any exception out, it might make the application missbehave
        cry("Manhole oneshot connection failed:")
        cry(traceback.format_exc())
    finally:
        _remove_manhole_uds()

def _remove_manhole_uds():
    name = "/tmp/manhole-%s" % os.getpid()
    if os.path.exists(name):
        os.unlink(name)

_INST_LOCK = thread.allocate_lock()
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
    global _ORIGINAL_OS_FORK, _ORIGINAL_OS_FORKPTY #pylint: disable=W0603
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
def install(verbose=True, patch_fork=True, activate_on=None, sigmask=ALL_SIGNALS, oneshot_on=None):
    global _STDERR, _INST, _SHOULD_RESTART, VERBOSE #pylint: disable=W0603
    with _INST_LOCK:
        VERBOSE = verbose
        _STDERR = sys.__stderr__
        if not _INST:
            _INST = Manhole(sigmask)
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
                    raise RuntimeError('You cannot do activation of the Manhole thread on the same signal that you want to do oneshot activation !')
                signal.signal(activate_on, _activate_on_signal)
        atexit.register(_remove_manhole_uds)
        if patch_fork:
            if activate_on is None and oneshot_on is None:
                _patch_os_fork_functions()
            else:
                if activate_on:
                    cry("Not patching os.fork and os.forkpty. Activation is done by signal %s" % activate_on)
                elif oneshot_on:
                    cry("Not patching os.fork and os.forkpty. Oneshot activation is done by signal %s" % oneshot_on)

def reinstall():
    global _INST #pylint: disable=W0603
    assert _INST
    with _INST_LOCK:
        if not _INST.is_alive():
            _INST = Manhole(_INST.sigmask)
            if _SHOULD_RESTART:
                _INST.start()

def dump_stacktraces():
    lines = []
    for thread_id, stack in sys._current_frames().items(): #pylint: disable=W0212
        lines.append("\n######### ProcessID=%s, ThreadID=%s #########" % (
            os.getpid(), thread_id
        ))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            lines.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                lines.append("  %s" % (line.strip()))
    lines.append("#############################################\n\n")

    print('\n'.join(lines), file=sys.stderr)


if __name__ == '__main__': #pragma: no cover
    from logging import basicConfig, DEBUG
    basicConfig(level=DEBUG)
    install(verbose=True)#, oneshot_on='USR2')
    try:
        import faulthandler
        faulthandler.enable()
    except ImportError:
        pass

    print()

    import time
    from itertools import cycle
    for i, _i in enumerate(cycle([None])):
        if i == 3:
            print()
            print('FORKING ----------------')
            print()
            cpid = os.fork()
            #if cpid:
            #    os.waitpid(pid, 0)
        time.sleep(1)
        #if i == 3:
        #    if cpid:
        #        time.sleep(1000)
        #    else:
        #        run_repl()
        #
