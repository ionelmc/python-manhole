from __future__ import print_function

import atexit
import code
import errno
import os
import signal
import socket
import struct
import sys
import traceback
from contextlib import closing

__version__ = '1.4.0'

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

try:
    from eventlet.patcher import original as _original

    def _get_original(mod, name):
        return getattr(_original(mod), name)
except ImportError:
    try:
        from gevent.monkey import get_original as _get_original
    except ImportError:
        def _get_original(mod, name):
            return getattr(__import__(mod), name)

_ORIGINAL_SOCKET = _get_original('socket', 'socket')
_ORIGINAL_FROMFD = _get_original('socket', 'fromfd')
_ORIGINAL_FDOPEN = _get_original('os', 'fdopen')
_ORIGINAL_DUP = _get_original('os', 'dup')
_ORIGINAL_DUP2 = _get_original('os', 'dup2')
try:
    _ORIGINAL_ALLOCATE_LOCK = _get_original('thread', 'allocate_lock')
except ImportError:  # python 3
    _ORIGINAL_ALLOCATE_LOCK = _get_original('_thread', 'allocate_lock')
_ORIGINAL_THREAD = _get_original('threading', 'Thread')
_ORIGINAL_EVENT = _get_original('threading', 'Event')
_ORIGINAL__ACTIVE = _get_original('threading', '_active')
_ORIGINAL_SLEEP = _get_original('time', 'sleep')

PY3 = sys.version_info[0] == 3
PY26 = sys.version_info[:2] == (2, 6)

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

    def pthread_setname_np(ident, name):
        _pthread_setname_np(ident, name[:15].encode('utf8'))
except ImportError:
    def pthread_setname_np(ident, name):
        pass

if sys.platform == 'darwin' or sys.platform.startswith("freebsd"):
    _PEERCRED_LEVEL = getattr(socket, 'SOL_LOCAL', 0)
    _PEERCRED_OPTION = getattr(socket, 'LOCAL_PEERCRED', 1)
else:
    _PEERCRED_LEVEL = socket.SOL_SOCKET
    # TODO: Is this missing on some platforms?
    _PEERCRED_OPTION = getattr(socket, 'SO_PEERCRED', 17)

_ALL_SIGNALS = tuple(getattr(signal, sig) for sig in dir(signal)
                     if sig.startswith('SIG') and '_' not in sig)

# These (_LOG and _MANHOLE) will hold instances after install
_MANHOLE = None
_LOCK = _ORIGINAL_ALLOCATE_LOCK()


def force_original_socket(sock):
    with closing(sock):
        if hasattr(sock, 'detach'):
            return _ORIGINAL_SOCKET(sock.family, sock.type, sock.proto, sock.detach())
        else:
            assert hasattr(_ORIGINAL_SOCKET, '_sock')
            return _ORIGINAL_SOCKET(_sock=sock._sock)


def get_peercred(sock):
    """Gets the (pid, uid, gid) for the client on the given *connected* socket."""
    buf = sock.getsockopt(_PEERCRED_LEVEL, _PEERCRED_OPTION, struct.calcsize('3i'))
    return struct.unpack('3i', buf)


class AlreadyInstalled(Exception):
    pass


class NotInstalled(Exception):
    pass


class ConfigurationConflict(Exception):
    pass


class SuspiciousClient(Exception):
    pass


