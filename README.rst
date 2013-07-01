===========================
       python-manhole
===========================

Manhole is a python daemon thread that will accept unix domain socket connections and present the
stacktraces for all threads and an interactive prompt.

Access to the socket is restricted to the application's effective user id or root.

Usage::

    import manhole
    manhole.install() # this will start the daemon thread

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
* Current implementation runs a daemon thread that waits for connection.
* Lightweight: does not fiddle with your process's singal handlers, settings, file descriptors, etc
* Compatible with apps that fork, reinstalls the Manhole thread after fork - had to monkeypatch os.fork/os.forkpty for this.

What happens when you actually connect to the socket
----------------------------------------------------

1. Credentials are checked (if it's same user or root)
2. sys.__std\*__/sys.std\* are be redirected to the UDS
3. Stacktraces for each thread are written to the UDS
3. REPL is started so you can fiddle with the process


Whishlist
---------

* Be compatible with eventlet/stackless (provide alternative implementation without thread)
* More configurable (chose what sys.__std\*__/sys.std\* to patch on connect time)


Requirements
============

Not sure yet ... maybe Python 2.6 and 2.7. Check Travis:

.. image:: https://secure.travis-ci.org/ionelmc/python-manhole.png
    :alt: Build Status
    :target: http://travis-ci.org/ionelmc/python-manhole

.. image:: https://coveralls.io/repos/ionelmc/python-manhole/badge.png?branch=master
    :alt: Coverage Status
    :target: https://coveralls.io/r/ionelmc/python-manhole

