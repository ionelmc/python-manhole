===========================
       python-manhole
===========================

Manhole is a python daemon thread that will accept unix domain socket connections and present the
stacktraces for all threads and an interactive prompt.

Access to the socket is restricted to the application's effective user id or root.

    This is just like Twisted's `manhole <http://twistedmatrix.com/documents/current/api/twisted.manhole.html>`__.
    It's simpler (no dependencies) and it only runs on Unix domain sockets (in contrast to Twisted's manhole which
    can run on telnet or ssh).


Usage
=====

You can put this in your django settings, wsgi app file, some module that's always imported early etc::

    import manhole
    manhole.install() # this will start the daemon thread

    # and now you start your app, eg: server.serve_forever()

Now in a shell you can do either of these::

    netcat -U /tmp/manhole-1234
    socat - unix-connect:/tmp/manhole-1234
    socat readline unix-connect:/tmp/manhole-1234

Sample output::

    $ nc -U /tmp/manhole-1234

    Python 2.7.3 (default, Apr 10 2013, 06:20:15)
    [GCC 4.6.3] on linux2
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> dir()
    ['__builtins__', 'dump_stacktraces', 'os', 'socket', 'sys', 'traceback']
    >>> print 'foobar'
    foobar


Features
========

* Uses unix domain sockets, only root or same effective user can connect.
* Can run the connection in a thread or in a signal handler (see ``oneshot_on`` option).
* Can start the thread listening for connections from a singla handler (see ``activate_on`` option)
* Compatible with apps that fork, reinstalls the Manhole thread after fork - had to monkeypatch os.fork/os.forkpty for
  this.
* The thread is compatible with apps that use signalfd (will mask all signals for the Manhole threads).

Options
-------

``manhole.install(verbose=True, patch_fork=True, activate_on=None, sigmask=manhole.ALL_SIGNALS, oneshot_on=None)``

* ``verbose`` - set it to ``False`` to squelch the stderr ouput
* ``patch_fork`` - set it to ``False`` if you don't want your ``os.fork`` and ``os.forkpy`` monkeypatched
* ``activate_on`` - set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you want the Manhole thread
  to start when this signal is sent. This is desireable in case you don't want the thread active all the time.
* ``oneshot_on`` - set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you want the Manhole to
  listen for connection in the signal handler. This is desireable in case you don't want threads at all.
* ``sigmask`` - will set the signal mask to the given list (using ``signalfd.sigprocmask``). No action is done if
  ``signalfd`` is not importable. **NOTE**: This is done so that the Manhole thread doesn't *steal* any signals;
  Normally that is fine cause Python will force all the signal handling to be run in the main thread but signalfd
  doesn't.

What happens when you actually connect to the socket
----------------------------------------------------

1. Credentials are checked (if it's same user or root)
2. sys.__std\*__/sys.std\* are be redirected to the UDS
3. Stacktraces for each thread are written to the UDS
4. REPL is started so you can fiddle with the process


Whishlist
---------

* Be compatible with eventlet/stackless (provide alternative implementation without thread) - currently ``oneshot_on``
  should be usable for those. The are not tests done on eventlet/stackless for now.
* More configurable (chose what sys.__std\*__/sys.std\* to patch on connect time)
* Support windows ?!

Requirements
============

Not sure yet ... so far Python 2.6, 2.7, 3.2, 3.3 and pypy are tested in Travis:

.. image:: https://secure.travis-ci.org/ionelmc/python-manhole.png
    :alt: Build Status
    :target: http://travis-ci.org/ionelmc/python-manhole

.. image:: https://coveralls.io/repos/ionelmc/python-manhole/badge.png?branch=master
    :alt: Coverage Status
    :target: https://coveralls.io/r/ionelmc/python-manhole

Coverage is wrong, must be a bug in coveralls, it should be at least 80%-90% depending whether you count branches or
not.

Similar projects
================

* Twisted's `old manhole <http://twistedmatrix.com/documents/current/api/twisted.manhole.html>`__ and the `newer
  implementation <http://twistedmatrix.com/documents/current/api/twisted.conch.manhole.html>`__ (colors, serverside
  history).
* `wsgi-shell <https://github.com/GrahamDumpleton/wsgi-shell>`_ - spawns a thread.
* `pyrasite <https://github.com/lmacken/pyrasite>`_ - uses gdb to inject code.
* `pydbattach <https://github.com/albertz/pydbattach>`_ - uses gdb to inject code.
