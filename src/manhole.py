from __future__ import print_function
from logging import getLogger
logger = getLogger(__name__)

import thread
import threading
#threading._VERBOSE = True
import traceback
import socket
import struct
import sys
import os
import atexit
import code
#import weakref

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
    try:
        print(message, file=_stderr)
    except: #pylint: disable=W0702
        pass

def get_peercred(sock):
    """Gets the (pid, uid, gid) for the client on the given *connected* socket."""

    return struct.unpack('3i', sock.getsockopt(
        socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize('3i')
    ))

#class _Vigil(object):
#    pass
#
#_vigil_locals = threading.local()
#_vigil_refs = set()

class SuspiciousClient(Exception):
    pass

class Manhole(threading.Thread):
    """
    Thread that runs the infamous "Manhole".
    """

    def __init__(self, poll_interval):
        super(Manhole, self).__init__()
        self.daemon = True
        self.poll_interval = poll_interval
        self.name = "Manhole"

    def get_socket(self):
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
        #_vigil_locals.vigil = vigil = _Vigil()
        #_vigil_refs.add(weakref.ref(vigil, lambda *args: cry('CRITICAL: Manhole thread has died !')))
        #del vigil
        pthread_setname_np(self.ident, self.name)

        sock, pid = self.get_socket()
        cry("Waiting for new connection (in pid:%s) ..." % pid)
        while True:
            client, _ = sock.accept()
            global _client_inst

            try:
                _client_inst = ManholeConnection(client)
                _client_inst.start()
                _client_inst.join()
            except: #pylint: disable=W0703
                cry(traceback.format_exc())
            finally:
                _client_inst = None
                del client

            cry("Waiting for new connection ...")

class ManholeConnection(threading.Thread):
    def __init__(self, client):
        super(ManholeConnection, self).__init__()
        self.daemon = False
        self.client = client
        self.name = "ManholeConnection"

    def run(self):
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
    code.InteractiveConsole(locals={}).interact()

def _remove_manhole_uds():
    name = "/tmp/manhole-%s" % os.getpid()
    if os.path.exists(name):
        os.unlink(name)

_inst_lock = thread.allocate_lock()
_stderr = _inst = _client_inst = _original_os_fork = _original_os_forkpty = None

def _patched_fork():
    """Fork a child process."""
    pid = _original_os_fork()
    if not pid:
        reinstall()
    return pid

def _patched_forkpty():
    """Fork a new process with a new pseudo-terminal as controlling tty."""
    pid, master_fd = _original_os_forkpty()
    if not pid:
        reinstall()
    return pid, master_fd

def _patch_os_fork_functions():
    global _original_os_fork, _original_os_forkpty #pylint: disable=W0603

    builtin_function = type(''.join)
    if hasattr(os, 'fork') and isinstance(os.fork, builtin_function):
        _original_os_fork, os.fork = os.fork, _patched_fork
    if hasattr(os, 'forkpty') and isinstance(os.forkpty, builtin_function):
        _original_os_forkpty, os.forkpty = os.forkpty, _patched_forkpty

def install(poll_interval=5):
    global _stderr, _inst #pylint: disable=W0603
    with _inst_lock:
        _stderr = sys.__stderr__
        if not _inst:
            _inst = Manhole(poll_interval)
            _inst.start()
        atexit.register(_remove_manhole_uds)
        _patch_os_fork_functions()

def reinstall():
    assert _inst
    global _inst #pylint: disable=W0603
    with _inst_lock:
        if not _inst.is_alive():
            _inst = Manhole(_inst.poll_interval)
            _inst.start()

def dump_stacktraces():
    code = []
    for thread_id, stack in sys._current_frames().items(): #pylint: disable=W0212
        code.append("\n######### ProcessID=%s, ThreadID=%s #########" % (
            os.getpid(), thread_id
        ))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                code.append("  %s" % (line.strip()))
    code.append("#############################################\n\n")

    print('\n'.join(code), file=sys.stderr)


if __name__ == '__main__':
    from logging import basicConfig, DEBUG
    basicConfig(level=DEBUG)
    install(1)
    import faulthandler
    faulthandler.enable()

    print()

    import time
    from itertools import cycle
    for i, _ in enumerate(cycle([None])):
        #print(i, 'Main(%s)' % os.getpid(), [x() for x in _vigil_refs])
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
