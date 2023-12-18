import os
import sys

import manhole

stack_dump_file = '/tmp/manhole-pid'
uwsgi_signal_number = 17

try:
    import uwsgi

    if not os.path.exists(stack_dump_file):
        open(stack_dump_file, 'w')

    def open_manhole(dummy_signum):
        with open(stack_dump_file) as fh:
            pid = fh.read().strip()
            if pid == str(os.getpid()):
                inst = manhole.install(strict=False, thread=False)
                inst.handle_oneshot(dummy_signum, dummy_signum)

    uwsgi.register_signal(uwsgi_signal_number, 'workers', open_manhole)
    uwsgi.add_file_monitor(uwsgi_signal_number, stack_dump_file)

    print('Listening for stack manhole requests via %r' % (stack_dump_file,), file=sys.stderr)
except ImportError:
    print('Not running under uwsgi; unable to configure manhole trigger', file=sys.stderr)
except OSError:
    print('IOError creating manhole trigger %r' % (stack_dump_file,), file=sys.stderr)


def application(env, sr):
    sr('200 OK', [('Content-Type', 'text/plain'), ('Content-Length', '2')])
    yield b'OK'