class ManholeThread(_ORIGINAL_THREAD):
    """
    Thread that runs the infamous "Manhole". This thread is a `daemon` thread - it will exit if the main thread
    exits.

    On connect, a different, non-daemon thread will be started - so that the process won't exit while there's a
    connection to the manole.

    Args:
        sigmask (list of singal numbers): Signals to block in this thread.
        start_timeout (float): Seconds to wait for the thread to start. Emits a message if the thread is not running
            when calling ``start()``.
        bind_delay (float): Seconds to delay socket binding. Default: `no delay`.
        daemon_connection (bool): The connection thread is daemonic (dies on app exit). Default: ``False``.
    """

    def __init__(self,
                 get_socket, sigmask, start_timeout, connection_handler,
                 bind_delay=None, daemon_connection=False):
        super(ManholeThread, self).__init__()
        self.daemon = True
        self.daemon_connection = daemon_connection
        self.name = "Manhole"
        self.sigmask = sigmask
        self.serious = _ORIGINAL_EVENT()
        # time to wait for the manhole to get serious (to have a complete start)
        # see: http://emptysqua.re/blog/dawn-of-the-thread/
        self.start_timeout = start_timeout
        self.bind_delay = bind_delay
        self.connection_handler = connection_handler
        self.get_socket = get_socket
        self.should_run = False

    def stop(self):
        self.should_run = False

    def clone(self, **kwargs):
        """
        Make a fresh thread with the same options. This is usually used on dead threads.
        """
        return ManholeThread(
            self.get_socket, self.sigmask, self.start_timeout,
            connection_handler=self.connection_handler,
            daemon_connection=self.daemon_connection,
            **kwargs
        )

    def start(self):
        self.should_run = True
        super(ManholeThread, self).start()
        if not self.serious.wait(self.start_timeout) and not PY26:
            _LOG("WARNING: Waited %s seconds but Manhole thread didn't start yet :(" % self.start_timeout)

    def run(self):
        """
        Runs the manhole loop. Only accepts one connection at a time because:

        * This thread is a daemon thread (exits when main thread exists).
        * The connection need exclusive access to stdin, stderr and stdout so it can redirect inputs and outputs.
        """
        self.serious.set()
        if signalfd and self.sigmask:
            signalfd.sigprocmask(signalfd.SIG_BLOCK, self.sigmask)
        pthread_setname_np(self.ident, self.name)

        if self.bind_delay:
            _LOG("Delaying UDS binding %s seconds ..." % self.bind_delay)
            _ORIGINAL_SLEEP(self.bind_delay)

        sock = self.get_socket()
        while self.should_run:
            _LOG("Waiting for new connection (in pid:%s) ..." % os.getpid())
            try:
                client = ManholeConnectionThread(sock.accept()[0], self.connection_handler, self.daemon_connection)
                client.start()
                client.join()
            except (InterruptedError, socket.error) as e:
                if e.errno != errno.EINTR:
                    raise
                continue
            finally:
                client = None


class ManholeConnectionThread(_ORIGINAL_THREAD):
    """
    Manhole thread that handles the connection. This thread is a normal thread (non-daemon) - it won't exit if the
    main thread exits.
    """

    def __init__(self, client, connection_handler, daemon=False):
        super(ManholeConnectionThread, self).__init__()
        self.daemon = daemon
        self.client = force_original_socket(client)
        self.connection_handler = connection_handler
        self.name = "ManholeConnectionThread"

    def run(self):
        _LOG('Started ManholeConnectionThread thread. Checking credentials ...')
        pthread_setname_np(self.ident, "Manhole -------")
        pid, _, _ = check_credentials(self.client)
        pthread_setname_np(self.ident, "Manhole < PID:%s" % pid)
        try:
            self.connection_handler(self.client)
        except BaseException as exc:
            _LOG("ManholeConnectionThread failure: %r" % exc)


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

    _LOG("Accepted connection on fd:%s from %s" % (client.fileno(), client_name))
    return pid, uid, gid


def handle_connection_exec(client):
    """
    Alternate connection handler. No output redirection.
    """
    client.settimeout(None)
    fh = os.fdopen(client.detach() if hasattr(client, 'detach') else client.fileno())
    with closing(client):
        with closing(fh):
            payload = fh.readline()
            while payload:
                exec(payload)
                payload = fh.readline()


