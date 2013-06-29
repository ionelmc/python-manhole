from __future__ import print_function
from logging import getLogger
logger = getLogger(__name__)

import thread
import threading
import traceback
import socket
import struct
import sys
import os

SO_PEERCRED = 17

def cry(message):
    """
    Fail-ignorant logging function.
    """
    try:
        logger.warning(message)
        print(message, file=_stderr)
    except: #pylint: disable=W0702
        pass

def get_peercred(sock):
    """Gets the (pid, uid, gid) for the client on the given *connected* socket."""

    return struct.unpack('3i', sock.getsockopt(
        socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize('3i')
    ))

class SuspiciousClient(Exception):
    pass

#class SoftFile(object):
#    def __init__(self, fh):
#        self.fh = fh
#
#import io

class Manhole(threading.Thread):
    """
    Thread that runs the infamous "Manhole".
    """

    def __init__(self):
        super(Manhole, self).__init__()
        self.daemon = True
        self.name = "Manhole"

    def run(self):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            pid = os.getpid()
            name = "/tmp/manhole-%s" % pid
            if os.path.exists(name):
                os.unlink(name)
            sock.bind(name)
            sock.listen(0)
            cry("ManholeUDS@: "+name)

            while True:
                client, _ = sock.accept()
                try:
                    self.handle_connection(client)
                except IOError:
                    pass # yes I'm sure !
                except: #pylint: disable=W0703
                    cry(traceback.format_exc())
                finally:
                    del client
        finally:
            if os:
                os.unlink(name)

    @staticmethod
    def handle_connection(client):
        client.settimeout(None)
        pid, uid, gid = get_peercred(client)
        euid = os.geteuid()
        if uid not in (0, euid):
            raise SuspiciousClient(
                "Can't accept client with UID:%s (GID:%s and PID:%s). "
                "It doesn't match the current EUID:%s or ROOT." % (
                    uid, gid, pid, euid
            ))

        cry("Accepted connection %s from pid:%s uid:%s gid:%s" % (client, pid, uid, gid))
        client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 0)
        backup = []
        try:
            client_fd = client.fileno()
            client_sock = client._sock
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
            junk = [client] # keep the old file objects alive for a bit
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
            sys.setcheckinterval(old_interval)

_inst_lock = thread.allocate_lock()
_stderr = _inst = None

def run_repl():
    dump_stactraces()

    import code
    code.InteractiveConsole(locals=globals()).interact()

def install():
    global _stderr, _inst #pylint: disable=W0603
    with _inst_lock:
        _stderr = sys.__stderr__
        if not _inst:
            _inst = Manhole()
            _inst.start()

def dump_stactraces():
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
    install()
    print()

    import time
    while 1:
        print('Main', end='')
        time.sleep(2)
