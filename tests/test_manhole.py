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

    def test_simple_r1(self):
        self.run_simple(1)

    def test_simple_r2(self):
        self.run_simple(2)

    def test_simple_r3(self):
        self.run_simple(3)

    def test_simple_r4(self):
        self.run_simple(4)

    def test_simple_r5(self):
        self.run_simple(5)

    def test_simple_r6(self):
        self.run_simple(6)

    def test_simple_r7(self):
        self.run_simple(7)

    def test_simple_r8(self):
        self.run_simple(8)

    def test_simple_r9(self):
        self.run_simple(9)

    #def test_simple_r10(self):
        #self.run_simple(10)

    def run_simple(self, count):
        with TestProcess(sys.executable, __file__, 'daemon', 'test_simple') as proc:
            with self._dump_on_error(proc.read):
                self._wait_for_strings(proc.read, 1, '/tmp/manhole-')
                uds_path = re.findall("(/tmp/manhole-\d+)", proc.read())[0]
                for i in range(count):
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(0.05)
                    sock.connect(uds_path)
                    with TestSocket(sock) as client:
                        proc.reset()
                        with self._dump_on_error(client.read):
                            self._wait_for_strings(client.read, 1,
                                "ThreadID",
                                "ProcessID",
                                ">>>",
                            )
                            sock.send("print 'FOOBAR'\n")
                            self._wait_for_strings(client.read, 1, "FOOBAR")

                            self._wait_for_strings(proc.read, 1,
                                'from pid:%s uid:%s' % (os.getpid(), os.getuid()),
                            )
                            sock.shutdown(socket.SHUT_RDWR)
                            sock.close()
                    self._wait_for_strings(proc.read, 1, 'Cleaning up.')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
        logging.basicConfig(
            level=logging.DEBUG,
            format='[pid=%(process)d - %(asctime)s]: %(name)s - %(levelname)s - %(message)s',
        )
        test_name = sys.argv[2]
        import manhole
        manhole.install()
        if test_name == 'test_simple':
            time.sleep(10)
        else:
            raise RuntimeError('Invalid test spec.')
        print 'DIED.'
    else:
        unittest.main()