def handle_connection_repl(client):
    """
    Handles connection.
    """
    client.settimeout(None)
    # # disable this till we have evidence that it's needed
    # client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
    # # Note: setting SO_RCVBUF on UDS has no effect, see: http://man7.org/linux/man-pages/man7/unix.7.html

    backup = []
    old_interval = getinterval()
    patches = [('r', ('stdin', '__stdin__')), ('w', ('stdout', '__stdout__'))]
    if _MANHOLE.redirect_stderr:
        patches.append(('w', ('stderr', '__stderr__')))
    try:
        client_fd = client.fileno()
        for mode, names in patches:
            for name in names:
                backup.append((name, getattr(sys, name)))
                setattr(sys, name, _ORIGINAL_FDOPEN(client_fd, mode, 1 if PY3 else 0))
        try:
            handle_repl(_MANHOLE.locals)
        except Exception as exc:
            _LOG("REPL failed with %r." % exc)
        _LOG("DONE.")
    finally:
        try:
            # Change the switch/check interval to something ridiculous. We don't want to have other thread try
            # to write to the redirected sys.__std*/sys.std* - it would fail horribly.
            setinterval(2147483647)
            try:
                client.close()  # close before it's too late. it may already be dead
            except IOError:
                pass
            junk = []  # keep the old file objects alive for a bit
            for name, fh in backup:
                junk.append(getattr(sys, name))
                setattr(sys, name, fh)
            del backup
            for fh in junk:
                try:
                    if hasattr(fh, 'detach'):
                        fh.detach()
                    else:
                        fh.close()
                except IOError:
                    pass
                del fh
            del junk
        finally:
            setinterval(old_interval)
            _LOG("Cleaned up.")

_CONNECTION_HANDLER_ALIASES = {
    'repl': handle_connection_repl,
    'exec': handle_connection_exec
}


class ManholeConsole(code.InteractiveConsole):
    def __init__(self, *args, **kw):
        code.InteractiveConsole.__init__(self, *args, **kw)
        if _MANHOLE.redirect_stderr:
            self.file = sys.stderr
        else:
            self.file = sys.stdout

    def write(self, data):
        self.file.write(data)


def handle_repl(locals):
    """
    Dumps stacktraces and runs an interactive prompt (REPL).
    """
    dump_stacktraces()
    namespace = {
        'dump_stacktraces': dump_stacktraces,
        'sys': sys,
        'os': os,
        'socket': socket,
        'traceback': traceback,
    }
    if locals:
        namespace.update(locals)
    ManholeConsole(namespace).interact()


class Logger(object):
    """
    Internal object used for logging.

    Initially this is not configured. Until you call ``manhole.install()`` this logger object won't work (will raise
    ``NotInstalled``).
    """
    time = _get_original('time', 'time')
    enabled = True
    destination = None

    def configure(self, enabled, destination):
        self.enabled = enabled
        self.destination = destination

    def release(self):
        self.enabled = True
        self.destination = None

    def __call__(self, message):
        """
        Fail-ignorant logging function.
        """
        if self.enabled:
            if self.destination is None:
                raise NotInstalled("Manhole is not installed!")
            try:
                full_message = "Manhole[%s:%.4f]: %s\n" % (os.getpid(), self.time(), message)

                if isinstance(self.destination, int):
                    os.write(self.destination, full_message.encode('ascii', 'ignore'))
                else:
                    self.destination.write(full_message)
            except:  # pylint: disable=W0702
                pass


_LOG = Logger()


