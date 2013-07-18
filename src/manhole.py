from __future__ import print_function
from logging import getLogger
logger = getLogger(__name__)

import thread
import threading
import traceback
import socket
import struct
import select
import sys
import os
import atexit
import code
import signal
try:
    import signalfd
except ImportError:
    signalfd = None

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
    pthread_setname_np = lambda ident, name: _pthread_setname_np(ident, name[:15])
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
        cry("Waiting for new connection (in pid:%s) ..." % pid)
        while True:
            client, _ = sock.accept()
            global _CLIENT_INST #pylint: disable=W0603

            try:
                _CLIENT_INST = ManholeConnection(client, self.sigmask)
                _CLIENT_INST.start()
                _CLIENT_INST.join()
            #except: #pylint: disable=W0703
            #    cry(traceback.format_exc()) #pylint: disable=W0702
            finally:
                _CLIENT_INST = None
                del client

            cry("Waiting for new connection ...")

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

        client = self.client
        client.settimeout(None)
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
        pthread_setname_np(self.ident, "Manhole %s" % pid)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 0)
        backup = []
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
                    setattr(sys, name, os.fdopen(client_fd, mode, 0))

            run_repl()
            cry("DONE.")
        finally:
            cry("Cleaning up.")
            old_interval = sys.getcheckinterval()
            sys.setcheckinterval(2147483647)
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
            self.client = None
            sys.setcheckinterval(old_interval)

def run_repl():
    dump_stacktraces()
    code.InteractiveConsole({
        'dump_stacktraces': dump_stacktraces,
        'sys': sys,
        'os': os,
        'socket': socket,
        'traceback': traceback,
    }).interact()

def _remove_manhole_uds():
    name = "/tmp/manhole-%s" % os.getpid()
    if os.path.exists(name):
        os.unlink(name)

_INST_LOCK = thread.allocate_lock()
_STDERR = _INST = _CLIENT_INST = _ORIGINAL_OS_FORK = _ORIGINAL_OS_FORKPTY = None

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
    assert _INST
    _INST.start()

ALL_SIGNALS = [
    getattr(signal, sig) for sig in dir(signal)
    if sig.startswith('SIG') and '_' not in sig
]
def install(verbose=True, patch_fork=True, activate_on=None, sigmask=ALL_SIGNALS):
    global _STDERR, _INST, VERBOSE #pylint: disable=W0603
    with _INST_LOCK:
        VERBOSE = verbose
        _STDERR = sys.__stderr__
        if not _INST:
            _INST = Manhole(sigmask)
            if activate_on is None:
                _INST.start()
            else:
                signal.signal(
                    getattr(signal, 'SIG'+activate_on) if isinstance(activate_on, basestring) else activate_on,
                    _activate_on_signal
                )
        atexit.register(_remove_manhole_uds)
        if patch_fork:
            if activate_on is None:
                _patch_os_fork_functions()
            else:
                cry("Not patching os.fork and os.forkpty. Activation is done by signal %s" % activate_on)

def reinstall():
    global _INST #pylint: disable=W0603
    assert _INST
    with _INST_LOCK:
        if not _INST.is_alive():
            _INST = Manhole(_INST.sigmask)
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
    install(1)
    import faulthandler
    faulthandler.enable()

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
