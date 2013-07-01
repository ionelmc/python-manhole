import unittest
import os
import sys
import subprocess
import socket
import fcntl
import errno
import time
import logging
import re
import atexit
from contextlib import contextmanager
from cStringIO import StringIO

class BufferingBase(object):

    BUFFSIZE = 8192
    def __init__(self, fd):
        self.buff = StringIO()
        self.fd = fd

    def read(self):
        """
        Read any available data fd. Does NOT block.
        """
        try:
            while 1:
                data = os.read(self.fd, self.BUFFSIZE)
                if not data:
                    break
                self.buff.write(data)
        except OSError, e:
            if e.errno not in (
                errno.EAGAIN, errno.EWOULDBLOCK,
                errno.EINPROGRESS
            ):
                raise
        return self.buff.getvalue()

    def reset(self):
        self.buff = StringIO()

class TestProcess(BufferingBase):
    def __init__(self, *args):
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        fd = self.proc.stdout.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        super(TestProcess, self).__init__(fd)

    @property
    def is_alive(self):
        return self.proc.poll() is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        try:
            self.proc.terminate()
            # wait 1 second for the process to die gracefully
            for _ in range(10):
                time.sleep(0.1)
                if self.proc.poll() is not None:
                    return
            self.proc.kill()
        except OSError as exc:
            if exc.errno != errno.ESRCH:
                raise

class TestSocket(BufferingBase):
    BUFFSIZE = 8192
    def __init__(self, sock):
        sock.setblocking(0)
        self.sock = sock
        super(TestSocket, self).__init__(sock.fileno())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        try:
            self.sock.close()
        except OSError as exc:
            if exc.errno not in (errno.EBADF, errno.EBADFD):
                raise

class ManholeTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def _wait_for_strings(self, cb, seconds, *strings):
        """
        This checks that *string appear in cb(), IN THE GIVEN ORDER !
        """
        buff = '<UNINITIALIZED>'

        for _ in range(int(seconds * 20)):
            time.sleep(0.05)
            buff = cb()
            check_strings = list(strings)
            check_strings.reverse()
            for line in buff.splitlines():
                if not check_strings:
                    break
                if check_strings[-1] in line:
                    check_strings.pop()
            if not check_strings:
                return

        raise AssertionError("Waited %0.2fsecs but %s did not appear in output in the given order !" % (
            seconds, strings
        ))

    @contextmanager
    def _dump_on_error(self, cb):
        try:
            yield
        except Exception:
            print "*********** OUTPUT ***********"
            print cb()
            print "******************************"
            raise

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
            with self._dump_on_error(proc.read):
                self._wait_for_strings(proc.read, 1, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self._wait_for_strings(proc.read, 1, 'Waiting for new connection')
                for _ in range(count):
                    proc.reset()
                    self.assertManholeRunning(proc, uds_path)

    def assertManholeRunning(self, proc, uds_path):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.05)
        sock.connect(uds_path)
        with TestSocket(sock) as client:
            with self._dump_on_error(client.read):
                self._wait_for_strings(client.read, 1,
                    "ThreadID",
                    "ProcessID",
                    ">>>",
                )
                sock.send("print 'FOOBAR'\n")
                self._wait_for_strings(client.read, 1, "FOOBAR")

                self._wait_for_strings(proc.read, 1,
                    'from PID:%s UID:%s' % (os.getpid(), os.getuid()),
                )
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
        self._wait_for_strings(proc.read, 1,
            'Cleaning up.',
            'Waiting for new connection'
        )

    def test_with_fork(self):
        with TestProcess(sys.executable, __file__, 'daemon', 'test_with_fork') as proc:
            with self._dump_on_error(proc.read):
                self._wait_for_strings(proc.read, 1, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self._wait_for_strings(proc.read, 1, 'Waiting for new connection')
                for _ in range(2):
                    proc.reset()
                    self.assertManholeRunning(proc, uds_path)

                proc.reset()
                self._wait_for_strings(proc.read, 3, 'Fork detected')
                self._wait_for_strings(proc.read, 1, '/tmp/manhole-')
                new_uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                self.failIfEqual(uds_path, new_uds_path)

                self._wait_for_strings(proc.read, 1, 'Waiting for new connection')
                for _ in range(2):
                    proc.reset()
                    self.assertManholeRunning(proc, new_uds_path)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
        logging.basicConfig(
            level=logging.DEBUG,
            format='[pid=%(process)d - %(asctime)s]: %(name)s - %(levelname)s - %(message)s',
        )
        import coverage
        coverage.process_startup()

        test_name = sys.argv[2]
        import manhole
        manhole.install()
        if test_name == 'test_simple':
            time.sleep(10)
        if test_name == 'test_with_fork':
            time.sleep(2)
            pid = os.fork()
            if pid:
                @atexit.register
                def cleanup():
                    os.kill(pid, 9)
                os.waitpid(pid, 0)
            else:
                time.sleep(10)
        else:
            raise RuntimeError('Invalid test spec.')
        print 'DIED.'
    else:
        unittest.main()