class Manhole(object):
    # Manhole core configuration
    # These are initialized when manhole is installed.
    daemon_connection = False
    locals = None
    original_os_fork = None
    original_os_forkpty = None
    redirect_stderr = True
    reinstall_delay = 0.5
    should_restart = None
    sigmask = _ALL_SIGNALS
    socket_path = None
    start_timeout = 0.5
    connection_handler = None
    previous_signal_handlers = None
    _thread = None

    def configure(self,
                  patch_fork=True, activate_on=None, sigmask=_ALL_SIGNALS, oneshot_on=None, thread=True,
                  start_timeout=0.5, socket_path=None, reinstall_delay=0.5, locals=None, daemon_connection=False,
                  redirect_stderr=True, connection_handler=handle_connection_repl):
        self.socket_path = socket_path
        self.reinstall_delay = reinstall_delay
        self.redirect_stderr = redirect_stderr
        self.locals = locals
        self.sigmask = sigmask
        self.daemon_connection = daemon_connection
        self.start_timeout = start_timeout
        self.previous_signal_handlers = {}
        self.connection_handler = _CONNECTION_HANDLER_ALIASES.get(connection_handler, connection_handler)

        if oneshot_on is None and activate_on is None and thread:
            self.thread.start()
            self.should_restart = True

        if oneshot_on is not None:
            oneshot_on = getattr(signal, 'SIG' + oneshot_on) if isinstance(oneshot_on, string) else oneshot_on
            self.previous_signal_handlers.setdefault(oneshot_on, signal.signal(oneshot_on, self.handle_oneshot))

        if activate_on is not None:
            activate_on = getattr(signal, 'SIG' + activate_on) if isinstance(activate_on, string) else activate_on
            if activate_on == oneshot_on:
                raise ConfigurationConflict('You cannot do activation of the Manhole thread on the same signal '
                                            'that you want to do oneshot activation !')
            self.previous_signal_handlers.setdefault(activate_on, signal.signal(activate_on, self.activate_on_signal))

        atexit.register(self.remove_manhole_uds)
        if patch_fork:
            if activate_on is None and oneshot_on is None and socket_path is None:
                self.patch_os_fork_functions()
            else:
                if activate_on:
                    _LOG("Not patching os.fork and os.forkpty. Activation is done by signal %s" % activate_on)
                elif oneshot_on:
                    _LOG("Not patching os.fork and os.forkpty. Oneshot activation is done by signal %s" % oneshot_on)
                elif socket_path:
                    _LOG("Not patching os.fork and os.forkpty. Using user socket path %s" % socket_path)

    def release(self):
        if self._thread:
            self._thread.stop()
            self._thread = None
        self.remove_manhole_uds()
        self.restore_os_fork_functions()
        for sig, handler in self.previous_signal_handlers.items():
            signal.signal(sig, handler)
        self.previous_signal_handlers.clear()

    @property
    def thread(self):
        if self._thread is None:
            self._thread = ManholeThread(
                self.get_socket, self.sigmask, self.start_timeout, self.connection_handler,
                daemon_connection=self.daemon_connection
            )
        return self._thread

    @thread.setter
    def thread(self, value):
        self._thread = value

    def get_socket(self):
        sock = _ORIGINAL_SOCKET(socket.AF_UNIX, socket.SOCK_STREAM)
        name = self.remove_manhole_uds()
        sock.bind(name)
        sock.listen(5)
        _LOG("Manhole UDS path: " + name)
        return sock

    def reinstall(self):
        """
        Reinstalls the manhole. Checks if the thread is running. If not, it starts it again.
        """
        with _LOCK:
            if not (self.thread.is_alive() and self.thread in _ORIGINAL__ACTIVE):
                self.thread = self.thread.clone(bind_delay=self.reinstall_delay)
                if self.should_restart:
                    self.thread.start()

    def handle_oneshot(self, _signum=None, _frame=None):
        try:
            try:
                sock = self.get_socket()
                _LOG("Waiting for new connection (in pid:%s) ..." % os.getpid())
                client = force_original_socket(sock.accept()[0])
                check_credentials(client)
                self.connection_handler(client)
            finally:
                self.remove_manhole_uds()
        except BaseException as exc:  # pylint: disable=W0702
            # we don't want to let any exception out, it might make the application misbehave
            _LOG("Oneshot failure: %r" % exc)

    def remove_manhole_uds(self):
        name = self.uds_name
        if os.path.exists(name):
            os.unlink(name)
        return name

    @property
    def uds_name(self):
        if self.socket_path is None:
            return "/tmp/manhole-%s" % os.getpid()
        return self.socket_path

    def patched_fork(self):
        """Fork a child process."""
        pid = self.original_os_fork()
        if not pid:
            _LOG('Fork detected. Reinstalling Manhole.')
            self.reinstall()
        return pid

    def patched_forkpty(self):
        """Fork a new process with a new pseudo-terminal as controlling tty."""
        pid, master_fd = self.original_os_forkpty()
        if not pid:
            _LOG('Fork detected. Reinstalling Manhole.')
            self.reinstall()
        return pid, master_fd

    def patch_os_fork_functions(self):
        self.original_os_fork, os.fork = os.fork, self.patched_fork
        self.original_os_forkpty, os.forkpty = os.forkpty, self.patched_forkpty
        _LOG("Patched %s and %s." % (self.original_os_fork, self.original_os_fork))

    def restore_os_fork_functions(self):
        if self.original_os_fork:
            os.fork = self.original_os_fork
        if self.original_os_forkpty:
            os.forkpty = self.original_os_forkpty

    def activate_on_signal(self, _signum, _frame):
        self.thread.start()


def install(verbose=True,
            verbose_destination=sys.__stderr__.fileno() if hasattr(sys.__stderr__, 'fileno') else sys.__stderr__,
            strict=True,
            **kwargs):
    """
    Installs the manhole.

    Args:
        verbose (bool): Set it to ``False`` to squelch the logging.
        verbose_destination (file descriptor or handle): Destination for verbose messages. Default is unbuffered stderr
            (stderr ``2`` file descriptor).
        patch_fork (bool): Set it to ``False`` if you don't want your ``os.fork`` and ``os.forkpy`` monkeypatched
        activate_on (int or signal name): set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you
            want the Manhole thread to start when this signal is sent. This is desireable in case you don't want the
            thread active all the time.
        oneshot_on (int or signal name): Set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you
            want the Manhole to listen for connection in the signal handler. This is desireable in case you don't want
            threads at all.
        thread (bool): Start the always-on ManholeThread. Default: ``True``. Automatically switched to ``False`` if
            ``oneshort_on`` or ``activate_on`` are used.
        sigmask (list of ints or signal names): Will set the signal mask to the given list (using
            ``signalfd.sigprocmask``). No action is done if ``signalfd`` is not importable.
            **NOTE**: This is done so that the Manhole thread doesn't *steal* any signals; Normally that is fine cause
            Python will force all the signal handling to be run in the main thread but signalfd doesn't.
        socket_path (str): Use a specifc path for the unix domain socket (instead of ``/tmp/manhole-<pid>``). This
            disables ``patch_fork`` as children cannot resuse the same path.
        reinstall_delay (float): Delay the unix domain socket creation *reinstall_delay* seconds. This
            alleviates cleanup failures when using fork+exec patterns.
        locals (dict): Names to add to manhole interactive shell locals.
        daemon_connection (bool): The connection thread is daemonic (dies on app exit). Default: ``False``.
        redirect_stderr (bool): Redirect output from stderr to manhole console. Default: ``True``.
        connection_handler (function): Connection handler to use. Use ``"exec"`` for simple implementation without output 
            redirection or your own function. (warning: this is for advanced users). Default: ``"repl"``.
    """
    # pylint: disable=W0603
    global _MANHOLE

    with _LOCK:
        if _MANHOLE is None:
            _MANHOLE = Manhole()
        else:
            if strict:
                raise AlreadyInstalled("Manhole already installed!")
            else:
                _LOG.release()
                _MANHOLE.release()  # Threads might be started here

    _LOG.configure(verbose, verbose_destination)
    _MANHOLE.configure(**kwargs)  # Threads might be started here
    return _MANHOLE


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

    print('\n'.join(lines), file=sys.stderr if _MANHOLE.redirect_stderr else sys.stdout)
